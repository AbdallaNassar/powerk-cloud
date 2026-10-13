import asyncio
import time
from datetime import datetime

from powerk.devices import Device, Hub
from powerk.rules import clean_rule, clean_settings, public_settings
from powerk.store import Db, Store


def test_rule_validation_and_timer_consumption(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # rule validation
        now = time.time()
        for bad in ({"kind": "schedule", "mac": "AABBCCDDEEFF", "outlets": [1], "at": "25:00", "days": [0], "on": True},
                    {"kind": "timer", "mac": "AABBCCDDEEFF", "outlets": [1], "minutes": 0, "on": True},
                    {"kind": "cycle", "mac": "AABBCCDDEEFF", "outlets": [9], "on_min": 1, "off_min": 1},
                    {"kind": "autooff", "mac": "nope", "outlets": [1], "below_w": 3, "for_min": 1},
                    {"kind": "schedule", "mac": "AABBCCDDEEFF", "outlets": [1], "at": "07:00", "days": [0], "on": "false"}):
            try:
                clean_rule(bad, now)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
    
        for bad in ({"kind": "cycle", "mac": "AABBCCDDEEFF", "outlets": [1.0], "on_min": 1, "off_min": 1},
                    {"kind": "timer", "mac": "AABBCCDDEEFF", "outlets": [1], "minutes": float("inf"), "on": True},
                    {"kind": "autooff", "mac": "AABBCCDDEEFF", "outlets": [1], "below_w": float("nan"), "for_min": 1}):
            try:
                clean_rule(bad, now)
                raise AssertionError(f"accepted {bad}")
            except ValueError:
                pass
        t1 = clean_rule({"kind": "timer", "mac": "AABBCCDDEEFF", "outlets": [1], "minutes": 5, "on": True, "fire_at": 1}, now)
        assert t1["fire_at"] == round(now + 300), "a client cannot set fire_at"
        store.put_rule(t1)
        assert store.consume_rule(dict(t1, on=False)) is False and store.rule(t1["id"]), "an edited timer is not consumed"
        store.delete_rule(t1["id"])
    run_strip(check)


def test_schedule_once_per_minute(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # schedule fires once in its minute, on the right weekday
        base = datetime.now().replace(hour=7, minute=30, second=5, microsecond=0).timestamp()
        wd = datetime.fromtimestamp(base).weekday()
        sched = clean_rule({"kind": "schedule", "mac": "AABBCCDDEEFF", "outlets": [0], "at": "07:30", "days": [wd], "on": False}, base)
        store.put_rule(sched)
        await engine.tick(base)
        assert state_on == set(), "schedule switched all off"
        state_on.add(1)
        await engine.tick(base + 20)
        assert state_on == {1}, "same minute does not fire twice"
        assert engine.view(sched, base + 60)["next_at"] == int(base - 5 + 7 * 86400), "next run is next week"
        store.delete_rule(sched["id"])
    run_strip(check)


def test_timer_fires_once(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # timer fires once, then deletes itself
        timer = clean_rule({"kind": "timer", "mac": "AABBCCDDEEFF", "outlets": [3], "minutes": 5, "on": True}, now)
        store.put_rule(timer)
        await engine.tick(now + 60)
        assert 3 not in state_on
        await engine.tick(now + 301)
        assert 3 in state_on and store.rule(timer["id"]) is None
    run_strip(check)


def test_cycle(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # cycle: on, then off after on_min, then on after off_min
        state_on.clear()
        await sess.refresh()
        cyc = clean_rule({"kind": "cycle", "mac": "AABBCCDDEEFF", "outlets": [4], "on_min": 2, "off_min": 3}, now)
        store.put_rule(cyc)
        await engine.tick(now)
        assert 4 in state_on and engine.view(cyc, now)["phase"] == "on"
        await engine.tick(now + 119)
        assert 4 in state_on
        await engine.tick(now + 121)
        assert 4 not in state_on and engine.view(cyc, now)["phase"] == "off"
        await engine.tick(now + 121 + 181)
        assert 4 in state_on
        store.delete_rule(cyc["id"])
        engine.reset(cyc["id"])
    run_strip(check)


def test_autooff_fresh_readings(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # auto-off: outlet 2 draws 5.3 W; below 10 W for 1 min -> off
        state_on.clear()
        state_on.add(2)
        auto = clean_rule({"kind": "autooff", "mac": "AABBCCDDEEFF", "outlets": [2], "below_w": 10, "for_min": 1}, now)
        store.put_rule(auto)
        await sess.refresh()                            # the reading starts the low-draw countdown
        engine.rt[auto["id"]]["below_since"][2] = now   # pin it to the fake clock
        await engine.tick(now)
        dev.reported_at = now + 30                      # the engine runs on a fake clock; keep readings "fresh"
        await engine.tick(now + 30)
        assert 2 in state_on
        dev.reported_at = now + 61
        await engine.tick(now + 61)
        assert 2 not in state_on and any("Auto-off" in t for t in sent)
        state_on.add(2)
        await sess.refresh()
        assert 2 in engine.rt[auto["id"]]["below_since"]
        dev.outlets[2] = dict(dev.outlets[2], power_w=50.0)
        engine.observe(dev, now)                        # one high reading cancels the countdown
        assert 2 not in engine.rt[auto["id"]]["below_since"]
        store.delete_rule(auto["id"])
        state_on.discard(2)
        await sess.refresh()
    run_strip(check)
