"""Background ntfy and Telegram notifications."""
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlparse

from .store import Store

NO_PUSH = {"rule_fired", "online"}


class Notifier:
    """Push to ntfy and/or Telegram from a background thread; failures are logged, never raised."""

    def __init__(self, store: Store):
        self.store = store

    def _jobs(self, title: str, text: str, settings: dict | None = None) -> list[tuple]:
        s = self.store.settings() if settings is None else settings
        jobs = []
        if s["ntfy_url"]:
            jobs.append(("ntfy", s["ntfy_url"], text.encode(), {"Title": title.encode("ascii", "replace").decode()}))
        if s["telegram_token"] and s["telegram_chat"]:
            jobs.append(("telegram", f"https://api.telegram.org/bot{s['telegram_token']}/sendMessage",
                         urlencode({"chat_id": s["telegram_chat"], "text": f"{title}\n{text}"}).encode(),
                         {"Content-Type": "application/x-www-form-urlencoded"}))
        return jobs

    def send(self, title: str, text: str, settings: dict | None = None) -> None:
        for job in self._jobs(title, text, settings):
            threading.Thread(target=self._post, args=job[1:], daemon=True).start()

    def test(self, settings: dict | None = None) -> tuple[list[str], list[dict]]:
        sent, failed = [], []
        for name, *job in self._jobs("powerk: test", "Test notification from powerk", settings):
            error = self._post(*job)
            if error:
                failed.append({"channel": name, "error": error})
            else:
                sent.append(name)
        return sent, failed

    @staticmethod
    def _post(url: str, body: bytes, headers: dict) -> str | None:
        """None on success, else a short error (the URL is never echoed: it can hold the bot token)."""
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if 200 <= resp.status < 300:
                    return None
                error = f"HTTP {resp.status}"
        except urllib.error.HTTPError as err:
            error = f"HTTP {err.code}"
        except Exception as err:
            error = type(err).__name__ + (f": {err.reason}" if hasattr(err, "reason") else "")
        print(f"[alert] push to {urlparse(url).hostname} failed: {error}")
        return error
