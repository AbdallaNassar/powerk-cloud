"""Wire protocol, shared constants and outlet parsing (unchanged from powerk.py)."""
from __future__ import annotations

import re

DEVICE_PORT = 10086
SETUP_HOST = "192.168.1.1"      # strip SoftAP setup service
SETUP_PORT = 30300
WEB_PORT = 8080
POLL_SECONDS = 5.0
DIAG_EVERY = 3                  # voltage/current/RSSI every 3rd poll
MAX_MISSES = 3                  # unanswered polls before a silent (half-open) session is dropped
OFFLINE_ALERT_AFTER = 60        # seconds offline before an "offline" alert (the strip re-dials often)
MAX_OUTLET_W = 4000             # energy counter jumps above this power between two readings are glitches
BUDGET_STEPS = (50, 75, 90, 100)
NAME_MAX = 40

DEFAULT_SETTINGS = {
    "currency": "EGP",
    "price_kwh": 2.14,
    "budget": None,             # monthly, in currency; None = off
    "temp_max_c": 60,
    "power_max_w": 3500,
    "ntfy_url": "",
    "telegram_token": "",
    "telegram_chat": "",
}

BOOTINFO_RE = re.compile(
    r"^up:bootinfo:([^;\r\n]+);([0-9A-Fa-f]{12});([0-9A-Fa-f]{12});([^;\r\n]+);connect$"
)
GETINFO_RE = re.compile(
    r"(?P<ch>[1-5]):(?P<runtime>-?\d+);(?P<relay>on|off);(?P<state>-?\d+);"
    r"(?P<overload>[^;:]+);(?P<overheat>[^;:]+);(?P<power>-?\d+);"
    r"(?P<energy>[0-9A-Fa-f]{8});(?P<previous>[0-9A-Fa-f]{8});"
    r"(?P<config>[0-9A-Fa-f]{8});(?P<status>[^;:]+);"
    r"(?P<event>[0-9A-Fa-f]{2});(?P<temperature>-?\d+)",
    re.I,
)
ONOFF_ACK_RE = re.compile(r"^up:onoff:([1-4]):(on|off)$", re.I)
EVENT_RE = re.compile(r"^up:event:onoff:([0-4]):(on|off)$", re.I)
POWER_REPORT_RE = re.compile(r"^up:power_report:([1-5]):(-?\d+)$", re.I)
QUERY_RE = re.compile(r"^up:query:(-?\d+)$")
MAC_RE = re.compile(r"^[0-9A-F]{12}$")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_getinfo(line: str) -> list[dict]:
    """Parse 'up:getinfo:...' into per-outlet records (channel 5 is the aggregate)."""
    text = line.strip("\r\n\x00 ")
    if text.startswith("up:getinfo:"):
        text = text[len("up:getinfo:"):]
    out = []
    for m in GETINFO_RE.finditer(text):
        g = m.groupdict()
        ch = int(g["ch"])
        if ch > 4:
            continue
        out.append({
            "n": ch,
            "on": g["relay"].lower() == "on",
            "power_w": round(int(g["power"]) / 1000.0, 2),
            "energy_kwh": round(int(g["energy"], 16) / 1000.0, 3),
            "temp_c": int(g["temperature"]),
            # overload/overheat read "on;on" on an idle, cool strip (fw 0.1.54-1.0.66): they look like
            # protection *settings*, not trips, so they are not reported as alarms.
        })
    return out
