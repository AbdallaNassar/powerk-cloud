"""Phone usernames and Argon2id passwords, independent of HTTP and strip access."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from time import time

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError

from .sessions import AuthError, Identity, Sessions, token_hash
from .store import Db

# Same parameters as the real hasher. Never regenerated per unknown login.
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$1bMm8//ePce8VQSX6z8pcg$KfLTymHQCTgKDNVvi8a1QVaa9c5TYjrolMncvGkgdzg"
COMMON_PASSWORDS = frozenset(Path(__file__).with_name("common_passwords.txt").read_text("utf-8").splitlines())


def normalize_phone(value) -> str:
    if not isinstance(value, str):
        raise AuthError("invalid phone number")
    value = re.sub(r"[ ()-]", "", value)
    if re.fullmatch(r"01[0-9]{9}", value):
        return "+20" + value[1:]
    if re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
        return value
    raise AuthError("invalid phone number")


def password_input(value) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise AuthError("password must be 1-128 characters")
    return value


def check_password(value, phone: str) -> str:
    if not isinstance(value, str) or not 10 <= len(value) <= 128:
        raise AuthError("password must be 10-128 characters")
    phone_forms = {phone, phone[1:]}
    if phone.startswith("+201") and len(phone) == 13:
        phone_forms.add("0" + phone[3:])
    if value in phone_forms or value.casefold() in COMMON_PASSWORDS:
        raise AuthError("password is too common or matches phone")
    return value


class Accounts:
    def __init__(self, db: Db):
        self.db = db
        self.hasher = PasswordHasher(type=Type.ID)
        with db.lock, db.conn:
            db.conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, phone TEXT NOT NULL UNIQUE, "
                            "password_hash TEXT NOT NULL, created_at INTEGER NOT NULL)")
        self.sessions = Sessions(db)
        self.audit = self.sessions.audit

    def register(self, phone, password, user_agent: str, ip: str) -> dict:
        phone = normalize_phone(phone)
        encoded = self.hasher.hash(check_password(password, phone))
        ts = int(time())
        with self.db.lock, self.db.conn:
            try:
                result = self.db.conn.execute("INSERT INTO users(phone,password_hash,created_at) VALUES(?,?,?)",
                                               (phone, encoded, ts))
            except sqlite3.IntegrityError:
                raise AuthError("phone already registered", 409) from None
            pair = self.sessions.create_locked({"id": result.lastrowid, "phone": phone, "created_at": ts}, user_agent, ip)
            self.audit.record_locked('register', result.lastrowid, ip)
            return pair

    def _verify(self, encoded: str, password: str) -> bool:
        try:
            return self.hasher.verify(encoded, password)
        except VerificationError:
            return False

    def login(self, phone, password, user_agent: str, ip: str) -> dict:
        phone, password = normalize_phone(phone), password_input(password)
        with self.db.lock:
            row = self.db.conn.execute("SELECT id,phone,created_at,password_hash FROM users WHERE phone=?", (phone,)).fetchone()
        valid = self._verify(row[3] if row else DUMMY_HASH, password)
        if not row or not valid:
            self.audit.record('login_failure', row[0] if row else None, ip, phone_hash=token_hash(phone))
            raise AuthError("wrong phone or password", 401)
        encoded = self.hasher.hash(password) if self.hasher.check_needs_rehash(row[3]) else row[3]
        with self.db.lock, self.db.conn:
            # Serialize with password changes, after the expensive work outside the lock.
            result = self.db.conn.execute("UPDATE users SET password_hash=? WHERE id=? AND password_hash=?",
                                          (encoded, row[0], row[3]))
            if not result.rowcount:
                self.audit.record_locked('login_failure', row[0], ip, phone_hash=token_hash(phone))
            else:
                pair = self.sessions.create_locked({"id": row[0], "phone": row[1], "created_at": row[2]}, user_agent, ip)
                self.audit.record_locked('login_success', row[0], ip)
                return pair
        # Report only after committing the failure event (e.g. a password-change race).
        raise AuthError("wrong phone or password", 401)

    def change_password(self, identity: Identity, current_password, new_password, ip: str = '') -> None:
        current_password = password_input(current_password)
        new_password = check_password(new_password, identity.user["phone"])
        with self.db.lock:
            row = self.db.conn.execute("SELECT password_hash FROM users WHERE id=?", (identity.user["id"],)).fetchone()
        if not row or not self._verify(row[0], current_password):
            raise AuthError("wrong phone or password", 401)
        encoded = self.hasher.hash(new_password)
        with self.db.lock, self.db.conn:
            result = self.db.conn.execute(
                "UPDATE users SET password_hash=? WHERE id=? AND password_hash=? AND EXISTS "
                "(SELECT 1 FROM session_families WHERE id=? AND revoked_at IS NULL)",
                (encoded, identity.user["id"], row[0], identity.family_id))
            if not result.rowcount:
                raise AuthError("session required", 401)
            self.db.conn.execute("UPDATE session_families SET revoked_at=? WHERE user_id=? AND id<>? AND revoked_at IS NULL",
                                 (int(time()), identity.user["id"], identity.family_id))
            self.audit.record_locked('password_change', identity.user['id'], ip, identity.family_id)
