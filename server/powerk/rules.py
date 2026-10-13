"""Rule validation/runtime and public settings, preserving legacy semantics."""
from __future__ import annotations

import asyncio
import math
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from .devices import Device, Hub
from .protocol import BUDGET_STEPS, DEFAULT_SETTINGS, HHMM_RE, MAC_RE, NAME_MAX, OFFLINE_ALERT_AFTER

RULE_KINDS = ("schedule", "timer", "cycle", "autooff")
RULE_FIELDS = {
    "schedule": ("at", "days", "on"),
    "timer": ("fire_at", "on"),
    "cycle": ("on_min", "off_min"),
    "autooff": ("below_w", "for_min"),
}


def _int_in(value, lo: int, hi: int, field: str) -> int:
    if type(value) is not int or not lo <= value <= hi:          # bool and 1.0 are rejected on purpose
        raise ValueError(f"{field} must be a whole number {lo}-{hi}")
    return value


def _is_outlet(value, lo: int = 1) -> bool:
    return type(value) is int and lo <= value <= 4


def clean_rule(body: dict, now: float, base: dict | None = None) -> dict:
    """Validate a create (base None) or partial update (base = stored rule). Returns the stored form."""
    if not isinstance(body, dict):
        raise ValueError("rule must be an object")
    r = dict(base or {})
    r.update({k: v for k, v in body.items() if k not in ("id", "next_at", "phase", "fire_at")})   # fire_at only from minutes
    kind = r.get("kind")
    if kind not in RULE_KINDS or (base and kind != base["kind"]):
        raise ValueError("kind must be schedule, timer, cycle or autooff (and cannot change)")
    mac = str(r.get("mac", "")).upper()
    if not MAC_RE.match(mac):
        raise ValueError("mac must be 12 hex digits")
    outlets = r.get("outlets")
    if not isinstance(outlets, list) or not outlets or not all(_is_outlet(n, 0) for n in outlets):
        raise ValueError("outlets must be a non-empty list of 1-4 (0 = all)")
    outlets = [1, 2, 3, 4] if 0 in outlets else sorted(set(outlets))
    enabled = r.get("enabled", True)
    label = r.get("label", "")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true/false")
    if not isinstance(label, str) or len(label) > NAME_MAX:
        raise ValueError(f"label must be text up to {NAME_MAX} characters")
    out = {"id": r.get("id") or "r_" + secrets.token_hex(3), "kind": kind, "mac": mac, "outlets": outlets,
           "enabled": enabled, "label": label.strip()}

    if kind in ("schedule", "timer"):
        if not isinstance(r.get("on"), bool):
            raise ValueError("on must be true/false")
        out["on"] = r["on"]
    if kind == "schedule":
        if not isinstance(r.get("at"), str) or not HHMM_RE.match(r["at"]):
            raise ValueError("at must be HH:MM (24 h)")
        days = r.get("days")
        if not isinstance(days, list) or not days or any(isinstance(x, bool) or x not in range(7) for x in days):
            raise ValueError("days must be a non-empty list of 0-6 (0 = Monday)")
        out["at"], out["days"] = r["at"], sorted(set(days))
    elif kind == "timer":
        if "minutes" in body:
            out["fire_at"] = round(now + _int_in(body["minutes"], 1, 10080, "minutes") * 60)
        elif base and "fire_at" in base:
            out["fire_at"] = base["fire_at"]
        else:
            raise ValueError("timer needs minutes (1-10080)")
    elif kind == "cycle":
        out["on_min"] = _int_in(r.get("on_min"), 1, 1440, "on_min")
        out["off_min"] = _int_in(r.get("off_min"), 1, 1440, "off_min")
    else:
        w = r.get("below_w")
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or not 0 < w <= 3500:
            raise ValueError("below_w must be 0-3500")
        out["below_w"] = float(w)
        out["for_min"] = _int_in(r.get("for_min"), 1, 1440, "for_min")
    return out


def next_schedule(rule: dict, now: float) -> int | None:
    h, m = map(int, rule["at"].split(":"))
    base = datetime.fromtimestamp(now)
    for add in range(8):
        cand = (base + timedelta(days=add)).replace(hour=h, minute=m, second=0, microsecond=0)
        ts = cand.timestamp()
        back = datetime.fromtimestamp(ts)
        if (back.hour, back.minute) != (h, m):             # skipped by a DST jump: the engine never sees it
            continue
        if cand.weekday() in rule["days"] and ts > now:
            return int(ts)
    return None


class Engine:
    """Runs rules, offline alerts and budget alerts once a second in the asyncio loop."""

    def __init__(self, hub: Hub):
        self.hub = hub
        self.store = hub.store
        self.rt: dict[str, dict] = {}          # per-rule runtime: last_key, phase, next_at, below_since
        self.inflight: set[str] = set()        # rules whose action is still running
        self.action_tasks: set[asyncio.Task] = set()
        self.last_budget_check = 0.0
        hub.observers.append(self.observe)

    def observe(self, d: Device, now: float) -> None:
        """Every reading resets an auto-off countdown that it disproves (outlet off, or at/above the limit)."""
        for rule in self.store.rules():
            if rule["kind"] != "autooff" or not rule["enabled"] or rule["mac"] != d.mac:
                continue
            since = self.rt.setdefault(rule["id"], {}).setdefault("below_since", {})
            for n in rule["outlets"]:
                o = d.outlets[n]
                if not o["on"] or o["power_w"] >= rule["below_w"]:
                    since.pop(n, None)
                else:
                    since.setdefault(n, now)

    def _current(self, rule: dict) -> bool:
        """The rule was not edited, disabled or deleted while its action waited."""
        return self.store.rule(rule["id"]) == rule

    def reset(self, rule_id: str) -> None:
        self.rt.pop(rule_id, None)

    def view(self, rule: dict, now: float | None = None) -> dict:
        """Rule plus read-only runtime fields for the API."""
        now = now or time.time()
        rt = self.rt.get(rule["id"], {})
        v = dict(rule, next_at=None, phase=None)
        if not rule["enabled"]:
            return v
        if rule["kind"] == "schedule":
            v["next_at"] = next_schedule(rule, now)
        elif rule["kind"] == "timer":
            v["next_at"] = int(rule["fire_at"])
        elif rule["kind"] == "cycle":
            v["phase"], v["next_at"] = rt.get("phase"), rt.get("next_at")
        else:
            since = [t for t in list(rt.get("below_since", {}).values()) if t]     # read from web threads
            v["next_at"] = int(min(since) + rule["for_min"] * 60) if since else None
        return v

    async def _switch(self, rule: dict, on: bool, outlets: list[int] | None = None) -> bool | None:
        """None = strip offline (nothing sent), False = sent but not confirmed, True = confirmed."""
        s = self.hub.session(rule["mac"])
        if not s:
            return None
        try:
            return await s.set_outlets(outlets or rule["outlets"], on)
        except Exception as err:
            print(f"[rule] {rule['id']} command failed: {err!r}")
            return False

    def _report(self, rule: dict, result: bool | None, what: str) -> None:
        text = f"{what}: {self._where(rule)} {'on' if rule['on'] else 'off'}"
        params = {"rule_id": rule["id"], "on": rule["on"], "outlets": rule["outlets"], "actor": "rule"}
        if result:
            self.hub.event("info", "rule_fired", text, rule["mac"], None, **params)
        elif result is None:
            self.hub.event("warn", "rule_skipped", f"{text} - skipped, strip offline", rule["mac"], None, **params)
        else:
            self.hub.event("warn", "rule_failed", f"{text} - sent but not confirmed by the strip", rule["mac"], None, **params)

    def _where(self, rule: dict, outlets: list[int] | None = None) -> str:
        d = self.hub.devices.get(rule["mac"])
        outlets = outlets or rule["outlets"]
        strip = self.hub.label(d) if d else rule["mac"]
        if outlets == [1, 2, 3, 4]:
            return f"{strip} / all outlets"
        names = ", ".join(self.hub.outlet_label(d, n) if d else f"Outlet {n}" for n in outlets)
        return f"{strip} / {names}"

    async def tick(self, now: float, wait: bool = True) -> None:
        """wait=False (the live loop) runs actions as tasks, so one slow strip never makes another rule late."""
        jobs = []
        for rule in self.store.rules():
            if not rule["enabled"]:
                self.rt.pop(rule["id"], None)
                continue
            if rule["id"] in self.inflight:
                continue
            self.inflight.add(rule["id"])
            jobs.append(self._run(rule, now))
        if wait:
            await asyncio.gather(*jobs)
        else:
            for job in jobs:
                task = asyncio.create_task(job)
                self.action_tasks.add(task)
                task.add_done_callback(self.action_tasks.discard)
        self._offline_alerts(now)
        if now - self.last_budget_check >= 60:
            self.last_budget_check = now
            self._budget(now)

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Allow outcomes to finish, then cancel; never spin forever on a stuck rule."""
        deadline = asyncio.get_running_loop().time() + timeout
        while self.inflight and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(min(.01, max(0, deadline - asyncio.get_running_loop().time())))
        for task in list(self.action_tasks):
            task.cancel()
        # All rule coroutines propagate cancellation; allow their finally blocks
        # to clear inflight before the caller closes the database.
        await asyncio.sleep(0)

    async def _run(self, rule: dict, now: float) -> None:
        try:
            await getattr(self, "_" + rule["kind"])(rule, now, self.rt.setdefault(rule["id"], {}))
        except Exception as err:
            print(f"[rule] {rule['id']} error: {err!r}")
        finally:
            self.inflight.discard(rule["id"])

    async def _schedule(self, rule: dict, now: float, rt: dict) -> None:
        lt = datetime.fromtimestamp(now)
        key = lt.strftime("%Y-%m-%d %H:%M")
        if lt.weekday() not in rule["days"] or lt.strftime("%H:%M") != rule["at"] or rt.get("last_key") == key:
            return
        rt["last_key"] = key
        if self._current(rule):
            self._report(rule, await self._switch(rule, rule["on"]), f"Schedule {rule['at']}")

    async def _timer(self, rule: dict, now: float, rt: dict) -> None:
        if now < rule["fire_at"]:
            return
        if not self.hub.session(rule["mac"]) and now - rule["fire_at"] < 300:
            return                                          # strip offline: keep waiting up to 5 minutes
        if not self.store.consume_rule(rule):               # consumed before the command: a crash never replays it
            return                                          # edited or deleted meanwhile: the new version decides
        self.rt.pop(rule["id"], None)
        self._report(rule, await self._switch(rule, rule["on"]), "Timer")

    async def _cycle(self, rule: dict, now: float, rt: dict) -> None:
        if "phase" in rt and now < rt["next_at"]:
            return
        phase = "on" if rt.get("phase") != "on" else "off"     # a new or restarted cycle begins with "on"
        if not self._current(rule):
            return
        result = await self._switch(rule, phase == "on")
        if result is not None:
            rt["phase"] = phase
            rt["next_at"] = int(now + rule["on_min" if phase == "on" else "off_min"] * 60)
            if result is False:
                self.hub.event("warn", "rule_failed", f"Cycle {phase}: {self._where(rule)} - sent but not confirmed by the strip",
                               rule["mac"], None, rule_id=rule["id"], on=phase == "on", outlets=rule["outlets"], actor="rule")
        else:
            rt.setdefault("phase", None)
            rt["next_at"] = int(now + 10)                   # strip offline: retry soon, keep the phase

    async def _autooff(self, rule: dict, now: float, rt: dict) -> None:
        d = self.hub.devices.get(rule["mac"])
        since = rt.setdefault("below_since", {})
        if not d or not d.online or not d.reported_at or now - d.reported_at > 30:
            since.clear()                                   # no fresh readings = no proof of low draw
            return
        for n in rule["outlets"]:                         # observe() keeps below_since honest per reading
            started = since.get(n)
            if started is None or now - started < rule["for_min"] * 60 or not self._current(rule):
                continue
            since.pop(n, None)
            watts = d.outlets[n]["power_w"]
            result = await self._switch(rule, False, [n])
            if result:
                self.hub.event("info", "autooff", f"Auto-off: {self._where(rule, [n])} drew {watts} W for {rule['for_min']} min",
                               rule["mac"], n, rule_id=rule["id"], watts=watts, actor="rule")
            elif result is False:
                self.hub.event("warn", "rule_failed", f"Auto-off: {self._where(rule, [n])} - sent but not confirmed by the strip",
                               rule["mac"], n, rule_id=rule["id"], on=False, outlets=[n], actor="rule")

    def _offline_alerts(self, now: float) -> None:
        for d in list(self.hub.devices.values()):
            if not d.online and d.offline_since and not d.offline_alerted and now - d.offline_since >= OFFLINE_ALERT_AFTER:
                d.offline_alerted = True
                self.hub.event("warn", "offline", f"{self.hub.label(d)} went offline", d.mac)
            elif d.online and d.offline_alerted:
                d.offline_alerted = False
                self.hub.event("info", "online", f"{self.hub.label(d)} is back online", d.mac)

    def _budget(self, now: float) -> None:
        month = datetime.fromtimestamp(now).strftime("%Y-%m")
        done = self.store.meta("strip_budget_alerted", {})
        for mac in list(self.hub.devices):
            s = self.hub.settings(mac)
            if not s["budget"]:
                continue
            cost = self.hub.db.totals(mac)["month_kwh"] * s["price_kwh"]
            pct = cost / s["budget"] * 100
            step = max((p for p in BUDGET_STEPS if pct >= p), default=0)
            prior = done.get(mac, {})
            if step > (prior.get("step", 0) if prior.get("month") == month else 0):
                done[mac] = {"month": month, "step": step}
                self.store.set_meta("strip_budget_alerted", done)
                self.hub.event("alert" if step >= 90 else "warn", "budget",
                               f"Monthly budget {step}% used: {cost:.2f} of {s['budget']:.2f} {s['currency']}",
                               mac, pct=step, cost=round(cost, 2))

    async def loop(self) -> None:
        while True:
            try:
                await self.tick(time.time(), wait=False)
            except Exception as err:
                print(f"[rule] engine error: {err!r}")
            await asyncio.sleep(1.0)


def public_settings(s: dict) -> dict:
    """Settings for the API: the bot token is write-only."""
    s = dict(s)
    s["telegram_configured"] = bool(s.pop("telegram_token"))
    return s


def clean_settings(body: dict) -> dict:
    out = {}
    for key, value in body.items():
        if key not in DEFAULT_SETTINGS:
            raise ValueError(f"unknown setting {key!r}")
        if key == "currency":
            if not isinstance(value, str) or not 0 < len(value.strip()) <= 8:
                raise ValueError("currency must be 1-8 characters")
            value = value.strip()
        elif key in ("price_kwh", "budget", "temp_max_c", "power_max_w"):
            if value is None and key == "budget":
                pass
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{key} must be a number")
            else:
                lo, hi = {"price_kwh": (0, 1000), "budget": (0.01, 10**7), "temp_max_c": (30, 120), "power_max_w": (100, 10000)}[key]
                if not lo <= value <= hi:
                    raise ValueError(f"{key} must be {lo}-{hi}")
        elif key == "ntfy_url":
            if not isinstance(value, str) or (value and urlparse(value).scheme not in ("http", "https")):
                raise ValueError("ntfy_url must be an http(s) URL or empty")
        elif key == "telegram_token":            # omitted = keep, "" = clear, text = replace
            if not isinstance(value, str):
                raise ValueError("telegram_token must be text")
        elif key == "telegram_chat":
            if not isinstance(value, str):
                raise ValueError("telegram_chat must be text")
        out[key] = value.strip() if isinstance(value, str) else value
    return out
