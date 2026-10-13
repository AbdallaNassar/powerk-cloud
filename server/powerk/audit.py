"""Security events, separate from strip activity; never persist credentials."""
from __future__ import annotations

import json
import time

AUDIT_RETENTION_SECONDS = 180 * 86400


class AuditLog:
    def __init__(self, db, *, clock=time.time):
        self.db, self.clock = db, clock
        with db.lock, db.conn:
            db.conn.execute('CREATE TABLE IF NOT EXISTS audit_log ('
                            'id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, user_id INTEGER, ip TEXT NOT NULL, '
                            'action TEXT NOT NULL, target TEXT NOT NULL, detail_json TEXT NOT NULL)')
            db.conn.execute('CREATE INDEX IF NOT EXISTS audit_user_id ON audit_log(user_id,id)')
            db.conn.execute('CREATE INDEX IF NOT EXISTS audit_ts ON audit_log(ts)')

    def record_locked(self, action, user_id=None, ip='', target='', **detail):
        """Caller holds the shared Db lock and transaction."""
        self.db.conn.execute('INSERT INTO audit_log(ts,user_id,ip,action,target,detail_json) VALUES(?,?,?,?,?,?)',
                             (int(self.clock()), user_id, ip, action, str(target), json.dumps(detail)))

    def record(self, action, user_id=None, ip='', target='', **detail):
        with self.db.lock, self.db.conn:
            self.record_locked(action, user_id, ip, target, **detail)

    def list(self, user_id, limit=50, before_id=None):
        with self.db.lock:
            rows = self.db.conn.execute(
                'SELECT id,ts,user_id,ip,action,target,detail_json FROM audit_log '
                'WHERE user_id=? AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?',
                (user_id, before_id, before_id, limit)).fetchall()
        return [dict(zip(('id', 'ts', 'user_id', 'ip', 'action', 'target', 'detail'), (*r[:6], json.loads(r[6])))) for r in rows]

    def prune(self, now=None):
        with self.db.lock, self.db.conn:
            self.db.conn.execute('DELETE FROM audit_log WHERE ts<?',
                                 ((self.clock() if now is None else now) - AUDIT_RETENTION_SECONDS,))
