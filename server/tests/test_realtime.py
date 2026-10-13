"""Live transport boundaries, using the real ASGI application and session store."""
import asyncio
import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from powerk.devices import Device
from powerk.realtime import Connection
from powerk.sessions import token_hash
from test_sharing import MAC, OTHER, headers, identities, own


@pytest.mark.parametrize('mode,accepted', [
    ('bearer', True), ('cookie', True), ('bad-origin', False), ('no-origin', False),
    ('legacy-header', True), ('legacy-query', True), ('legacy-cookie', False),
    ('invalid-bearer', False), ('none', False),
])
def test_ws_auth_and_initial_scoping(client_factory, mode, accepted):
    with client_factory(token='shared') as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        for mac in (MAC, OTHER):
            env.hub.devices[mac] = Device(mac, 'tap', '1', '')
        h, path = {}, '/api/ws'
        if mode in ('bearer', 'invalid-bearer'):
            h = headers(pairs, 'owner')
            if mode == 'invalid-bearer':
                h.update(Authorization='Bearer invalid', Cookie='powerk_access=' + pairs['owner']['access_token'], Origin='http://testserver')
        elif mode in ('cookie', 'bad-origin', 'no-origin'):
            h['Cookie'] = 'powerk_access=' + pairs['owner']['access_token']
            if mode != 'no-origin':
                h['Origin'] = 'http://testserver' if mode == 'cookie' else 'https://evil.example'
        elif mode == 'legacy-header':
            h['X-Token'] = 'shared'
        elif mode == 'legacy-query':
            path += '?t=shared'
        elif mode == 'legacy-cookie':
            h['Cookie'] = 'powerk_t=shared'
        if not accepted:
            with pytest.raises(WebSocketDisconnect) as error:
                with client.websocket_connect(path, headers=h) as ws:
                    ws.receive_json()
            assert error.value.code == 4401
            return
        with client.websocket_connect(path, headers=h) as ws:
            state = ws.receive_json()
            assert state['type'] == 'state'
            assert state['local_ip'] == '192.0.2.1' and state['port'] == 10086
            assert {d['mac'] for d in state['devices']} == ({MAC, OTHER} if mode.startswith('legacy') else {MAC})


def test_socket_closes_on_logout(client_factory):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        h = headers(pairs, 'owner')
        with client.websocket_connect('/api/ws', headers=h) as ws:
            assert ws.receive_json()['type'] == 'state'
            assert client.post('/api/auth/logout', headers=h, json={}).status_code == 200
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 4401


def test_push_registration_and_ownership(client_factory):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        owner, stranger = headers(pairs, 'owner'), headers(pairs, 'stranger')
        body = {'token': 'device:one', 'platform': 'android', 'app_version': '1.0'}
        assert client.post('/api/me/push-tokens', headers=owner, json=body).status_code == 200
        assert client.get('/api/me/notifications', headers=owner).json()['fcm'] == {'enabled': False, 'devices': 1}
        assert client.delete('/api/me/push-tokens/device:one', headers=stranger).status_code == 404
        assert client.delete('/api/me/push-tokens/device:one', headers=owner).status_code == 200
        assert client.get('/api/me/notifications', headers=owner).json()['fcm']['devices'] == 0


def test_push_cap_and_logout_cleanup(client_factory):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        h = headers(pairs, 'owner')
        for n in range(11):
            assert client.post('/api/me/push-tokens', headers=h, json={
                'token': f'device{n:02}', 'platform': 'android', 'app_version': '1',
            }).status_code == 200
        with env.hub.db.lock:
            tokens = [r[0] for r in env.hub.db.conn.execute('SELECT token FROM push_tokens ORDER BY token')]
        assert tokens == [f'device{n:02}' for n in range(1, 11)]
        assert client.post('/api/auth/logout', headers=h, json={}).status_code == 200
        with env.hub.db.lock:
            assert env.hub.db.conn.execute('SELECT COUNT(*) FROM push_tokens').fetchone()[0] == 0


def test_strip_event_and_access_updates(client_factory):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        env.hub.devices[MAC] = Device(MAC, 'tap', '1', '')
        client.app.state.live.heartbeat = .2
        client.app.state.live.interval = .02
        with client.websocket_connect('/api/ws', headers=headers(pairs, 'viewer')) as ws:
            assert len(ws.receive_json()['devices']) == 1
            env.hub.devices[MAC].online = True
            env.hub.event('warn', 'offline', 'visible', MAC)
            env.hub.event('warn', 'offline', 'hidden', OTHER)
            received = []
            while not any(m['type'] == 'ping' for m in received):
                received.append(ws.receive_json())
            assert any(m['type'] == 'strip' and m['strip']['online'] for m in received)
            assert [m['text'] for m in received if m['type'] == 'event'] == ['visible']
            uid = pairs['viewer']['user']['id']
            env.hub.sharing.change_access(MAC, uid, pairs['owner']['user']['id'], 'control')
            assert ws.receive_json()['strip']['role'] == 'control'
            env.hub.sharing.change_access(MAC, uid, pairs['owner']['user']['id'], None)
            env.hub.devices[MAC].online = False
            env.hub.event('alert', 'temp_high', 'removed', MAC)
            received = []
            while not any(m['type'] == 'ping' for m in received):
                received.append(ws.receive_json())
            assert any(m['type'] == 'access' for m in received)
            assert not any(m['type'] in ('strip', 'event') for m in received)


@pytest.mark.parametrize('operation', ['unclaim', 'leave', 'remove'])
def test_queued_frames_recheck_access(client_factory, operation):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        env.hub.devices[MAC] = Device(MAC, 'tap', '1', '')
        sessions = client.app.state.accounts.sessions
        identity = sessions.resolve(pairs['viewer']['access_token'])
        connection = Connection(client.app.state.live, None, identity, token_hash(pairs['viewer']['access_token']), 'ip')
        event = {'type': 'event', 'id': 1, 'mac': MAC, 'text': 'private'}
        strip = {'type': 'strip', 'strip': {'mac': MAC}}
        assert connection.prepare(event) and connection.prepare(strip)
        if operation == 'unclaim':
            env.hub.sharing.unclaim(MAC)
        elif operation == 'leave':
            env.hub.sharing.leave(MAC, identity.user['id'])
        else:
            env.hub.sharing.change_access(MAC, identity.user['id'], pairs['owner']['user']['id'], None)
        assert connection.prepare(event) is None and connection.prepare(strip) is None
        assert connection.prepare({'type': 'state'})['devices'] == []


def test_access_gain_and_transfer_refresh_roles(client_factory):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        env.hub.devices[MAC] = Device(MAC, 'tap', '1', '')
        client.app.state.live.interval = .02
        with client.websocket_connect('/api/ws', headers=headers(pairs, 'stranger')) as ws:
            assert ws.receive_json()['devices'] == []
            uid = pairs['owner']['user']['id']
            phone = pairs['stranger']['user']['phone']
            env.hub.sharing.share(MAC, phone, 'viewer', uid)
            assert ws.receive_json() == {'type': 'access'}
            assert ws.receive_json()['strip']['role'] == 'viewer'
            env.hub.sharing.transfer(MAC, phone, uid)
            assert ws.receive_json()['strip']['role'] == 'owner'


def test_access_token_expiry_closes_even_if_family_has_new_token(client_factory):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        pair = pairs['owner']
        with client.websocket_connect('/api/ws', headers=headers(pairs, 'owner')) as ws:
            ws.receive_json()
            client.app.state.accounts.sessions.refresh(pair['refresh_token'])
            with env.hub.db.lock, env.hub.db.conn:
                env.hub.db.conn.execute('UPDATE access_tokens SET expires_at=? WHERE token_hash=?',
                                        (int(time.time()) - 1, token_hash(pair['access_token'])))
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 4401


class Socket:
    """A controllably slow transport for the actual connection manager."""
    def __init__(self, app, token, ip='192.0.2.1', blocked=False):
        self.app, self.client = app, SimpleNamespace(host=ip)
        self.headers = {'authorization': 'Bearer ' + token}
        self.cookies, self.query_params = {}, {}
        self.output, self.closed = asyncio.Queue(), asyncio.Queue()
        self.blocked, self.accepted = blocked, False

    async def accept(self):
        self.accepted = True

    async def send_json(self, packet):
        if self.blocked:
            await asyncio.Event().wait()
        await self.output.put((time.monotonic(), packet))

    async def receive(self):
        await asyncio.Event().wait()

    async def close(self, code):
        await self.closed.put(code)


@pytest.mark.parametrize('same_user', [True, False])
def test_user_and_ip_socket_caps_and_release(client_factory, same_user):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        async def exercise():
            manager = client.app.state.live
            active = []
            try:
                for n in range(5):
                    token = pairs['owner' if same_user else list(pairs)[n % 4]]['access_token']
                    socket = Socket(client.app, token, f'192.0.2.{n + 1}' if same_user else '192.0.2.1')
                    task = asyncio.create_task(manager.handle(socket))
                    active.append(task)
                    await asyncio.wait_for(socket.output.get(), 2)
                extra = Socket(client.app, pairs['owner']['access_token'], '192.0.2.99' if same_user else '192.0.2.1')
                await manager.handle(extra)
                assert await extra.closed.get() == 4429 and extra.output.empty()
                active.pop().cancel()
                await asyncio.sleep(.01)
                task = asyncio.create_task(manager.handle(extra))
                active.append(task)
                assert (await asyncio.wait_for(extra.output.get(), 2))[1]['type'] == 'state'
            finally:
                for task in active:
                    task.cancel()
                await asyncio.gather(*active, return_exceptions=True)
        client.portal.call(exercise)


@pytest.mark.parametrize('overflow', [False, True])
def test_slow_consumers_drop_on_deadline_or_full_queue(client_factory, overflow):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        async def exercise():
            manager = client.app.state.live
            manager.send_timeout = 1 if overflow else .03
            manager.interval, manager.queue_size = .01, 2
            socket = Socket(client.app, pairs['owner']['access_token'], blocked=True)
            task = asyncio.create_task(manager.handle(socket))
            try:
                while not socket.accepted:
                    await asyncio.sleep(.001)
                await asyncio.sleep(.03)
                if overflow:
                    for n in range(3):
                        env.hub.event('warn', 'offline', str(n), MAC)
                assert await asyncio.wait_for(socket.closed.get(), .5) == 4408
                await task
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        client.portal.call(exercise)


def test_bursts_coalesce_and_small_power_changes_do_not_emit(client_factory):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        dev = env.hub.devices[MAC] = Device(MAC, 'tap', '1', '')
        async def exercise():
            socket = Socket(client.app, pairs['owner']['access_token'])
            task = asyncio.create_task(client.app.state.live.handle(socket))
            try:
                initial = await asyncio.wait_for(socket.output.get(), 2)
                dev.outlets[1]['power_w'] = .5
                dev.reported_at = time.time()
                await asyncio.sleep(.3)
                assert socket.output.empty()
                for n in range(20):
                    dev.outlets[1]['power_w'] = n * 2
                    await asyncio.sleep(.01)
                await asyncio.sleep(.55)
                readings = []
                while not socket.output.empty():
                    readings.append(socket.output.get_nowait())
                assert 1 <= len(readings) <= 3
                assert readings[-1][1]['strip']['power_w'] == 38
                assert all(b[0] - a[0] >= .24 for a, b in zip([initial] + readings, readings))
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        client.portal.call(exercise)


def test_push_and_ws_rate_limits(client_factory):
    from powerk.ratelimit import LIMITS, RateLimiter
    limiter = RateLimiter(limits={**LIMITS, 'push_tokens': (1, 3600), 'ws': (1, 60)})
    with client_factory(token='', rate_limiter=limiter) as (env, client):
        pairs = identities(env, client)
        h = headers(pairs, 'owner')
        assert client.post('/api/me/push-tokens', headers=h, json={'token': 'one', 'platform': 'android'}).status_code == 200
        r = client.delete('/api/me/push-tokens/one', headers=h)
        assert r.status_code == 429 and int(r.headers['Retry-After']) > 0
        for expected in (4401, 4429):
            with pytest.raises(WebSocketDisconnect) as error:
                with client.websocket_connect('/api/ws') as ws:
                    ws.receive_json()
            assert error.value.code == expected


def test_revocation_and_password_change_remove_other_family_tokens_and_sockets(client_factory):
    with client_factory(token='') as (env, client):
        accounts = client.app.state.accounts
        pair = accounts.register('+201055555555', 'correct horse 55555', '', '')
        with env.hub.db.lock, env.hub.db.conn:
            other = accounts.sessions.create_locked(pair['user'], 'second', '')
        current = accounts.sessions.resolve(pair['access_token'])
        h, remote_h = {'Authorization': 'Bearer ' + pair['access_token']}, {'Authorization': 'Bearer ' + other['access_token']}
        for token, auth in [('one', h), ('two', remote_h)]:
            assert client.post('/api/me/push-tokens', headers=auth, json={'token': token, 'platform': 'android'}).status_code == 200
        with client.websocket_connect('/api/ws', headers=remote_h) as ws:
            ws.receive_json()
            assert client.post('/api/auth/password', headers=h, json={
                'current_password': 'correct horse 55555', 'new_password': 'another good horse 6789',
            }).status_code == 200
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 4401
        assert client.app.state.push_tokens.for_user(pair['user']['id']) == [('one', current.family_id)]
        with client.websocket_connect('/api/ws', headers=h) as ws:
            ws.receive_json()
            assert client.delete('/api/auth/sessions/' + current.family_id, headers=h).status_code == 200
            with pytest.raises(WebSocketDisconnect) as error:
                ws.receive_json()
            assert error.value.code == 4401
        assert client.app.state.push_tokens.for_user(pair['user']['id']) == []
        rows = accounts.audit.list(pair['user']['id'])
        assert sum(row['action'] == 'push_token_register' for row in rows) == 2
        assert sum(row['action'] == 'push_token_delete' for row in rows) == 2
        for row in rows:
            if row['action'].startswith('push_token_'):
                assert len(row['target']) == 16 and row['target'] not in ('one', 'two')
                assert 'token' not in row['detail']


def test_real_upgrade_reports_auth_close_code_and_streams_state(client_factory):
    import uvicorn
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosedError
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        async def exercise():
            listener = socket.socket()
            listener.bind(('127.0.0.1', 0))
            server = uvicorn.Server(uvicorn.Config(client.app, log_level='error', lifespan='off',
                                                 ws='websockets-sansio', proxy_headers=False))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                while not server.started:
                    await asyncio.sleep(.005)
                url = f'ws://127.0.0.1:{listener.getsockname()[1]}/api/ws'
                async with connect(url) as ws:
                    with pytest.raises(ConnectionClosedError) as error:
                        await ws.recv()
                    assert error.value.rcvd.code == 4401
                async with connect(url, additional_headers=headers(pairs, 'owner')) as ws:
                    assert json.loads(await ws.recv())['type'] == 'state'
            finally:
                server.should_exit = True
                await asyncio.wait_for(task, 3)
                listener.close()
        client.portal.call(exercise)


@pytest.mark.parametrize('origin,accepted', [('https://testserver', True), ('https://testserver:443', True),
    ('http://testserver', False), ('https://testserver:444', False), ('https://testserver.evil.example', False),
    ('null', False), ('https://testserver/path', False)])
def test_cookie_origin_on_https_proxy(client_factory, origin, accepted):
    with client_factory(token='', secure_cookies=True) as (env, client):
        pairs = identities(env, client)
        h = {'Cookie': 'powerk_access=' + pairs['owner']['access_token'], 'Origin': origin}
        with client.websocket_connect('/api/ws', headers=h) as ws:
            if accepted:
                assert ws.receive_json()['type'] == 'state'
            else:
                with pytest.raises(WebSocketDisconnect) as error:
                    ws.receive_json()
                assert error.value.code == 4401


def test_http_command_changes_arrive_on_socket(client_factory):
    with client_factory(token='', connected=True) as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        h = headers(pairs, 'owner')
        with client.websocket_connect('/api/ws', headers=h) as ws:
            assert not ws.receive_json()['devices'][0]['outlets'][0]['on']
            assert client.post('/api/onoff', headers=h, json={'mac': MAC, 'outlet': 1, 'on': True}).json()['confirmed']
            packets = [ws.receive_json(), ws.receive_json()]
            assert any(m['type'] == 'strip' and m['strip']['outlets'][0]['on'] for m in packets)
            assert any(m['type'] == 'event' and m['code'] == 'onoff' for m in packets)


@pytest.mark.parametrize('body', [{}, {'token': 'device', 'platform': 'ios'},
    {'token': '', 'platform': 'android'}, {'token': 'a/b', 'platform': 'android'},
    {'token': 'device', 'platform': 'android', 'app_version': 1}])
def test_invalid_push_registration_and_cookie_csrf(client_factory, body):
    with client_factory(token='shared') as (env, client):
        pairs = identities(env, client)
        assert client.post('/api/me/push-tokens', headers=headers(pairs, 'owner'), json=body).status_code == 400
        valid = {'token': 'device', 'platform': 'android'}
        assert client.post('/api/me/push-tokens', headers={'X-Token': 'shared'}, json=valid).status_code == 401
        cookie = {'Cookie': 'powerk_access=' + pairs['owner']['access_token'] + '; powerk_csrf=check'}
        assert client.post('/api/me/push-tokens', headers=cookie, json=valid).status_code == 403
        assert client.post('/api/me/push-tokens', headers={**cookie, 'X-CSRF-Token': 'check'}, json=valid).status_code == 200


def test_refresh_failure_hook_cleans_revoked_tokens(client_factory):
    # Reuse/grace policy belongs to Sessions. Any refresh that revokes a family
    # must run the API cleanup, including when refresh raises AuthError.
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        pair = pairs['owner']
        h = headers(pairs, 'owner')
        assert client.post('/api/me/push-tokens', headers=h, json={'token': 'device', 'platform': 'android'}).status_code == 200
        identity = client.app.state.accounts.sessions.resolve(pair['access_token'])
        client.app.state.accounts.sessions.revoke(identity, identity.family_id)
        assert client.post('/api/auth/refresh', json={'refresh_token': pair['refresh_token']}).status_code == 401
        with env.hub.db.lock:
            assert env.hub.db.conn.execute('SELECT COUNT(*) FROM push_tokens').fetchone()[0] == 0


def test_shutdown_waits_for_snapshot_thread_before_database_closes(client_factory, monkeypatch):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        entered, release = threading.Event(), threading.Event()
        snapshot = env.hub.snapshot
        def blocked(*args):
            entered.set()
            assert release.wait(2)
            return snapshot(*args)
        monkeypatch.setattr(env.hub, 'snapshot', blocked)
        async def exercise():
            manager = client.app.state.live
            ws = Socket(client.app, pairs['owner']['access_token'])
            task = asyncio.create_task(manager.handle(ws))
            try:
                while not entered.is_set():
                    await asyncio.sleep(.001)
                close = asyncio.create_task(manager.close())
                await asyncio.sleep(.03)
                assert not close.done()
                release.set()
                await asyncio.wait_for(close, 2)
                await task
                assert await ws.closed.get() == 1001
            finally:
                release.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        client.portal.call(exercise)
