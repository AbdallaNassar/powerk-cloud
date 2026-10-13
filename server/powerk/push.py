"""Device registrations tied to account session families."""
from __future__ import annotations

import re
import time

from .audit import AuditLog
from .sessions import AuthError, token_hash


class PushTokens:
    def __init__(self, db):
        self.db, self.audit = db, AuditLog(db)
        with db.lock, db.conn:
            db.conn.execute('CREATE TABLE IF NOT EXISTS push_tokens ('
                            'token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), '
                            'platform TEXT NOT NULL, app_version TEXT NOT NULL, created_at INTEGER NOT NULL, '
                            'last_seen_at INTEGER NOT NULL, session_family_id TEXT NOT NULL '
                            'REFERENCES session_families(id) ON DELETE CASCADE)')
            db.conn.execute('CREATE INDEX IF NOT EXISTS push_users ON push_tokens(user_id)')
            db.conn.execute('CREATE INDEX IF NOT EXISTS push_families ON push_tokens(session_family_id)')

    def _audit(self, action, token, user_id, ip='', **detail):
        self.audit.record_locked(action, user_id, ip, token_hash(token)[:16], **detail)

    def register(self, identity, body, ip=''):
        token, platform, version = body.get('token'), body.get('platform'), body.get('app_version', '')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_:.-]{1,4096}', token):
            raise AuthError('invalid push token')
        if platform != 'android' or not isinstance(version, str) or len(version) > 64:
            raise AuthError('platform must be android and app_version at most 64 characters')
        uid, family, ts = identity.user['id'], identity.family_id, int(time.time())
        with self.db.lock, self.db.conn:
            self.db.conn.execute('BEGIN IMMEDIATE')
            if not self.db.conn.execute('SELECT 1 FROM session_families WHERE id=? AND user_id=? AND revoked_at IS NULL',
                                        (family, uid)).fetchone():
                raise AuthError('session required', 401)
            # A device switching accounts must no longer receive the previous account's pushes.
            self.db.conn.execute('INSERT INTO push_tokens VALUES(?,?,?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET '
                                 'created_at=CASE WHEN push_tokens.user_id=excluded.user_id THEN push_tokens.created_at ELSE excluded.created_at END, '
                                 'user_id=excluded.user_id, platform=excluded.platform, app_version=excluded.app_version, '
                                 'last_seen_at=excluded.last_seen_at, session_family_id=excluded.session_family_id',
                                 (token, uid, platform, version, ts, ts, family))
            self._audit('push_token_register', token, uid, ip)
            old = self.db.conn.execute('SELECT token FROM push_tokens WHERE user_id=? '
                                       'ORDER BY created_at DESC,rowid DESC LIMIT -1 OFFSET 10', (uid,)).fetchall()
            for (value,) in old:
                self.db.conn.execute('DELETE FROM push_tokens WHERE token=?', (value,))
                self._audit('push_token_delete', value, uid, ip, reason='evicted')

    def delete(self, token, user_id, ip=''):
        with self.db.lock, self.db.conn:
            result = self.db.conn.execute('DELETE FROM push_tokens WHERE token=? AND user_id=?', (token, user_id))
            if not result.rowcount:
                raise AuthError('push token not found', 404)
            self._audit('push_token_delete', token, user_id, ip, reason='removed')

    def purge_revoked(self):
        with self.db.lock, self.db.conn:
            rows = self.db.conn.execute('SELECT token,user_id FROM push_tokens WHERE NOT EXISTS '
                '(SELECT 1 FROM session_families f WHERE f.id=push_tokens.session_family_id AND f.revoked_at IS NULL)').fetchall()
            for token, uid in rows:
                self.db.conn.execute('DELETE FROM push_tokens WHERE token=?', (token,))
                self._audit('push_token_delete', token, uid, reason='session_revoked')

    def for_user(self, user_id):
        with self.db.lock:
            return self.db.conn.execute('SELECT p.token,p.session_family_id FROM push_tokens p '
                'JOIN session_families f ON f.id=p.session_family_id WHERE p.user_id=? AND f.revoked_at IS NULL',
                (user_id,)).fetchall()

    def active(self, token, family_id, event=None):
        with self.db.lock:
            row = self.db.conn.execute('SELECT p.user_id FROM push_tokens p JOIN session_families f '
                'ON f.id=p.session_family_id WHERE p.token=? AND f.id=? AND f.revoked_at IS NULL', (token, family_id)).fetchone()
            if not row:
                return False
            if event and event.get('mac'):
                return bool(self.db.conn.execute('SELECT 1 FROM strip_access a LEFT JOIN alert_preferences p '
                    'ON p.user_id=a.user_id AND p.mac=a.mac AND p.code=? '
                    'WHERE a.user_id=? AND a.mac=? AND COALESCE(p.enabled,?)=1',
                    (event['code'], row[0], event['mac'], int(event.get('level') != 'info'))).fetchone())
            return True

    def delete_invalid(self, token, family_id):
        with self.db.lock, self.db.conn:
            row = self.db.conn.execute('SELECT user_id FROM push_tokens WHERE token=? AND session_family_id=?',
                                       (token, family_id)).fetchone()
            if row:
                self.db.conn.execute('DELETE FROM push_tokens WHERE token=? AND session_family_id=?', (token, family_id))
                self._audit('push_token_delete', token, row[0], reason='invalid')
