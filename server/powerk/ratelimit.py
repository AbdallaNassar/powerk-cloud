"""Bounded, process-local sliding windows; monotonic clock is injectable."""
from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

LIMITS = {
    'login': (20, 600), 'register': (3, 3600), 'refresh': (60, 600),
    'claim': (5, 3600), 'access': (20, 3600), 'api': (120, 60),
    'ws': (30, 60), 'push_tokens': (20, 3600),
}
PHONE_FAILURES = 5
PHONE_BASE_SECONDS = 60
PHONE_MAX_SECONDS = 900
PHONE_IDLE_SECONDS = 86400
MAX_KEYS = 10000
AUDIT_SAMPLE_SECONDS = 60


class RateLimited(Exception):
    def __init__(self, key: tuple, retry_after: float):
        self.key = key
        self.retry_after = max(1, math.ceil(retry_after))
        super().__init__('too many requests')


@dataclass
class Entry:
    idle_until: float
    hits: deque = field(default_factory=deque)
    failures: int = 0
    blocked_until: float = 0
    logged_at: float = float('-inf')


class RateLimiter:
    def __init__(self, *, clock=time.monotonic, limits=None, max_keys=MAX_KEYS):
        self.clock, self.limits, self.max_keys = clock, dict(LIMITS if limits is None else limits), max_keys
        self.entries: OrderedDict[tuple, Entry] = OrderedDict()
        self.lock = threading.RLock()
        # Fixed stripes serialize password checks, including concurrent wrong guesses.
        self.phone_locks = [threading.Lock() for _ in range(64)]
        self.serial = 0
        self.next_sweep = 0
        self.overflow_logged = float('-inf')

    def phone_lock(self, key):
        return self.phone_locks[hash(key) % len(self.phone_locks)]

    def _entry(self, key, ttl, now):
        if now >= self.next_sweep or len(self.entries) >= self.max_keys:
            for old in [k for k, v in self.entries.items() if v.idle_until <= now]:
                del self.entries[old]
            self.next_sweep = now + 60
        entry = self.entries.get(key)
        if entry is None:
            if len(self.entries) >= self.max_keys:
                # Never evict a live penalty: key churn must not bypass limits.
                raise RateLimited(('capacity', ''), 60)
            entry = self.entries[key] = Entry(now + ttl)
        entry.idle_until = now + max(ttl, AUDIT_SAMPLE_SECONDS)
        return entry

    def take(self, name, identity):
        key = (name, str(identity))
        with self.lock:
            now = self.clock()
            count, seconds = self.limits[name]
            entry = self._entry(key, seconds, now)
            while entry.hits and entry.hits[0][0] <= now - seconds:
                entry.hits.popleft()
            if len(entry.hits) >= count:
                raise RateLimited(key, entry.hits[0][0] + seconds - now)
            self.serial += 1
            ticket = (now, self.serial)
            entry.hits.append(ticket)
            return key, ticket

    def refund(self, reservation):
        key, ticket = reservation
        with self.lock:
            entry = self.entries.get(key)
            if entry and ticket in entry.hits:
                entry.hits.remove(ticket)

    def check_phone(self, phone_hash):
        with self.lock:
            now = self.clock()
            key = ('phone', phone_hash)
            entry = self._entry(key, PHONE_IDLE_SECONDS, now)
            if entry.blocked_until > now:
                raise RateLimited(key, entry.blocked_until - now)

    def fail_phone(self, phone_hash):
        with self.lock:
            now = self.clock()
            entry = self._entry(('phone', phone_hash), PHONE_IDLE_SECONDS, now)
            max_exponent = math.ceil(math.log2(max(1, PHONE_MAX_SECONDS / PHONE_BASE_SECONDS)))
            entry.failures = min(entry.failures + 1, PHONE_FAILURES + max_exponent)
            if entry.failures >= PHONE_FAILURES:
                delay = min(PHONE_MAX_SECONDS, PHONE_BASE_SECONDS * 2 ** (entry.failures - PHONE_FAILURES))
                entry.blocked_until = now + delay

    def reset_phone(self, phone_hash):
        with self.lock:
            self.entries.pop(('phone', phone_hash), None)

    def sample(self, key):
        with self.lock:
            now = self.clock()
            entry = self.entries.get(key)
            last = entry.logged_at if entry else self.overflow_logged
            if now - last < AUDIT_SAMPLE_SECONDS:
                return False
            if entry:
                entry.logged_at = now
            else:
                self.overflow_logged = now
            return True
