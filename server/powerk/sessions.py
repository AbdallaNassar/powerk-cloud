"""Opaque session credentials. All SQL shares Db's lock and connection."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from time import time as now

from .store import Db
from .audit import AuditLog

ACCESS_SECONDS = 15 * 60
REFRESH_SECONDS = 30 * 86400
REFRESH_REUSE_GRACE_SECONDS = 60


class AuthError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Identity:
    user: dict
    family_id: str


class Sessions:
    def __init__(self, db: Db):
        self.db = db
        self.audit = AuditLog(db)
        with db.lock, db.conn:
            # Serialize the additive schema check across connections as well.
            db.conn.execute("BEGIN IMMEDIATE")
            db.conn.execute("CREATE TABLE IF NOT EXISTS session_families ("
                            "id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), "
                            "created_at INTEGER NOT NULL, last_used_at INTEGER NOT NULL, "
                            "user_agent TEXT NOT NULL, ip TEXT NOT NULL, revoked_at INTEGER)")
            db.conn.execute("CREATE INDEX IF NOT EXISTS session_users ON session_families(user_id)")
            db.conn.execute("CREATE TABLE IF NOT EXISTS refresh_tokens ("
                            "token_hash TEXT PRIMARY KEY, family_id TEXT NOT NULL REFERENCES session_families(id), "
                            "created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, used_at INTEGER)")
            columns = {row[1] for row in db.conn.execute("PRAGMA table_info(refresh_tokens)")}
            if "child_hash" not in columns:
                db.conn.execute("ALTER TABLE refresh_tokens ADD COLUMN child_hash TEXT")
            db.conn.execute("CREATE INDEX IF NOT EXISTS refresh_families ON refresh_tokens(family_id)")
            db.conn.execute("CREATE TABLE IF NOT EXISTS access_tokens ("
                            "token_hash TEXT PRIMARY KEY, family_id TEXT NOT NULL REFERENCES session_families(id), "
                            "expires_at INTEGER NOT NULL)")
            db.conn.execute("CREATE INDEX IF NOT EXISTS access_families ON access_tokens(family_id)")
            # Minimal tombstones preserve replay detection after used token rows are pruned.
            db.conn.execute('CREATE TABLE IF NOT EXISTS refresh_replays ('
                            'token_hash TEXT PRIMARY KEY, family_id TEXT NOT NULL REFERENCES session_families(id))')
            db.conn.execute('CREATE INDEX IF NOT EXISTS replay_families ON refresh_replays(family_id)')

    def issue_locked(self, family_id: str, user: dict, ts: int) -> dict:
        """Caller owns the Db lock and transaction (including credential checks)."""
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.db.conn.execute("INSERT INTO access_tokens VALUES(?,?,?)",
                             (token_hash(access), family_id, ts + ACCESS_SECONDS))
        self.db.conn.execute("INSERT INTO refresh_tokens(token_hash,family_id,created_at,expires_at) VALUES(?,?,?,?)",
                             (token_hash(refresh), family_id, ts, ts + REFRESH_SECONDS))
        return {"user": user, "access_token": access, "refresh_token": refresh, "expires_in": ACCESS_SECONDS}

    def create_locked(self, user: dict, user_agent: str, ip: str) -> dict:
        family_id, ts = secrets.token_urlsafe(18), int(now())
        self.db.conn.execute("INSERT INTO session_families VALUES(?,?,?,?,?,?,NULL)",
                             (family_id, user["id"], ts, ts, user_agent[:512], ip[:128]))
        return self.issue_locked(family_id, user, ts)

    def resolve(self, token: str) -> Identity | None:
        if not token or len(token) > 256:
            return None
        ts = int(now())
        with self.db.lock, self.db.conn:
            row = self.db.conn.execute(
                "SELECT u.id, u.phone, u.created_at, f.id FROM access_tokens a "
                "JOIN session_families f ON f.id=a.family_id JOIN users u ON u.id=f.user_id "
                "WHERE a.token_hash=? AND a.expires_at>? AND f.revoked_at IS NULL",
                (token_hash(token), ts)).fetchone()
            if not row:
                return None
            self.db.conn.execute("UPDATE session_families SET last_used_at=? WHERE id=?", (ts, row[3]))
            return Identity({"id": row[0], "phone": row[1], "created_at": row[2]}, row[3])

    def refresh(self, token: str, ip: str = '') -> dict:
        if not isinstance(token, str) or not token or len(token) > 256:
            raise AuthError("invalid refresh token", 401)
        digest, pair = token_hash(token), None
        with self.db.lock, self.db.conn:
            # Lock before the read as well, so separate connections/processes cannot both rotate.
            self.db.conn.execute("BEGIN IMMEDIATE")
            ts = int(now())
            row = self.db.conn.execute(
                "SELECT r.family_id, r.expires_at, r.used_at, f.revoked_at, u.id, u.phone, u.created_at, r.child_hash "
                "FROM refresh_tokens r JOIN session_families f ON f.id=r.family_id "
                "JOIN users u ON u.id=f.user_id WHERE r.token_hash=?", (digest,)).fetchone()
            if row is None:
                row = self.db.conn.execute(
                    'SELECT r.family_id,0,1,f.revoked_at,u.id,u.phone,u.created_at,NULL FROM refresh_replays r '
                    'JOIN session_families f ON f.id=r.family_id JOIN users u ON u.id=f.user_id '
                    'WHERE r.token_hash=?', (digest,)).fetchone()
            if row and row[2] is not None:
                if row[3] is None and row[2] <= ts < row[2] + REFRESH_REUSE_GRACE_SECONDS:
                    child = self.db.conn.execute(
                        "UPDATE refresh_tokens SET used_at=? WHERE token_hash=? AND family_id=? AND used_at IS NULL",
                        (ts, row[7], row[0]))
                    if child.rowcount:
                        # Keep the original link: this used child blocks a second grace on the parent.
                        # The invalidated child has no child_hash, so cannot claim grace itself.
                        pair = self.issue_locked(row[0], {"id": row[4], "phone": row[5], "created_at": row[6]}, ts)
                        self.audit.record_locked('refresh_grace', row[4], ip, row[0])
                if pair is None:
                    # Commit the revocation BEFORE reporting the error; raising here would roll it back.
                    self.db.conn.execute("UPDATE session_families SET revoked_at=COALESCE(revoked_at,?) WHERE id=?",
                                         (ts, row[0]))
                    self.audit.record_locked('refresh_reuse', row[4], ip, row[0])
            elif row and row[1] > ts and row[3] is None:
                pair = self.issue_locked(row[0], {"id": row[4], "phone": row[5], "created_at": row[6]}, ts)
                self.db.conn.execute("UPDATE refresh_tokens SET used_at=?, child_hash=? WHERE token_hash=?",
                                     (ts, token_hash(pair["refresh_token"]), digest))
            if pair is not None:
                self.db.conn.execute("UPDATE session_families SET last_used_at=? WHERE id=?", (ts, row[0]))
        if pair is None:
            raise AuthError("invalid refresh token", 401)
        return pair

    def list(self, identity: Identity) -> list[dict]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT f.id, f.created_at, f.last_used_at, f.user_agent, f.ip FROM session_families f "
                "WHERE f.user_id=? AND f.revoked_at IS NULL AND EXISTS "
                "(SELECT 1 FROM refresh_tokens r WHERE r.family_id=f.id AND r.used_at IS NULL AND r.expires_at>?) "
                "ORDER BY f.created_at DESC, f.id", (identity.user["id"], int(now()))).fetchall()
        return [{"id": r[0], "created_at": r[1], "last_used_at": r[2], "user_agent": r[3], "ip": r[4],
                 "current": r[0] == identity.family_id} for r in rows]

    def revoke(self, identity: Identity, family_id: str, ip: str = '', *, action='session_revoked') -> None:
        with self.db.lock, self.db.conn:
            result = self.db.conn.execute(
                "UPDATE session_families SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
                (int(now()), family_id, identity.user["id"]))
            if not result.rowcount:
                raise AuthError("session not found", 404)
            self.audit.record_locked(action, identity.user['id'], ip, family_id)

    def prune(self, ts=None):
        ts = int(now()) if ts is None else ts
        with self.db.lock, self.db.conn:
            self.db.conn.execute('BEGIN IMMEDIATE')
            self.db.conn.execute('DELETE FROM access_tokens WHERE expires_at<=?', (ts,))
            # Preserve rotation time and child links throughout grace, even if the parent expires.
            grace_cutoff = ts - REFRESH_REUSE_GRACE_SECONDS
            self.db.conn.execute('INSERT OR IGNORE INTO refresh_replays SELECT token_hash,family_id '
                                 'FROM refresh_tokens WHERE used_at<=?', (grace_cutoff,))
            self.db.conn.execute('DELETE FROM refresh_tokens WHERE used_at<=? '
                                 'OR (used_at IS NULL AND expires_at<=?)', (grace_cutoff, ts))
            # Delete children before parents (also works with foreign_keys=ON).
            old = 'SELECT id FROM session_families WHERE revoked_at IS NOT NULL AND revoked_at<?'
            for table in ('access_tokens', 'refresh_tokens', 'refresh_replays'):
                self.db.conn.execute(f'DELETE FROM {table} WHERE family_id IN ({old})', (ts - 30 * 86400,))
            self.db.conn.execute(f'DELETE FROM session_families WHERE id IN ({old})', (ts - 30 * 86400,))
            # Expired families cannot ever rotate again; their replay markers are no longer needed.
            self.db.conn.execute('DELETE FROM refresh_replays WHERE family_id IN ('
                                 'SELECT f.id FROM session_families f WHERE NOT EXISTS '
                                 '(SELECT 1 FROM refresh_tokens r WHERE r.family_id=f.id) AND NOT EXISTS '
                                 '(SELECT 1 FROM access_tokens a WHERE a.family_id=f.id))')
