"""Device sessions, polling, energy accounting and alarms."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

from .notify import NO_PUSH, Notifier
from .protocol import (
    BOOTINFO_RE, DIAG_EVERY, EVENT_RE, MAC_RE, MAX_MISSES, MAX_OUTLET_W,
    ONOFF_ACK_RE, POLL_SECONDS, POWER_REPORT_RE, QUERY_RE, parse_getinfo,
)
from .store import Db, Store
from .sharing import Sharing


class Device:
    def __init__(self, mac: str, model: str, fw: str, ip: str):
        self.mac = mac.upper()
        self.model = model
        self.fw = fw
        self.ip = ip
        self.online = False
        self.voltage_v: float | None = None
        self.rssi: int | None = None
        self.outlets = {n: {"n": n, "on": False, "power_w": 0.0, "energy_kwh": 0.0, "temp_c": 0} for n in range(1, 5)}
        self.counter_wh: dict[int, int] = {}       # last cumulative energy counter per outlet
        self.counter_ts: float | None = None
        self.glitches: dict[int, int] = {}         # consecutive implausible counter jumps per outlet
        self.reported_at: float | None = None     # time of the last complete getinfo
        self.last_getinfo = ""
        self.offline_since: float | None = None
        self.offline_alerted = False
        self.raised: set[tuple] = set()           # alarms already reported (edge-triggered)

    @property
    def name(self) -> str:
        return f"MTTL {self.mac[-7:]}"

    @property
    def current_a(self) -> float:
        if not self.voltage_v:
            return 0.0
        return round(sum(o["power_w"] for o in self.outlets.values()) / self.voltage_v, 2)

    def snapshot(self) -> dict:
        outlets = [dict(o) for o in self.outlets.values()]
        return {
            "mac": self.mac,
            "name": self.name,
            "model": self.model,
            "fw": self.fw,
            "ip": self.ip,
            "online": self.online,
            "on": any(o["on"] for o in outlets),
            "power_w": round(sum(o["power_w"] for o in outlets), 2),
            "energy_kwh": round(sum(o["energy_kwh"] for o in outlets), 3),
            "voltage": self.voltage_v,
            "current_a": self.current_a,
            "rssi": self.rssi,
            "reported_at": int(self.reported_at) if self.reported_at else None,
            "outlets": outlets,
        }


class Session:
    """One connected strip. Only one command transaction runs at a time."""

    def __init__(self, ip: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.ip = ip
        self.reader = reader
        self.writer = writer
        self.lock = asyncio.Lock()
        self.device: Device | None = None
        self.got_getinfo = asyncio.Event()
        self.last_cmd = ""
        self.last_rx = ""
        self.misses = 0                 # consecutive unanswered polls

    async def send(self, cmd: str) -> None:
        self.last_cmd = cmd
        self.writer.write((cmd + "\r\n").encode("ascii"))
        await self.writer.drain()

    async def _refresh(self, timeout: float = 6.0) -> bool:
        self.got_getinfo.clear()
        await self.send("up:getinfo:all")
        try:
            await asyncio.wait_for(self.got_getinfo.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def refresh(self, timeout: float = 4.0) -> bool:
        async with self.lock:
            return await self._refresh(timeout)

    async def set_outlets(self, channels: list[int], on: bool) -> bool:
        """Send the commands; True only when a fresh snapshot shows every outlet in the wanted state."""
        async with self.lock:
            for ch in channels:
                await self.send(f"up:onoff:{ch}:{'on' if on else 'off'}")
            await asyncio.sleep(0.3)          # let the relay settle before the snapshot
            if not await self._refresh():
                return False
            return bool(self.device) and all(self.device.outlets[ch]["on"] == on for ch in channels)

    async def diagnostics(self) -> None:
        async with self.lock:
            await self.send("up:power_report:1:vol")
            await self.send("up:query:wifirssi")


class Hub:
    def __init__(self, store: Store | None = None, db: Db | None = None, notifier: Notifier | None = None,
                 allow: set[str] | None = None) -> None:
        self.devices: dict[str, Device] = {}
        self.sessions: dict[str, Session] = {}
        self.store = store or Store(None)
        self.db = db or Db(":memory:")
        self.sharing = Sharing(self.db)
        self.notifier = notifier or Notifier(self.store)
        self.fcm = None
        self.legacy_notifications = False
        self.connections_per_ip: dict[str, int] = {}
        self.allow = allow or set()           # empty = accept any strip
        self.observers: list = []             # f(device, now) after every complete reading

    def session(self, mac: str) -> Session | None:
        s = self.sessions.get(mac.upper())
        if s and s.device and s.device.online and not s.writer.is_closing():
            return s
        return None

    def label(self, d: Device) -> str:
        return self.store.name(d.mac, 0) or d.name

    def outlet_label(self, d: Device, n: int) -> str:
        return self.store.name(d.mac, n) or f"Outlet {n}"

    def event(self, level: str, code: str, text: str, mac: str | None = None, outlet: int | None = None, **params) -> None:
        params.setdefault("actor", "strip")
        ev = {"ts": time.time(), "level": level, "code": code, "mac": mac, "outlet": outlet, "text": text, "params": params}
        print(f"[{level}] {text}")
        ev['id'] = self.db.add_event(ev)
        if self.legacy_notifications and self.store.meta("accounts_migrated") is None and code not in NO_PUSH:
            self.notifier.send(f"powerk: {code.replace('_', ' ')}", text)
        if mac:
            for user_id, settings in self.sharing.recipients(mac, code, level, include_users=True):
                if settings['ntfy_url'] or (settings['telegram_token'] and settings['telegram_chat']):
                    self.notifier.send(f"powerk: {code.replace('_', ' ')}", text, settings)
                if self.fcm:
                    self.fcm.send(user_id, ev)

    def settings(self, mac: str) -> dict:
        # Existing unclaimed strips retain legacy settings until claimed/migrated.
        return self.sharing.settings(mac, self.store.settings())

    def read_pointer(self, user_id: int | None = None) -> int:
        return self.store.meta("events_read_id", 0) if user_id is None else self.sharing.read_pointer(user_id)

    @staticmethod
    def alarms(d: Device, settings: dict) -> tuple[list[str], dict[int, list[str]]]:
        """Active alarms: temp_high (outlet temperature) and power_high (strip total), from our own limits."""
        per = {n: ["temp_high"] if o["temp_c"] >= settings["temp_max_c"] else [] for n, o in d.outlets.items()}
        device = ["temp_high"] if any(per.values()) else []
        if sum(o["power_w"] for o in d.outlets.values()) >= settings["power_max_w"]:
            device.append("power_high")
        return device, per

    def snapshot(self, user_id: int | None = None) -> dict:
        roles = self.sharing.accessible(user_id) if user_id is not None else None
        settings = self.sharing.settings("")
        devices = []
        for d in list(self.devices.values()):               # called from web threads
            if roles is not None and d.mac not in roles:
                continue
            s = self.settings(d.mac)
            price = s["price_kwh"]
            snap = d.snapshot()
            alarms, per = self.alarms(d, s)
            totals = self.db.totals(d.mac)
            snap.update(label=self.store.name(d.mac, 0), alarms=alarms, alarm=(alarms or [None])[0],
                        today_kwh=totals["today_kwh"], month_kwh=totals["month_kwh"],
                        month_cost=round(totals["month_kwh"] * price, 2), role=roles[d.mac] if roles is not None else "owner",
                        currency=s["currency"], price_kwh=price, budget=s["budget"])
            for o in snap["outlets"]:
                o["name"] = self.store.name(d.mac, o["n"])
                o["alarms"] = per.get(o["n"], [])
                o["alarm"] = (o["alarms"] or [None])[0]
            devices.append(snap)
        if devices:
            settings = devices[0]
        elif user_id is None:
            settings = self.store.settings()
        mixed = len({d["currency"] for d in devices}) > 1
        totals_from = devices[:1] if mixed else devices
        month_kwh = round(sum(d["month_kwh"] for d in totals_from), 3)
        month_cost = round(sum(d["month_cost"] for d in totals_from), 2)
        now = time.time()
        return {"api_version": 2, "server_time": int(now),
                "utc_offset_seconds": int(datetime.fromtimestamp(now).astimezone().utcoffset().total_seconds()),
                "devices": devices, "currency": settings["currency"], "price_kwh": settings["price_kwh"], "budget": settings["budget"],
                "month_kwh": month_kwh, "month_cost": month_cost,
                "unread_alerts": self.db.unread(self.read_pointer(user_id), user_id)}

    def remember(self, d: Device) -> None:
        """Known strips survive a restart, so names/rules/history stay usable while a strip is offline."""
        known = self.store.meta("devices", {})
        if known.get(d.mac) != {"model": d.model, "fw": d.fw}:
            known[d.mac] = {"model": d.model, "fw": d.fw}
            self.store.set_meta("devices", known)

    def restore(self) -> None:
        known = {mac: {} for mac in sorted(self.db.known_macs() | self.sharing.claimed())}
        known.update(self.store.meta("devices", {}))
        for mac, info in known.items():
            if MAC_RE.match(mac) and (not self.allow or mac in self.allow):
                d = self.devices.setdefault(mac, Device(mac, str(info.get("model", "")), str(info.get("fw", "")), ""))
                d.offline_since = d.offline_since or time.time()      # alerts if it does not come back within a minute

    def on_getinfo(self, d: Device, records: list[dict], now: float) -> None:
        """New outlet readings: store energy deltas, report alarms on their rising edge."""
        since = d.counter_ts
        limit = 50 + MAX_OUTLET_W * (now - since) / 3600 if since else 0
        for r in records:
            wh = round(r["energy_kwh"] * 1000)
            prev = d.counter_wh.get(r["n"])
            d.counter_wh[r["n"]] = wh
            if prev is None:                              # first reading is the baseline, not consumption
                continue
            delta = wh - prev if wh >= prev else wh      # counter went down = strip reset it
            if 0 < delta <= limit:
                self.db.add_energy(d.mac, r["n"], delta, now, since)
                d.glitches.pop(r["n"], None)
            elif delta > limit:
                d.glitches[r["n"]] = d.glitches.get(r["n"], 0) + 1
                if d.glitches[r["n"]] < 3:
                    d.counter_wh[r["n"]] = prev           # keep the trusted baseline for the next reading
                    print(f"[energy] {d.name} outlet {r['n']}: ignored counter jump of {delta} Wh")
                else:
                    d.glitches.pop(r["n"], None)            # the jump persists: new baseline, nothing counted
                    print(f"[energy] {d.name} outlet {r['n']}: counter re-based at {wh} Wh")
        d.counter_ts = d.reported_at = now
        d.outlets = {r["n"]: r for r in records}
        for observe in self.observers:
            observe(d, now)

        settings = self.settings(d.mac)
        _, per = self.alarms(d, settings)
        active = {(code, n) for n, codes in per.items() for code in codes}
        total = sum(o["power_w"] for o in d.outlets.values())
        if total >= settings["power_max_w"]:
            active.add(("power_high", 0))
        elif ("power_high", 0) in d.raised and total >= settings["power_max_w"] * 0.95:
            active.add(("power_high", 0))                  # hysteresis: no flapping right at the limit
        for code, n in sorted(active - d.raised):
            if code == "power_high":
                self.event("alert", code, f"{self.label(d)}: total power {total:.0f} W (limit {settings['power_max_w']} W)",
                           d.mac, 0, watts=round(total, 1))
            else:
                o = d.outlets[n]
                detail = f" {o['temp_c']} C" if code == "temp_high" else ""
                self.event("alert", code, f"{self.label(d)} / {self.outlet_label(d, n)}: {code.replace('_', ' ')}{detail}",
                           d.mac, n, temp_c=o["temp_c"], watts=o["power_w"])
        d.raised = active

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else "?"
        if self.connections_per_ip.get(ip, 0) >= 8:
            print(f"[device] {ip}: TCP session limit (8), dropping connection")
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return
        self.connections_per_ip[ip] = self.connections_per_ip.get(ip, 0) + 1
        s = Session(ip, reader, writer)
        print(f"[device] connection from {ip}")
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                if len(raw) > 8192:
                    raise ValueError("line too long")
                line = raw.replace(b"\x00", b"").decode("utf-8", "replace").strip("\r\n ")
                s.last_rx = line

                m = BOOTINFO_RE.match(line)
                if m:
                    mac = m.group(2).upper()
                    if self.allow and mac not in self.allow:
                        print(f"[device] {ip} announced {mac}, not in --mac list: closing")
                        break
                    d = self.devices.get(mac) or Device(mac, m.group(1), m.group(4), ip)
                    d.model, d.fw, d.ip, d.online = m.group(1), m.group(4), ip, True
                    d.offline_since = None
                    s.device = d
                    self.devices[mac] = d
                    old = self.sessions.get(mac)
                    if old and old is not s:
                        old.writer.close()
                    self.sessions[mac] = s
                    self.remember(d)
                    print(f"[device] {d.name} model={d.model} fw={d.fw}")
                    asyncio.create_task(s.refresh())
                    continue

                if not s.device:
                    continue

                if line.startswith("up:getinfo:"):
                    records = parse_getinfo(line)
                    if sorted(r["n"] for r in records) == [1, 2, 3, 4]:
                        s.device.last_getinfo = line
                        self.on_getinfo(s.device, records, time.time())
                        s.got_getinfo.set()
                    continue

                if line.lower().startswith("up:power_report:"):
                    m = POWER_REPORT_RE.fullmatch(line)
                    if m and int(m.group(2)) >= 50000:      # mV -> V; sub-50000 values are per-outlet current, unused
                        s.device.voltage_v = round(int(m.group(2)) / 1000.0, 1)
                    continue

                m = QUERY_RE.fullmatch(line)
                if m:
                    s.device.rssi = int(m.group(1))
                    continue

                m = EVENT_RE.fullmatch(line)
                if m:
                    ch, on = int(m.group(1)), m.group(2).lower() == "on"
                    if self.sessions.get(s.device.mac) is not s:
                        continue
                    for n in ([ch] if ch else [1, 2, 3, 4]):      # 0 = master button
                        s.device.outlets[n]["on"] = on
                    self.sharing.button(s.device.mac)
                    self.event("info", "onoff", f"{self.label(s.device)}: button {'on' if on else 'off'}",
                               s.device.mac, ch, on=on, actor="strip")
                    continue

                if ONOFF_ACK_RE.fullmatch(line):
                    continue
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        except Exception as err:
            print(f"[device] session error {ip}: {err!r} (last sent {s.last_cmd!r}, last received {s.last_rx!r})")
        finally:
            self.connections_per_ip[ip] -= 1
            if not self.connections_per_ip[ip]:
                self.connections_per_ip.pop(ip)
            if s.device:
                if self.sessions.get(s.device.mac) is s:
                    self.sessions.pop(s.device.mac, None)
                    s.device.online = False
                    s.device.offline_since = time.time()
                    print(f"[device] {s.device.name} offline")
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def poll_loop(self) -> None:
        n = 0
        while True:
            n += 1
            for s in list(self.sessions.values()):
                if not s.device:
                    continue
                try:
                    if not await s.refresh():
                        s.misses += 1
                        print(f"[device] {s.device.name} poll timeout ({s.misses}/{MAX_MISSES})")
                        if s.misses >= MAX_MISSES:
                            # a strip that lost power never sends FIN; without this it stays "online" forever
                            print(f"[device] {s.device.name} not answering, dropping session")
                            s.writer.close()
                        continue
                    s.misses = 0
                    if n % DIAG_EVERY == 0:
                        await s.diagnostics()
                except Exception as err:
                    print(f"[device] poll error: {err!r}")
            await asyncio.sleep(POLL_SECONDS)



def parse_macs(values: list[str]) -> set[str]:
    macs = {m.strip().upper().replace(":", "").replace("-", "") for v in values for m in v.split(",") if m.strip()}
    bad = [m for m in macs if not MAC_RE.match(m)]
    if bad:
        raise SystemExit(f"--mac needs 12 hex digits, got {', '.join(bad)}")
    return macs
