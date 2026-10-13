import asyncio
import time
from datetime import datetime

from powerk.devices import Device, Hub
from powerk.rules import clean_rule, clean_settings, public_settings
from powerk.store import Db, Store


def test_parser_commands_and_master_button(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        dev = hub.devices["AABBCCDDEEFF"]
        sess = hub.session("aabbccddeeff")
        assert dev.outlets[1]["on"] is False and dev.outlets[2]["on"] is True
        assert dev.outlets[2]["power_w"] == 5.3 and dev.outlets[2]["energy_kwh"] == 0.01
        assert dev.outlets[1]["temp_c"] == 31 and dev.outlets[4]["temp_c"] == 34
        assert dev.voltage_v == 224.5 and dev.rssi == -52
        assert dev.current_a == 0.02
    
        assert await sess.set_outlets([2], False) is True
        assert dev.outlets[2]["on"] is False and state_on == set()
        snapshot = hub.snapshot()["devices"][0]
        assert snapshot["on"] is False and snapshot["energy_kwh"] == 0.04
    
        writer.write(b"up:event:onoff:0:on\r\n")        # master button switches all four
        await writer.drain()
        await asyncio.sleep(0.2)
        assert all(o["on"] for o in dev.outlets.values())
    run_strip(check)


def test_allowlist_rejects_unknown_strip(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # allowlist: an unknown strip is refused
        hub.allow = {"AABBCCDDEEFF"}
        r2, w2 = await asyncio.open_connection("127.0.0.1", port)
        w2.write(b"up:bootinfo:x;112233445566;112233445566;1;connect\r\n")
        await w2.drain()
        assert await r2.read() == b"" and "112233445566" not in hub.devices
        w2.close()
        await w2.wait_closed()
    run_strip(check)
