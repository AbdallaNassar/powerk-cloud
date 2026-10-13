import asyncio
import time
from datetime import datetime

from powerk.devices import Device, Hub
from powerk.rules import clean_rule, clean_settings, public_settings
from powerk.store import Db, Store


def test_energy_deltas_reset_and_history(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # energy: counter deltas go to the hourly table; a counter reset counts its new value
        energy[1] = 510
        dev.counter_ts -= 1800                          # 500 Wh in 30 min is plausible (1 kW)
        await sess.refresh()
        energy[1] = 20
        await sess.refresh()
        assert hub.db._sum_wh("AABBCCDDEEFF", 0) == 520, "500 Wh delta + 20 Wh after reset"
        h = hub.db.history("AABBCCDDEEFF", "day", 2.0)
        assert len(h["buckets"]) == 24 and h["total_kwh"] == 0.52 and h["total_cost"] == 1.04
        assert h["per_outlet"][0] == {"n": 1, "kwh": 0.52}
        for rng, count in (("week", 7), ("month", 30), ("year", 12)):
            assert len(hub.db.history("AABBCCDDEEFF", rng, 2.0)["buckets"]) == count
    run_strip(check)


def test_names_persist(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # names
        store.set_name("AABBCCDDEEFF", 0, "Desk")
        store.set_name("AABBCCDDEEFF", 3, "Fridge")
        snap = hub.snapshot()["devices"][0]
        assert snap["label"] == "Desk" and snap["outlets"][2]["name"] == "Fridge" and snap["outlets"][0]["name"] == ""
        assert Store(tmp / "powerk.json").name("AABBCCDDEEFF", 3) == "Fridge", "names persist"
    run_strip(check)


def test_restore_known_strips(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # known strips come back (offline) after a restart
        hub2 = Hub(Store(tmp / "powerk.json"), Db(":memory:"))
        hub2.restore()
        assert "AABBCCDDEEFF" in hub2.devices and hub2.devices["AABBCCDDEEFF"].online is False
        hub2.db.conn.close()
    run_strip(check)


def test_offline_gap_and_month_boundary(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # an offline gap spreads the counter delta over the hours it covers
        db = Db(":memory:")
        t = datetime(2026, 1, 5, 12, 30).timestamp()
        db.add_energy("M", 1, 300.0, t, since=t - 3 * 3600)
        assert len(db.conn.execute("SELECT * FROM energy").fetchall()) == 4 and db._sum_wh("M", 0) == 300.0
        db2 = Db(":memory:")
        t = datetime(2026, 2, 1, 0, 0).timestamp()
        db2.add_energy("M", 1, 300.0, t, since=t - 3 * 3600)    # [21:00, 00:00): nothing lands in February
        assert db2._sum_wh("M", t) == 0 and db2._sum_wh("M", 0) == 300.0
        db.conn.close()
        db2.conn.close()
    run_strip(check)


def test_counter_glitches_and_rebase(run_strip):
    async def check(env):
        store, hub, engine = env.store, env.hub, env.engine
        dev, sess = env.dev, env.sess
        state_on, energy, sent = env.state_on, env.energy, env.sent
        tmp, writer, port = env.data, env.writer, env.port
        now = time.time()
        # a one-reading counter glitch keeps the baseline; a jump that persists becomes the new baseline
        g = Device("AABBCCDDEEFF", "m", "f", "")
        recs = lambda wh: [dict(n=n, on=True, power_w=1.0, energy_kwh=wh / 1000 if n == 1 else 0.0, temp_c=30) for n in (1, 2, 3, 4)]
        hub3 = Hub(Store(None), Db(":memory:"))
        for i, wh in enumerate((10, 10000, 11)):
            hub3.on_getinfo(g, recs(wh), 1.79e9 + 5 * i)
        assert hub3.db._sum_wh(None, 0) == 1, "10 -> spike -> 11 counts 1 Wh"
        for i, wh in enumerate((90000, 90000, 90000, 90001)):
            hub3.on_getinfo(g, recs(wh), 1.79e9 + 100 + 5 * i)
        assert hub3.db._sum_wh(None, 0) == 2 and g.counter_wh[1] == 90001
        hub3.db.conn.close()
    run_strip(check)
