"""Shared real-TCP fake strip and HTTP fixtures; no async pytest plugin required."""
from __future__ import annotations

import asyncio
import importlib.util
import itertools
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

# Prefer the package over the untouched powerk.py in the repository root.
SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent
sys.path.insert(0, str(SERVER_ROOT))

from fastapi.testclient import TestClient
from powerk.api import create_app
from powerk.devices import Hub
from powerk.rules import Engine
from powerk.store import Db, Store

MAC = "AABBCCDDEEFF"


def _fake_tags(state_on: set[int], energy: dict[int, int] | None = None) -> str:
    """A 'up:getinfo:' payload shaped like the real strip's, for offline checks."""
    energy = energy or {}
    return ":".join(
        f"{n}:{n * 111};{'on' if n in state_on else 'off'};{int(n in state_on)};0;0;"
        f"{5300 if n == 2 and n in state_on else 0};{energy.get(n, 10):08X};00000000;00000000;0;00;{30 + n}"
        for n in (1, 2, 3, 4)
    )



class FakeStrip:
    def __init__(self, data):
        data.mkdir(parents=True, exist_ok=True)
        self.data = data
        self.store = Store(data / "powerk.json")
        self.hub = Hub(self.store, Db(str(data / "powerk.db")))
        self.hub.legacy_notifications = True  # legacy selftest fixtures keep their global channel
        self.sent = []
        self.hub.notifier.send = lambda _title, text, _settings=None: self.sent.append(text)
        self.engine = Engine(self.hub)
        self.state_on = {2}
        self.energy = {1: 10, 2: 10, 3: 10, 4: 10}
        self.commands = []
        self.connections = set()

    async def start(self):
        def connected(reader, writer):
            task = asyncio.create_task(self.hub.handle_client(reader, writer))
            self.connections.add(task)
            task.add_done_callback(self.connections.discard)

        self.server = await asyncio.start_server(connected, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.strip_task = asyncio.create_task(self.fake_strip())
        self.writer.write(b"up:bootinfo:LGU+-TAP-HW002;aabbccddeeff;001122334455;1.0.66;connect\r\n")
        self.writer.write(b"up:power_report:1:224500\r\n")
        self.writer.write(b"up:query:-52\r\n")
        await self.writer.drain()

        async def ready():
            while MAC not in self.hub.devices or not self.hub.devices[MAC].reported_at:
                await asyncio.sleep(0.01)
        await asyncio.wait_for(ready(), 3)
        self.dev = self.hub.devices[MAC]
        self.sess = self.hub.session(MAC)
        return self

    async def fake_strip(self):
        while True:
            raw = await self.reader.readline()
            if not raw:
                return
            line = raw.decode().strip()
            self.commands.append(line)
            if line == "up:getinfo:all":
                self.writer.write(f"up:getinfo:{_fake_tags(self.state_on, self.energy)}\r\n".encode())
                await self.writer.drain()
            elif line.startswith("up:onoff:"):
                _, _, ch, val = line.split(":")
                (self.state_on.add if val == "on" else self.state_on.discard)(int(ch))

    async def close(self):
        self.server.close()
        self.writer.close()
        await self.writer.wait_closed()
        tasks = [self.strip_task, *self.connections]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.server.wait_closed()
        self.hub.db.conn.close()


@pytest.fixture
def run_strip(tmp_path):
    def run(check):
        async def exercise():
            env = FakeStrip(tmp_path)
            await env.start()
            try:
                return await check(env)
            finally:
                await env.close()
        return asyncio.run(exercise())
    return run


@pytest.fixture
def client_factory(tmp_path):
    sequence = itertools.count()

    @contextmanager
    def make(token=None, connected=False, apk=None, **options):
        # Non-auth regressions use an explicit legacy credential. Auth tests opt out.
        default_auth = token is None
        token = "fixture-token" if default_auth else token
        env = FakeStrip(tmp_path / str(next(sequence)))
        app = create_app(env.hub, env.engine, token=token, local_ip="192.0.2.1", port=10086,
                         apk=apk if apk is not None else tmp_path / "missing.apk", **options)
        with TestClient(app) as client:
            if default_auth:
                client.headers["X-Token"] = token
            if connected:
                client.portal.call(env.start)
            try:
                yield env, client
            finally:
                async def cancel_commands():
                    pending = list(app.state.command_tasks)
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                client.portal.call(cancel_commands)
                if connected:
                    client.portal.call(env.close)
                else:
                    env.hub.db.conn.close()
    return make


@pytest.fixture(scope="session")
def legacy():
    spec = importlib.util.spec_from_file_location("legacy_powerk", REPO_ROOT / "powerk.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def provision():
    spec = importlib.util.spec_from_file_location("standalone_provision", REPO_ROOT / "tools/provision.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
