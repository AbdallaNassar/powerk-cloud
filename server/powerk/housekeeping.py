"""Hourly credential cleanup and daily audit retention, off the TCP event loop."""
import asyncio
import logging
import time

TOKEN_CLEANUP_SECONDS = 3600
AUDIT_CLEANUP_SECONDS = 86400


class Housekeeping:
    def __init__(self, sessions, sharing, *, clock=time.time):
        self.sessions, self.sharing, self.clock = sessions, sharing, clock
        self.next_tokens = self.next_audit = 0

    def run_due(self):
        now = self.clock()
        self.sharing.expire_claims()
        if now >= self.next_tokens:
            self.sessions.prune(now)
            self.next_tokens = now + TOKEN_CLEANUP_SECONDS
        if now >= self.next_audit:
            self.sessions.audit.prune(now)
            self.next_audit = now + AUDIT_CLEANUP_SECONDS

    async def loop(self):
        while True:
            worker = asyncio.create_task(asyncio.to_thread(self.run_due))
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Do not close SQLite while its worker still owns a transaction.
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                worker.result()
                raise
            except Exception:
                logging.exception('powerk housekeeping failed; retrying in one minute')
            await asyncio.sleep(60)
