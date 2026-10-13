import asyncio
import time
from datetime import datetime

from powerk.devices import Device, Hub
from powerk.rules import clean_rule, clean_settings, public_settings
from powerk.store import Db, Store


def test_temperature_alarm_edges(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # alarms are edge-triggered: one alert per raise
        store.update_settings({"temp_max_c": 34})        # only outlet 4 (34 C) is at the limit
        await sess.refresh()
        await sess.refresh()
        assert sum("temp high" in t for t in sent) == 1, sent
        assert hub.snapshot()["devices"][0]["outlets"][3]["alarm"] == "temp_high"
    run_strip(check)


def test_budget_threshold_once(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        hub.db.add_energy("AABBCCDDEEFF", 1, 520, now)
        # budget: 0.52 kWh * 100 = 52 -> 50 % of 100
        store.update_settings({"price_kwh": 100.0, "budget": 100.0})
        hub.db._totals.clear()
        engine._budget(now)
        engine._budget(now)
        assert sum("budget 50%" in t for t in sent) == 1
        assert hub.db.events(5)[0]["code"] == "budget"
    run_strip(check)


def test_settings_validation_and_write_only_token(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # settings validation
        for bad in ({"price_kwh": "x"}, {"budget": -1}, {"ntfy_url": "ftp://x"}, {"nope": 1}):
            try:
                clean_settings(bad)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
        assert "telegram_token" not in public_settings(store.settings())
        store.update_settings(clean_settings({"telegram_token": "123:abc"}))
        assert public_settings(store.settings())["telegram_configured"] is True
    run_strip(check)


def test_event_order_paging_and_unread(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        for level in ("info", "warn", "alert", "info"):
            hub.event(level, "test", "test event")
        # events: newest first, ids, unread counts only warn/alert
        evs = hub.db.events(50)
        assert evs[0]["id"] > evs[-1]["id"] and all(isinstance(e["ts"], int) for e in evs)
        assert hub.db.unread(0) == sum(e["level"] != "info" for e in evs) > 0
        assert hub.db.unread(hub.db.last_event_id()) == 0
        assert [e["id"] for e in hub.db.events(2, before_id=evs[0]["id"])] == [evs[1]["id"], evs[2]["id"]]
    run_strip(check)
