"""Scoped, bounded WebSocket feeds. Commands remain on the HTTP API."""
from __future__ import annotations

import asyncio
import secrets
import time
from collections import OrderedDict
from urllib.parse import urlsplit

from starlette.websockets import WebSocket, WebSocketDisconnect

from .ratelimit import RateLimited
from .security import client_ip
from .sessions import token_hash

INTERVAL = 0.25
HEARTBEAT = 25.0
QUEUE_SIZE = 32
SEND_TIMEOUT = 5.0
SOCKET_LIMIT = 5
POWER_THRESHOLD = 1.0  # watts, relative to the last queued reading (not the last poll)


def same_origin(ws: WebSocket) -> bool:
    """Use the configured HTTPS deployment mode, never untrusted forwarded headers."""
    scheme = 'https' if ws.app.state.secure_cookies or ws.url.scheme == 'wss' else 'http'
    try:
        origin = urlsplit(ws.headers.get('origin', ''))
        host = urlsplit(scheme + '://' + ws.headers.get('host', ''))
        return (origin.scheme == scheme and bool(origin.hostname) and
                origin.hostname == host.hostname and
                (origin.port or (443 if scheme == 'https' else 80)) ==
                (host.port or (443 if scheme == 'https' else 80)) and
                not origin.username and not origin.password and not origin.path and
                not origin.query and not origin.fragment)
    except ValueError:
        return False


def changed(before, after) -> bool:
    if isinstance(after, dict):
        return before.keys() != after.keys() or any(
            abs(after[k] - before[k]) >= POWER_THRESHOLD if k == 'power_w' else changed(before[k], after[k])
            for k in after if k not in ('reported_at', 'current_a'))
    if isinstance(after, list):
        return len(before) != len(after) or any(changed(a, b) for a, b in zip(before, after))
    return before != after


class FeedClosed(Exception):
    def __init__(self, code):
        self.code = code


class Connection:
    def __init__(self, manager, ws, identity, credential_hash, ip):
        self.manager, self.ws = manager, ws
        self.identity, self.credential_hash, self.ip = identity, credential_hash, ip
        self.user_id = identity.user['id'] if identity else None
        self.pending = OrderedDict()
        self.ready = asyncio.Event()
        self.stopped = asyncio.Event()
        self.finished = asyncio.Event()
        self.code = None
        self.previous = {}
        self.access = set()
        self.cursor = 0

    def valid(self):
        if self.identity is None:
            return True
        db = self.manager.hub.db
        with db.lock:
            return bool(db.conn.execute(
                'SELECT 1 FROM access_tokens a JOIN session_families f ON f.id=a.family_id '
                'WHERE a.token_hash=? AND a.expires_at>? AND f.revoked_at IS NULL',
                (self.credential_hash, time.time())).fetchone())

    def snapshot(self):
        snap = self.manager.hub.snapshot(self.user_id)
        snap.update(local_ip=self.manager.state.local_ip, port=self.manager.state.port)
        return snap

    @staticmethod
    async def work(function, *args):
        # Cancelling an asyncio wrapper does not stop a thread using SQLite.
        worker = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
            worker.result()
            raise

    def collect(self, initial=False):
        hub = self.manager.hub
        with hub.db.lock:
            if not self.valid():
                raise FeedClosed(4401)
            snap = self.snapshot()
            access = set(hub.sharing.accessible(self.user_id)) if self.user_id is not None else set(hub.devices)
            cursor = hub.db.last_event_id()
            events = [] if initial or cursor == self.cursor else [
                ev for ev in reversed(hub.db.events(500, user_id=self.user_id)) if ev['id'] > self.cursor]
        return snap, access, cursor, events

    def enqueue(self, packet):
        kind = packet['type']
        key = (kind, packet['strip']['mac'] if kind == 'strip' else packet.get('id'))
        if key not in self.pending and len(self.pending) >= self.manager.queue_size:
            raise FeedClosed(4408)
        self.pending[key] = packet
        if kind == 'access':
            self.pending.move_to_end(key, last=False)
        self.ready.set()

    def prepare(self, packet):
        """Check again at delivery, including queued frames and role changes."""
        hub = self.manager.hub
        with hub.db.lock:
            if not self.valid():
                raise FeedClosed(4401)
            kind = packet['type']
            if kind == 'state':
                return dict(self.snapshot(), type='state')
            if kind in ('strip', 'event'):
                mac = packet['strip']['mac'] if kind == 'strip' else packet['mac']
                if self.user_id is not None and (not mac or not hub.sharing.role(mac, self.user_id)):
                    return None
                if kind == 'strip':
                    strip = next((d for d in self.snapshot()['devices'] if d['mac'] == mac), None)
                    return {'type': 'strip', 'strip': strip} if strip else None
            if kind in ('event', 'ping'):
                packet = dict(packet, unread_alerts=hub.db.unread(hub.read_pointer(self.user_id), self.user_id))
            return packet

    async def produce(self):
        snap, self.access, self.cursor, _ = await self.work(self.collect, True)
        self.previous = {d['mac']: d for d in snap['devices']}
        self.enqueue({'type': 'state'})
        ping_at = time.monotonic() + self.manager.heartbeat
        while True:
            await asyncio.sleep(self.manager.interval)
            snap, access, self.cursor, events = await self.work(self.collect)
            if access != self.access:
                self.access = access
                # Remove stale state before queue capacity is considered.
                self.pending = OrderedDict((k, p) for k, p in self.pending.items() if
                    not (p['type'] in ('strip', 'event') and
                         (p['strip']['mac'] if p['type'] == 'strip' else p['mac']) not in access))
                self.enqueue({'type': 'access'})
            current = {d['mac']: d for d in snap['devices']}
            self.previous = {k: v for k, v in self.previous.items() if k in current}
            for mac, strip in current.items():
                if mac not in self.previous or changed(self.previous[mac], strip):
                    self.enqueue({'type': 'strip', 'strip': strip})
                    self.previous[mac] = strip
            for ev in events:
                self.enqueue(dict(ev, type='event'))
            if time.monotonic() >= ping_at:
                self.enqueue({'type': 'ping', 'server_time': int(time.time())})
                ping_at = time.monotonic() + self.manager.heartbeat

    async def send(self):
        next_send = 0.0
        while True:
            await self.ready.wait()
            await asyncio.sleep(max(0, next_send - time.monotonic()))
            if not self.pending:
                self.ready.clear()
                continue
            _, packet = self.pending.popitem(last=False)
            if not self.pending:
                self.ready.clear()
            packet = await self.work(self.prepare, packet)
            if packet is None:
                continue
            try:
                await asyncio.wait_for(self.ws.send_json(packet), self.manager.send_timeout)
            except asyncio.TimeoutError:
                raise FeedClosed(4408) from None
            next_send = time.monotonic() + self.manager.interval

    async def receive(self):
        while True:
            message = await self.ws.receive()
            if message['type'] == 'websocket.disconnect':
                return
            # This is a read-only feed; tolerate small application pongs only.
            if message.get('text') not in ('pong', '{"type":"pong"}'):
                raise FeedClosed(1008)

    def stop(self, code):
        self.code = code
        self.stopped.set()

    async def run(self):
        tasks = [asyncio.create_task(f()) for f in (self.produce, self.send, self.receive, self.stopped.wait)]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    task.result()
                except FeedClosed as err:
                    self.code = err.code
                except (WebSocketDisconnect, OSError):
                    pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.code:
                try:
                    await asyncio.wait_for(self.ws.close(self.code), self.manager.send_timeout)
                except (WebSocketDisconnect, OSError, RuntimeError, asyncio.TimeoutError):
                    pass


class LiveUpdates:
    def __init__(self, state):
        self.state, self.hub = state, state.hub
        self.connections = set()
        self.interval, self.heartbeat = INTERVAL, HEARTBEAT
        self.queue_size, self.send_timeout = QUEUE_SIZE, SEND_TIMEOUT

    def authenticate(self, ws):
        auth = ws.headers.get('authorization', '')
        credential = None
        if auth.lower().startswith('bearer '):
            credential = auth[7:]
        elif ws.cookies.get('powerk_access'):
            if not same_origin(ws):
                raise FeedClosed(4401)
            credential = ws.cookies['powerk_access']
        if credential is not None:
            identity = self.state.accounts.sessions.resolve(credential)
            if identity:
                return identity, token_hash(credential)
            raise FeedClosed(4401)
        token = self.state.token
        if token and any(secrets.compare_digest(value.encode(), token.encode()) for value in
                         (ws.headers.get('x-token', ''), ws.query_params.get('t', ''))):
            return None, None
        raise FeedClosed(4401)

    async def recheck(self):
        """API calls invoke this after auth mutations, including refresh replay."""
        for connection in list(self.connections):
            if not await asyncio.to_thread(connection.valid):
                connection.stop(4401)

    async def handle(self, ws):
        ip = client_ip(ws.client.host if ws.client else '', ws.headers, self.state.trusted_proxies)
        try:
            self.state.rate_limiter.take('ws', ip)
            identity, credential = await asyncio.to_thread(self.authenticate, ws)
            uid = identity.user['id'] if identity else None
            if (sum(c.ip == ip for c in self.connections) >= SOCKET_LIMIT or
                    sum(c.user_id == uid for c in self.connections) >= SOCKET_LIMIT):
                raise FeedClosed(4429)
        except RateLimited as err:
            if self.state.rate_limiter.sample(err.key):
                await asyncio.to_thread(self.state.accounts.audit.record, 'rate_limit', None, ip, 'ws')
            # ASGI close before accept is translated to HTTP 403 by uvicorn.
            # Complete the upgrade only to transmit the documented close code.
            await ws.accept()
            await ws.close(4429)
            return
        except FeedClosed as err:
            await ws.accept()
            await ws.close(err.code)
            return
        connection = Connection(self, ws, identity, credential, ip)
        # Reserve both caps before accept yields to another connection.
        self.connections.add(connection)
        try:
            await ws.accept()
            await connection.run()
        finally:
            self.connections.discard(connection)
            connection.finished.set()

    async def close(self):
        connections = list(self.connections)
        for connection in connections:
            connection.stop(1001)
        await asyncio.gather(*(c.finished.wait() for c in connections))
