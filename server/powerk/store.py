"""The existing JSON store and SQLite schema, with their original locks."""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from .protocol import DEFAULT_SETTINGS


class Store:
    """powerk.json: names, rules, settings, small bookkeeping. Shared by web threads and the loop."""

    def __init__(self, path: Path | None):
        self.path = path
        self.lock = threading.RLock()
        self.data = {"names": {}, "rules": [], "settings": dict(DEFAULT_SETTINGS), "meta": {}}
        if path and path.is_file():
            try:
                loaded = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError) as err:
                raise SystemExit(f"cannot read {path}: {err} (fix or move it away)")
            for key in ("names", "rules", "meta"):
                if isinstance(loaded.get(key), type(self.data[key])):
                    self.data[key] = loaded[key]
            if isinstance(loaded.get("settings"), dict):
                self.data["settings"].update({k: v for k, v in loaded["settings"].items() if k in DEFAULT_SETTINGS})

    def save(self) -> None:
        if not self.path:
            return
        with self.lock:
            text = json.dumps(self.data, indent=1, ensure_ascii=False)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(text, "utf-8")
            os.replace(tmp, self.path)

    # names: {"MAC": {"0": "strip label", "1": "Fridge", ...}}
    def name(self, mac: str, n: int) -> str:
        with self.lock:
            return self.data["names"].get(mac, {}).get(str(n), "")

    def set_name(self, mac: str, n: int, name: str) -> None:
        with self.lock:
            names = self.data["names"].setdefault(mac, {})
            if name:
                names[str(n)] = name
            else:
                names.pop(str(n), None)
            self.save()

    def settings(self) -> dict:
        with self.lock:
            return dict(self.data["settings"])

    def update_settings(self, changes: dict) -> dict:
        with self.lock:
            self.data["settings"].update(changes)
            self.save()
            return dict(self.data["settings"])

    def meta(self, key: str, default=None):
        with self.lock:
            return copy.deepcopy(self.data["meta"].get(key, default))

    def set_meta(self, key: str, value) -> None:
        with self.lock:
            self.data["meta"][key] = value
            self.save()

    def raise_meta(self, key: str, value: int) -> int:
        """Move a numeric cursor forward only (two clients marking read never move it back)."""
        with self.lock:
            value = max(value, self.data["meta"].get(key, 0))
            self.data["meta"][key] = value
            self.save()
            return value

    def rules(self) -> list[dict]:
        with self.lock:
            return copy.deepcopy(self.data["rules"])

    def rule(self, rule_id: str) -> dict | None:
        with self.lock:
            return next((copy.deepcopy(r) for r in self.data["rules"] if r["id"] == rule_id), None)

    def put_rule(self, rule: dict) -> None:
        with self.lock:
            rules = self.data["rules"]
            for i, r in enumerate(rules):
                if r["id"] == rule["id"]:
                    rules[i] = rule
                    break
            else:
                rules.append(rule)
            self.save()

    def consume_rule(self, rule: dict) -> bool:
        """Delete a rule only if it is unchanged since the caller read it (a timer edited meanwhile survives)."""
        with self.lock:
            if rule not in self.data["rules"]:
                return False
            self.data["rules"].remove(rule)
            self.save()
            return True

    def delete_rule(self, rule_id: str) -> bool:
        with self.lock:
            before = len(self.data["rules"])
            self.data["rules"] = [r for r in self.data["rules"] if r["id"] != rule_id]
            if len(self.data["rules"]) == before:
                return False
            self.save()
            return True


def hour_start(ts: float) -> int:
    return int(datetime.fromtimestamp(ts).replace(minute=0, second=0, microsecond=0).timestamp())


def day_start(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def month_start(dt: datetime, back: int = 0) -> datetime:
    y, m = divmod(dt.year * 12 + dt.month - 1 - back, 12)
    return datetime(y, m + 1, 1)


class Db:
    """powerk.db: hourly energy per outlet + the event log."""

    def __init__(self, path: str):
        # Live snapshots compose existing readers while holding one permission boundary.
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        with self.lock, self.conn:
            self.conn.execute("CREATE TABLE IF NOT EXISTS energy(mac TEXT, outlet INTEGER, hour INTEGER, wh REAL,"
                              " PRIMARY KEY(mac, outlet, hour))")
            self.conn.execute("CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, level TEXT, code TEXT,"
                              " mac TEXT, outlet INTEGER, text TEXT, params TEXT)")
        self._totals: dict[str, tuple[float, dict]] = {}

    def add_energy(self, mac: str, outlet: int, wh: float, ts: float, since: float | None = None) -> None:
        """Add wh consumed up to ts. After a long gap (strip offline, counter kept running) the delta
        is spread evenly over the hours since the previous reading instead of landing in one hour."""
        hours = [hour_start(ts)]
        if since and ts - since > 3600:
            since = max(since, ts - 366 * 86400)
            hours = sorted({hour_start(t) for t in range(int(since), int(ts), 900)} | {hour_start(ts - 1)})
        share = wh / len(hours)
        with self.lock, self.conn:
            self.conn.executemany("INSERT INTO energy VALUES(?,?,?,?) ON CONFLICT(mac, outlet, hour)"
                                  " DO UPDATE SET wh = wh + excluded.wh", [(mac, outlet, h, share) for h in hours])
        self._totals.clear()

    def _sum_wh(self, mac: str | None, since: float) -> float:
        sql, args = "SELECT COALESCE(SUM(wh), 0) FROM energy WHERE hour >= ?", [int(since)]
        if mac:
            sql, args = sql + " AND mac = ?", args + [mac]
        with self.lock:
            return self.conn.execute(sql, args).fetchone()[0]

    def totals(self, mac: str | None = None) -> dict:
        """today/month kWh, cached a few seconds (every /api/state asks)."""
        key = mac or "*"
        hit = self._totals.get(key)
        if hit and time.monotonic() - hit[0] < 10:
            return hit[1]
        now = datetime.now()
        value = {
            "today_kwh": round(self._sum_wh(mac, day_start(now).timestamp()) / 1000.0, 3),
            "month_kwh": round(self._sum_wh(mac, month_start(now).timestamp()) / 1000.0, 3),
        }
        self._totals[key] = (time.monotonic(), value)
        return value

    def history(self, mac: str, rng: str, price: float, outlet: int | None = None, now: datetime | None = None) -> dict:
        now = now or datetime.now()
        if rng == "day":                                   # 24 elapsed hours, stepped in epoch time (DST-safe)
            unit, last = "hour", hour_start(now.timestamp())
            starts = [datetime.fromtimestamp(last - (23 - i) * 3600) for i in range(24)]
        elif rng in ("week", "month"):
            days = 7 if rng == "week" else 30
            unit, first = "day", day_start(now) - timedelta(days=days - 1)
            starts = [day_start(first + timedelta(days=i, hours=3)) for i in range(days)]   # +3h: DST-safe day step
        elif rng == "year":
            unit = "month"
            starts = [month_start(now, back) for back in range(11, -1, -1)]
        else:
            raise ValueError("range must be day, week, month or year")

        def bucket(ts: int) -> int:
            if unit == "hour":
                return ts
            dt = datetime.fromtimestamp(ts)
            if unit == "day":
                dt = day_start(dt)
            elif unit == "month":
                dt = month_start(dt)
            return int(dt.timestamp())

        sql, args = "SELECT outlet, hour, wh FROM energy WHERE mac = ? AND hour >= ?", [mac, int(starts[0].timestamp())]
        if outlet:
            sql, args = sql + " AND outlet = ?", args + [outlet]
        with self.lock:
            rows = self.conn.execute(sql, args).fetchall()
        sums = {(last - (23 - i) * 3600 if unit == "hour" else int(s.timestamp())): 0.0 for i, s in enumerate(starts)}
        per_outlet = {n: 0.0 for n in (1, 2, 3, 4)}
        for n, hour, wh in rows:
            key = bucket(hour)
            if key in sums:
                sums[key] += wh
                per_outlet[n] = per_outlet.get(n, 0.0) + wh
        total = sum(sums.values()) / 1000.0
        return {
            "range": rng, "unit": unit,
            "buckets": [{"t": t, "kwh": round(wh / 1000.0, 3), "cost": round(wh / 1000.0 * price, 2)} for t, wh in sums.items()],
            "total_kwh": round(total, 3), "total_cost": round(total * price, 2),
            "per_outlet": [{"n": n, "kwh": round(wh / 1000.0, 3)} for n, wh in sorted(per_outlet.items())],
        }

    def add_event(self, ev: dict) -> int:
        with self.lock, self.conn:
            result = self.conn.execute("INSERT INTO events(ts, level, code, mac, outlet, text, params) VALUES(?,?,?,?,?,?,?)",
                              (ev["ts"], ev["level"], ev["code"], ev["mac"], ev["outlet"], ev["text"], json.dumps(ev["params"])))
            self.conn.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - 500")
            return result.lastrowid

    @staticmethod
    def _event_scope(user_id: int | None = None, mac: str | None = None) -> tuple[str, list]:
        sql, args = "", []
        if user_id is not None:
            sql += " AND EXISTS (SELECT 1 FROM strip_access a WHERE a.mac=events.mac AND a.user_id=?)"
            args.append(user_id)
        if mac:
            sql += " AND mac=?"
            args.append(mac)
        return sql, args

    def events(self, limit: int = 50, before_id: int | None = None, *, user_id: int | None = None,
               mac: str | None = None) -> list[dict]:
        scope, args = self._event_scope(user_id, mac)
        with self.lock:
            rows = self.conn.execute("SELECT id, ts, level, code, mac, outlet, text, params FROM events WHERE id < ?"
                                     + scope + " ORDER BY id DESC LIMIT ?", [before_id or 2**62, *args, limit]).fetchall()
        return [{"id": r[0], "ts": int(r[1]), "level": r[2], "code": r[3], "mac": r[4], "outlet": r[5], "text": r[6],
                 "params": json.loads(r[7] or "{}")} for r in rows]

    def last_event_id(self, user_id: int | None = None) -> int:
        scope, args = self._event_scope(user_id)
        with self.lock:
            return self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM events WHERE 1=1" + scope, args).fetchone()[0]

    def unread(self, read_through: int, user_id: int | None = None, mac: str | None = None) -> int:
        scope, args = self._event_scope(user_id, mac)
        with self.lock:
            return self.conn.execute("SELECT COUNT(*) FROM events WHERE id > ? AND level != 'info'" + scope,
                                     [read_through, *args]).fetchone()[0]

    def known_macs(self) -> set[str]:
        with self.lock:
            return {r[0] for r in self.conn.execute("SELECT mac FROM energy UNION SELECT mac FROM events WHERE mac IS NOT NULL")}
