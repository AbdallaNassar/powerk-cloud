import ast
import inspect
import json
from collections import Counter
from pathlib import Path

from powerk import devices, notify, protocol, rules, store
from powerk.api import REPO_ROOT


def test_unchanged_protocol_energy_and_rule_semantics_are_verbatim(legacy, provision):
    for module, names in [
        (protocol, ["parse_getinfo"]),
        (store, ["Store", "hour_start", "day_start", "month_start"]),
        (devices, ["Device", "Session", "parse_macs"]),
        (rules, ["_int_in", "_is_outlet", "clean_rule", "next_schedule", "public_settings", "clean_settings"]),
        (provision, ["local_ipv4s", "setup_command", "cmd_provision"]),
    ]:
        for name in names:
            assert inspect.getsource(getattr(module, name)) == inspect.getsource(getattr(legacy, name)), name
    for new, old, names in [
        # Db now composes atomic live snapshots with an RLock, and add_event returns
        # its inserted ID for FCM. Schema/history compatibility is tested below.
        (store.Db, legacy.Db, ["add_energy", "_sum_wh", "totals", "history"]),
        (rules.Engine, legacy.Engine, ["observe", "_current", "reset", "view", "_switch", "_where", "tick", "_run", "_schedule", "_timer"]),
    ]:
        for name in names:
            source = inspect.getsource(getattr(new, name))
            if new is rules.Engine and name == 'tick':
                # Tracking tasks enables bounded shutdown; scheduling is identical.
                source = source.replace('task = asyncio.create_task(job)\n'
                                        '                self.action_tasks.add(task)\n'
                                        '                task.add_done_callback(self.action_tasks.discard)',
                                        'asyncio.create_task(job)')
            assert source == inspect.getsource(getattr(old, name)), name


def test_all_constants_match(legacy):
    modules = (protocol, notify, rules)
    for name, value in vars(legacy).items():
        if not name.isupper() or name in ("PAGE", "FONT_FILES"):
            continue
        actual = next(getattr(m, name) for m in modules if hasattr(m, name))
        if hasattr(value, "pattern"):
            assert (actual.pattern, actual.flags) == (value.pattern, value.flags), name
        else:
            assert actual == value, name


def test_every_legacy_selftest_assertion_is_ported(legacy):
    class Assets(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == "legacy" and node.attr in ("PAGE", "FONT_FILES"):
                return ast.Name(id=node.attr, ctx=ast.Load())
            return self.generic_visit(node)

    def assertions(tree):
        return Counter(ast.dump(Assets().visit(node.test), include_attributes=False)
                       for node in ast.walk(tree) if isinstance(node, ast.Assert))
    expected = assertions(ast.parse(inspect.getsource(legacy._selftest)))
    ported = Counter()
    for path in Path(__file__).parent.glob("test_*.py"):
        ported.update(assertions(ast.parse(path.read_text(encoding="utf-8"))))
    assert not (expected - ported), "A legacy selftest assertion was dropped"


def test_json_is_readable_and_writable_in_both_directions(legacy, tmp_path):
    path = tmp_path / "powerk.json"
    old = legacy.Store(path)
    old.set_name("AABBCCDDEEFF", 0, "Desk / ????")
    old.update_settings({"telegram_token": "123:example", "budget": 100.0})
    old.set_meta("devices", {"AABBCCDDEEFF": {"model": "lgutap", "fw": "1"}})
    old.set_meta("events_read_id", 4)
    old.put_rule(legacy.clean_rule({"kind": "timer", "mac": "AABBCCDDEEFF", "outlets": [1], "minutes": 5, "on": True}, 1000))
    new = store.Store(path)
    assert new.data == old.data
    before = path.read_bytes()
    new.save()
    assert path.read_bytes() == before
    new.set_name("AABBCCDDEEFF", 3, "Fridge")
    new.raise_meta("events_read_id", 2)
    assert new.meta("events_read_id") == 4
    new.update_settings({"price_kwh": 3.5})
    reopened = legacy.Store(path)
    assert reopened.data == new.data
    before = path.read_bytes()
    reopened.save()
    assert path.read_bytes() == before
    assert set(json.loads(before)) == {"names", "rules", "settings", "meta"}


def test_sqlite_schema_and_data_in_both_directions(legacy, tmp_path):
    path = str(tmp_path / "powerk.db")
    old = legacy.Db(path)
    old.add_energy("AABBCCDDEEFF", 1, 100, 1790000000)
    old.add_event({"ts": 1790000000, "level": "warn", "code": "offline", "mac": "AABBCCDDEEFF", "outlet": None,
                   "text": "offline", "params": {}})
    schema = old.conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    old.conn.close()
    new = store.Db(path)
    assert new.conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall() == schema
    assert new._sum_wh("AABBCCDDEEFF", 0) == 100
    assert new.events()[0]["code"] == "offline"
    new.add_energy("AABBCCDDEEFF", 1, 50, 1790000000)
    new.add_event({"ts": 1790000001, "level": "alert", "code": "budget", "mac": None, "outlet": None,
                   "text": "budget", "params": {"pct": 50, "cost": 50}})
    expected = new.events()
    new.conn.close()
    old = legacy.Db(path)
    assert old._sum_wh("AABBCCDDEEFF", 0) == 150
    assert old.events() == expected
    assert old.unread(0) == 2
    assert old.conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall() == schema
    old.conn.close()


def test_supported_python_syntax():
    for path in (REPO_ROOT / "server/powerk").rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 10))
    ast.parse((REPO_ROOT / "tools/provision.py").read_text(encoding="utf-8"), feature_version=(3, 8))
