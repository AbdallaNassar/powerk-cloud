"""Additive ownership, claim and preference storage. Legacy JSON/tables stay readable."""
from __future__ import annotations

import json
import secrets
import time

from .accounts import normalize_phone
from .protocol import DEFAULT_SETTINGS, MAC_RE
from .sessions import AuthError, token_hash
from .store import Db, Store
from .audit import AuditLog

STRIP_KEYS = ("currency", "price_kwh", "budget", "temp_max_c", "power_max_w")
CHANNEL_KEYS = ("ntfy_url", "telegram_token", "telegram_chat")
EVENT_LEVELS = {
    "offline": "warn", "online": "info", "temp_high": "alert", "power_high": "alert",
    "budget": "warn", "rule_fired": "info", "rule_skipped": "warn", "rule_failed": "warn",
    "autooff": "info", "onoff": "info", "name_changed": "info", "rule_created": "info",
    "rule_updated": "info", "rule_deleted": "info",
}
CLAIM_ERROR = "no unclaimed online strip with this code"


class Sharing:
    def __init__(self, db: Db):
        self.db = db
        self.audit = AuditLog(db)
        with db.lock, db.conn:
            for sql in (
                "CREATE TABLE IF NOT EXISTS strips(mac TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, claimed_at INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS strip_access(mac TEXT NOT NULL, user_id INTEGER NOT NULL, "
                "role TEXT NOT NULL CHECK(role IN ('owner','control','viewer')), added_by INTEGER, added_at INTEGER NOT NULL, PRIMARY KEY(mac,user_id))",
                "CREATE UNIQUE INDEX IF NOT EXISTS strip_one_owner ON strip_access(mac) WHERE role='owner'",
                "CREATE INDEX IF NOT EXISTS strip_access_user ON strip_access(user_id,mac)",
                "CREATE TABLE IF NOT EXISTS strip_settings(mac TEXT PRIMARY KEY, settings TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS user_notifications(user_id INTEGER PRIMARY KEY, settings TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS alert_preferences(mac TEXT, user_id INTEGER, code TEXT, enabled INTEGER NOT NULL, PRIMARY KEY(mac,user_id,code))",
                "CREATE TABLE IF NOT EXISTS event_reads(user_id INTEGER PRIMARY KEY, through_id INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS strip_claims(id TEXT PRIMARY KEY, mac TEXT NOT NULL, user_id INTEGER NOT NULL, "
                "expires_at REAL NOT NULL, status TEXT NOT NULL)",
                "CREATE UNIQUE INDEX IF NOT EXISTS strip_pending_claim ON strip_claims(mac) WHERE status='pending'",
                "CREATE TABLE IF NOT EXISTS sharing_migrations(name TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, completed_at INTEGER NOT NULL)",
            ):
                db.conn.execute(sql)

    def role(self, mac: str, user_id: int) -> str | None:
        with self.db.lock:
            row = self.db.conn.execute("SELECT role FROM strip_access WHERE mac=? AND user_id=?", (mac, user_id)).fetchone()
        return row[0] if row else None

    def accessible(self, user_id: int) -> dict[str, str]:
        with self.db.lock:
            return dict(self.db.conn.execute("SELECT mac,role FROM strip_access WHERE user_id=?", (user_id,)).fetchall())

    def claimed(self) -> set[str]:
        with self.db.lock:
            return {r[0] for r in self.db.conn.execute("SELECT mac FROM strips")}

    def require(self, mac: str, user_id: int, roles: tuple[str, ...] = ("owner", "control", "viewer")) -> str:
        role = self.role(mac, user_id)
        if role is None:
            raise AuthError("unknown strip", 404)
        if role not in roles:
            raise AuthError("forbidden", 403)
        return role

    def _claim_locked(self, mac: str, user_id: int, now: float) -> None:
        self.db.conn.execute("INSERT INTO strips VALUES(?,?,?)", (mac, user_id, int(now)))
        self.db.conn.execute("INSERT INTO strip_access VALUES(?,?,'owner',?,?)", (mac, user_id, user_id, int(now)))
        self.db.conn.execute("INSERT INTO strip_settings VALUES(?,?) ON CONFLICT(mac) DO NOTHING",
                             (mac, json.dumps({k: DEFAULT_SETTINGS[k] for k in STRIP_KEYS})))

    def _expire_locked(self, now: float) -> None:
        rows = self.db.conn.execute("SELECT id,mac,user_id FROM strip_claims WHERE status='pending' AND expires_at<=?", (now,)).fetchall()
        for claim_id, mac, user_id in rows:
            self._claim_event_locked('claim_expired', claim_id, mac, user_id)
        self.db.conn.execute("UPDATE strip_claims SET status='expired' WHERE status='pending' AND expires_at<=?", (now,))

    def _claim_event_locked(self, action, claim_id, mac, user_id):
        row = self.db.conn.execute("SELECT ip FROM audit_log WHERE action='claim_started' AND target=? ORDER BY id DESC LIMIT 1",
                                   (claim_id,)).fetchone()
        self.audit.record_locked(action, user_id, row[0] if row else '', claim_id, mac=mac)

    def expire_claims(self):
        with self.db.lock, self.db.conn:
            self._expire_locked(time.time())

    def start_claim(self, user_id: int, mac: str, ip: str = '') -> dict:
        now = time.time()
        with self.db.lock, self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            self._expire_locked(now)
            if self.db.conn.execute("SELECT 1 FROM strips WHERE mac=?", (mac,)).fetchone():
                raise AuthError(CLAIM_ERROR, 404)
            if self.db.conn.execute("SELECT 1 FROM strip_claims WHERE mac=? AND status='pending'", (mac,)).fetchone():
                raise AuthError("claim already pending", 409)
            claim_id = secrets.token_urlsafe(24)
            self.db.conn.execute("INSERT INTO strip_claims VALUES(?,?,?,?,'pending')", (claim_id, mac, user_id, now + 60))
            self.audit.record_locked('claim_started', user_id, ip, claim_id, mac=mac)
        return {"claim_id": claim_id, "expires_in": 60}

    def button(self, mac: str) -> None:
        now = time.time()
        with self.db.lock, self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            self._expire_locked(now)
            row = self.db.conn.execute("SELECT id,user_id FROM strip_claims WHERE mac=? AND status='pending'", (mac,)).fetchone()
            if not row:
                return
            if self.db.conn.execute("SELECT 1 FROM strips WHERE mac=?", (mac,)).fetchone():
                self.db.conn.execute("UPDATE strip_claims SET status='expired' WHERE id=?", (row[0],))
                self._claim_event_locked('claim_expired', row[0], mac, row[1])
                return
            self._claim_locked(mac, row[1], now)
            self.db.conn.execute("UPDATE strip_claims SET status='done' WHERE id=?", (row[0],))
            self._claim_event_locked('claim_completed', row[0], mac, row[1])

    def claim_status(self, user_id: int, claim_id: str) -> dict:
        with self.db.lock, self.db.conn:
            self._expire_locked(time.time())
            row = self.db.conn.execute("SELECT status,mac FROM strip_claims WHERE id=? AND user_id=?", (claim_id, user_id)).fetchone()
        if not row:
            raise AuthError("unknown claim", 404)
        return {"status": row[0], **({"mac": row[1]} if row[0] == "done" else {})}

    def settings(self, mac: str, fallback: dict | None = None) -> dict:
        with self.db.lock:
            row = self.db.conn.execute("SELECT settings FROM strip_settings WHERE mac=?", (mac,)).fetchone()
        return {**{k: (fallback or DEFAULT_SETTINGS)[k] for k in STRIP_KEYS}, **(json.loads(row[0]) if row else {})}

    def update_settings(self, mac: str, changes: dict, actor: int | None = None, ip: str = '') -> dict:
        with self.db.lock, self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            row = self.db.conn.execute("SELECT settings FROM strip_settings WHERE mac=?", (mac,)).fetchone()
            settings = {**{k: DEFAULT_SETTINGS[k] for k in STRIP_KEYS}, **(json.loads(row[0]) if row else {}), **changes}
            self.db.conn.execute("INSERT INTO strip_settings VALUES(?,?) ON CONFLICT(mac) DO UPDATE SET settings=excluded.settings",
                                 (mac, json.dumps(settings)))
            self.audit.record_locked('strip_settings_change', actor, ip, mac, changes=changes)
        return settings

    def access(self, mac: str) -> list[dict]:
        with self.db.lock:
            rows = self.db.conn.execute("SELECT u.id,u.phone,a.role,a.added_at FROM strip_access a JOIN users u ON u.id=a.user_id "
                                        "WHERE a.mac=? ORDER BY a.added_at,u.id", (mac,)).fetchall()
        return [dict(zip(("user_id", "phone", "role", "added_at"), r)) for r in rows]

    @staticmethod
    def clean_role(role) -> str:
        if role not in ("control", "viewer"):
            raise AuthError("role must be control or viewer")
        return role

    def share(self, mac: str, phone, role, added_by: int | None, ip: str = '') -> None:
        phone, role = normalize_phone(phone), self.clean_role(role)
        with self.db.lock, self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            strip = self.db.conn.execute("SELECT owner_id FROM strips WHERE mac=?", (mac,)).fetchone()
            if not strip:
                raise AuthError("unknown strip", 404)
            user = self.db.conn.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone()
            # Self/owner sharing is a no-op too: it cannot demote the owner or enumerate phones.
            if user and user[0] != strip[0]:
                self.db.conn.execute("INSERT INTO strip_access VALUES(?,?,?,?,?) ON CONFLICT(mac,user_id) "
                                     "DO UPDATE SET role=excluded.role", (mac, user[0], role, added_by, int(time.time())))
            # Same audit shape for no-op/unknown phones: the log must not become an oracle.
            self.audit.record_locked('share', added_by, ip, mac, phone_hash=token_hash(phone), role=role)

    def change_access(self, mac: str, user_id: int, actor: int | None, role: str | None = None, ip: str = '') -> None:
        if role is not None:
            self.clean_role(role)
        with self.db.lock, self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            row = self.db.conn.execute("SELECT role FROM strip_access WHERE mac=? AND user_id=?", (mac, user_id)).fetchone()
            if not row:
                raise AuthError("unknown strip", 404)
            if user_id == actor or row[0] == "owner":
                raise AuthError("forbidden", 403)
            if role is None:
                self._remove_locked(mac, user_id)
            else:
                self.db.conn.execute("UPDATE strip_access SET role=? WHERE mac=? AND user_id=?", (role, mac, user_id))
            self.audit.record_locked('role_change' if role is not None else 'remove_access', actor, ip, mac,
                                      member_id=user_id, role=role)

    def _remove_locked(self, mac: str, user_id: int) -> None:
        self.db.conn.execute("DELETE FROM strip_access WHERE mac=? AND user_id=?", (mac, user_id))
        self.db.conn.execute("DELETE FROM alert_preferences WHERE mac=? AND user_id=?", (mac, user_id))

    def leave(self, mac: str, user_id: int, ip: str = '') -> None:
        with self.db.lock, self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            row = self.db.conn.execute("SELECT role FROM strip_access WHERE mac=? AND user_id=?", (mac, user_id)).fetchone()
            if not row:
                raise AuthError("unknown strip", 404)
            if row[0] == "owner":
                raise AuthError("forbidden", 403)
            self._remove_locked(mac, user_id)
            self.audit.record_locked('leave', user_id, ip, mac)

    def transfer(self, mac: str, phone, actor: int | None = None, ip: str = '') -> None:
        phone = normalize_phone(phone)
        with self.db.lock, self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            target = self.db.conn.execute("SELECT a.user_id,a.role FROM strip_access a JOIN users u ON u.id=a.user_id "
                                          "WHERE a.mac=? AND u.phone=?", (mac, phone)).fetchone()
            if not target:
                raise AuthError("unknown strip", 404)
            if target[1] == "owner":
                raise AuthError("forbidden", 403)
            self.db.conn.execute("UPDATE strip_access SET role='control' WHERE mac=? AND role='owner'", (mac,))
            self.db.conn.execute("UPDATE strip_access SET role='owner' WHERE mac=? AND user_id=?", (mac, target[0]))
            self.db.conn.execute("UPDATE strips SET owner_id=? WHERE mac=?", (target[0], mac))
            self.audit.record_locked('transfer', actor, ip, mac, member_id=target[0])

    def unclaim(self, mac: str, actor: int | None = None, ip: str = '') -> None:
        with self.db.lock, self.db.conn:
            for claim_id, uid in self.db.conn.execute("SELECT id,user_id FROM strip_claims WHERE mac=? AND status='pending'", (mac,)).fetchall():
                self._claim_event_locked('claim_expired', claim_id, mac, uid)
            self.db.conn.execute("DELETE FROM strip_access WHERE mac=?", (mac,))
            self.db.conn.execute("DELETE FROM alert_preferences WHERE mac=?", (mac,))
            self.db.conn.execute("DELETE FROM strips WHERE mac=?", (mac,))
            self.db.conn.execute("DELETE FROM strip_settings WHERE mac=?", (mac,))
            self.db.conn.execute("UPDATE strip_claims SET status='expired' WHERE mac=?", (mac,))
            self.audit.record_locked('unclaim', actor, ip, mac)

    def channels(self, user_id: int) -> dict:
        with self.db.lock:
            row = self.db.conn.execute("SELECT settings FROM user_notifications WHERE user_id=?", (user_id,)).fetchone()
        return {**{k: DEFAULT_SETTINGS[k] for k in CHANNEL_KEYS}, **(json.loads(row[0]) if row else {})}

    def notifications(self, user_id: int) -> dict:
        settings = self.channels(user_id)
        settings["telegram_configured"] = bool(settings.pop("telegram_token"))
        prefs = {mac: {k: level != "info" for k, level in EVENT_LEVELS.items()} for mac in self.accessible(user_id)}
        with self.db.lock:
            rows = self.db.conn.execute("SELECT mac,code,enabled FROM alert_preferences WHERE user_id=?", (user_id,)).fetchall()
        for mac, code, enabled in rows:
            if mac in prefs:
                prefs[mac][code] = bool(enabled)
        return dict(settings, alerts=prefs)

    def update_notifications(self, user_id: int, changes: dict, alerts: dict) -> None:
        if not isinstance(alerts, dict):
            raise AuthError("alerts must be an object keyed by strip MAC")
        prefs = []
        for mac, codes in alerts.items():
            mac = mac.upper()
            if not isinstance(codes, dict):
                raise AuthError("alert preferences must be objects")
            for code, enabled in codes.items():
                if code not in EVENT_LEVELS or type(enabled) is not bool:
                    raise AuthError("alert preferences need known event codes and true/false values")
                prefs.append((mac, user_id, code, int(enabled)))
        with self.db.lock, self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            # Check even empty preference objects; all changes succeed or none do.
            for mac in alerts:
                if not self.db.conn.execute("SELECT 1 FROM strip_access WHERE mac=? AND user_id=?", (mac.upper(), user_id)).fetchone():
                    raise AuthError("unknown strip", 404)
            row = self.db.conn.execute("SELECT settings FROM user_notifications WHERE user_id=?", (user_id,)).fetchone()
            settings = {**(json.loads(row[0]) if row else {}), **changes}
            self.db.conn.execute("INSERT INTO user_notifications VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET settings=excluded.settings",
                                 (user_id, json.dumps(settings)))
            self.db.conn.executemany("INSERT INTO alert_preferences VALUES(?,?,?,?) ON CONFLICT(mac,user_id,code) DO UPDATE SET enabled=excluded.enabled", prefs)

    def recipients(self, mac: str, code: str, level: str, *, include_users=False) -> list:
        with self.db.lock:
            rows = self.db.conn.execute("SELECT a.user_id,n.settings FROM strip_access a LEFT JOIN user_notifications n ON n.user_id=a.user_id "
                                        "LEFT JOIN alert_preferences p ON p.user_id=a.user_id AND p.mac=a.mac AND p.code=? "
                                        "WHERE a.mac=? AND COALESCE(p.enabled,?)=1", (code, mac, int(level != "info"))).fetchall()
        recipients = [(uid, {**{k: DEFAULT_SETTINGS[k] for k in CHANNEL_KEYS}, **json.loads(settings or '{}')})
                      for uid, settings in rows if include_users or settings is not None]
        return recipients if include_users else [settings for _, settings in recipients]

    def read_pointer(self, user_id: int) -> int:
        with self.db.lock:
            row = self.db.conn.execute("SELECT through_id FROM event_reads WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else 0

    def mark_read(self, user_id: int, through: int) -> int:
        with self.db.lock, self.db.conn:
            self.db.conn.execute("INSERT INTO event_reads VALUES(?,?) ON CONFLICT(user_id) DO UPDATE "
                                 "SET through_id=MAX(through_id,excluded.through_id)", (user_id, through))
            return self.db.conn.execute("SELECT through_id FROM event_reads WHERE user_id=?", (user_id,)).fetchone()[0]

    def migrate(self, store: Store, phone) -> dict:
        result = self._migrate_accounts(store, phone)
        # Persist only after the database commit. Reruns repair a missing JSON marker
        # (including migrations from older versions) without copying settings again.
        if store.meta("accounts_migrated") is None:
            with self.db.lock:
                completed_at = self.db.conn.execute(
                    "SELECT completed_at FROM sharing_migrations WHERE name='ownership-v1'").fetchone()[0]
            store.set_meta("accounts_migrated", completed_at)
        return result

    def _migrate_accounts(self, store: Store, phone) -> dict:
        phone = normalize_phone(phone)
        known = set(store.meta("devices", {})) | self.db.known_macs()
        settings = store.settings()
        with self.db.lock, self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            user = self.db.conn.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone()
            if not user:
                raise AuthError("owner phone must belong to an existing account")
            if self.db.conn.execute("SELECT 1 FROM sharing_migrations WHERE name='ownership-v1'").fetchone():
                return {"migrated": 0, "already_migrated": True}
            count = 0
            for mac in sorted(known):
                if not MAC_RE.fullmatch(mac):
                    continue
                if self.db.conn.execute("SELECT 1 FROM strips WHERE mac=?", (mac,)).fetchone():
                    self.db.conn.execute("UPDATE strip_access SET role='control' WHERE mac=? AND role='owner'", (mac,))
                    self.db.conn.execute("INSERT INTO strip_access VALUES(?,?,'owner',?,?) ON CONFLICT(mac,user_id) "
                                         "DO UPDATE SET role='owner'", (mac, user[0], user[0], int(time.time())))
                    self.db.conn.execute("UPDATE strips SET owner_id=? WHERE mac=?", (user[0], mac))
                else:
                    self._claim_locked(mac, user[0], time.time())
                self.db.conn.execute("INSERT INTO strip_settings VALUES(?,?) ON CONFLICT(mac) DO UPDATE SET settings=excluded.settings",
                                     (mac, json.dumps({k: settings[k] for k in STRIP_KEYS})))
                self.db.conn.execute("UPDATE strip_claims SET status='expired' WHERE mac=? AND status='pending'", (mac,))
                count += 1
            self.db.conn.execute("INSERT INTO user_notifications VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET settings=excluded.settings",
                                 (user[0], json.dumps({k: settings[k] for k in CHANNEL_KEYS})))
            self.db.conn.execute("INSERT INTO sharing_migrations VALUES('ownership-v1',?,?)", (user[0], int(time.time())))
        return {"migrated": count, "already_migrated": False}
