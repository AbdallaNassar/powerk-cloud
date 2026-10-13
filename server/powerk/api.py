"""FastAPI transport for the legacy HTTP contract, with manual validation."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from starlette.exceptions import HTTPException

from .accounts import Accounts, normalize_phone, password_input
from .devices import Hub
from .protocol import DEVICE_PORT, NAME_MAX
from .rules import Engine, _is_outlet, clean_rule, clean_settings, public_settings
from .sessions import ACCESS_SECONDS, REFRESH_SECONDS, AuthError, token_hash
from .sharing import CHANNEL_KEYS, CLAIM_ERROR, STRIP_KEYS
from .ratelimit import RateLimiter, RateLimited
from .security import SecurityHeaders, client_ip, parse_trusted_proxies
from .push import PushTokens
from .fcm import FCM
from .realtime import LiveUpdates

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APK = REPO_ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
PROVISION_FILE = REPO_ROOT / "tools/provision.py"
WEB_ROOT = Path(__file__).resolve().parent / "web"
# A route cannot reach a domain handler without an explicit policy. Unknown policies
# fail closed, including for legacy credentials. Auth/public routes have their own gates.
API_POLICIES = {
    ("GET", "/api/state"): "list", ("GET", "/api/debug"): "list",
    ("GET", "/api/rules"): "optional-read", ("GET", "/api/events"): "optional-read",
    ("GET", "/api/history"): "read", ("POST", "/api/onoff"): "control",
    ("POST", "/api/name"): "control", ("POST", "/api/rules"): "control",
    ("GET", "/api/settings"): "legacy", ("PUT", "/api/settings"): "legacy",
    ("POST", "/api/alerts/test"): "list", ("POST", "/api/events/read"): "list",
    ("GET", "/api/me/notifications"): "account", ("PUT", "/api/me/notifications"): "account",
    ("POST", "/api/strips/claim"): "account",
    ("GET", "/api/me/security-log"): "account",
    ("POST", "/api/me/push-tokens"): "account",
}
STRIP_POLICIES = {
    ("GET", "settings", False): "read", ("PUT", "settings", False): "owner",
    ("GET", "access", False): "owner", ("POST", "access", False): "owner",
    ("PUT", "access", True): "owner", ("DELETE", "access", True): "owner",
    ("POST", "leave", False): "leave", ("POST", "transfer", False): "owner",
    ("DELETE", "", False): "owner",
}
PUBLIC_GET = {"/", "/index.html", "/app.js", "/app.css", "/powerk.py", "/powerk.apk"}
PUBLIC_AUTH = {"/api/auth/register", "/api/auth/login", "/api/auth/refresh"}
AUTH_GET = {"/api/auth/me", "/api/auth/sessions"}
AUTH_POST = PUBLIC_AUTH | {"/api/auth/logout", "/api/auth/password"}


def _response(body: bytes, ctype: str, code: int = 200, **headers: str) -> Response:
    # Explicit content type preserves the existing JSON/download contract.
    return Response(body, status_code=code, headers={
        "Content-Type": ctype, **headers,
    })


def _json(obj, code=200) -> Response:
    return _response(json.dumps(obj).encode(), "application/json", code, **{"Cache-Control": "no-store"})


class _Web:
    """Per-request adapter; domain logic remains in the original classes."""

    def __init__(self, request: Request):
        self.request = request
        state = request.app.state
        self.hub, self.engine = state.hub, state.engine
        self.local_ip, self.port, self.token = state.local_ip, state.port, state.token
        self.headers = request.headers
        self.accounts, self.sessions = state.accounts, state.accounts.sessions
        self.limiter, self.audit = state.rate_limiter, self.accounts.audit
        self.ip = client_ip(request.client.host if request.client else '', self.headers, state.trusted_proxies)
        request.state.client_ip = self.ip
        self.identity = self.current_user = None
        self.auth_method = None
        # Match the raw escaped URL, as BaseHTTPRequestHandler did.
        self.path = request.scope["raw_path"].decode("ascii")
        if request.scope["query_string"]:
            self.path += "?" + request.scope["query_string"].decode("ascii")

    def _legacy_authorized(self) -> bool:
        """Optional shared credential: X-Token header, HTTP Basic (browser), ?t= (simple clients)
        or the cookie the page sets after a ?t= visit (so the page's own API calls work too)."""
        if not self.token:
            return False
        if secrets.compare_digest(self.headers.get("X-Token", ""), self.token):
            return True
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
        except Exception:
            cookie = SimpleCookie()
        if "powerk_t" in cookie and secrets.compare_digest(unquote(cookie["powerk_t"].value), self.token):
            return True
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                user, _, password = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
            except Exception:
                return False
            if secrets.compare_digest(password, self.token) or secrets.compare_digest(user, self.token):
                return True
        return secrets.compare_digest(parse_qs(urlparse(self.path).query).get("t", [""])[0], self.token)

    def _resolve_auth(self) -> bool:
        """Resolve credentials once; strip permissions are read afresh on each request."""
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            self.identity = self.sessions.resolve(auth[7:])
            self.auth_method = "bearer" if self.identity else None
        else:
            self.identity = self.sessions.resolve(self.request.cookies.get("powerk_access", ""))
            if self.identity:
                self.auth_method = "cookie"
            elif self._legacy_authorized():
                self.auth_method = "legacy"
        self.current_user = self.identity.user if self.identity else None
        self.request.state.current_user = self.current_user
        self.request.state.session_family_id = self.identity.family_id if self.identity else None
        self.request.state.auth_method = self.auth_method
        return self.auth_method is not None

    def _csrf(self) -> None:
        cookie = self.request.cookies.get("powerk_csrf", "")
        header = self.headers.get("X-CSRF-Token", "")
        if not cookie or not secrets.compare_digest(cookie.encode("utf-8"), header.encode("utf-8")):
            raise AuthError("CSRF token required", 403)

    def _pair(self, pair: dict, code: int = 200, *, cookie_refresh: bool = False) -> Response:
        web = cookie_refresh or self.headers.get("X-Powerk-Client") == "web"
        response = _json({"user": pair["user"], "expires_in": pair["expires_in"]} if web else pair, code)
        if web:
            secure = self.request.app.state.secure_cookies
            csrf = self.request.cookies.get("powerk_csrf") if cookie_refresh else None
            for name, value, path, age, http_only in (
                ("powerk_access", pair["access_token"], "/", ACCESS_SECONDS, True),
                ("powerk_refresh", pair["refresh_token"], "/api/auth/", REFRESH_SECONDS, True),
                ("powerk_csrf", csrf or secrets.token_urlsafe(32), "/", REFRESH_SECONDS, False),
            ):
                response.set_cookie(name, value, path=path, max_age=age, secure=secure, httponly=http_only, samesite="strict")
        return response

    def _clear_cookies(self, response: Response) -> Response:
        for name, path in (("powerk_access", "/"), ("powerk_refresh", "/api/auth/"), ("powerk_csrf", "/"), ("powerk_t", "/")):
            response.delete_cookie(name, path=path, secure=self.request.app.state.secure_cookies,
                                   httponly=name != "powerk_csrf", samesite="strict")
        return response

    def _auth(self, method: str, path: str, body: dict) -> Response:
        if path in ("/api/auth/register", "/api/auth/login"):
            if self.request.cookies.get("powerk_access"):
                self._csrf()
            if path.endswith("register") and not self.request.app.state.open_registration:
                raise AuthError("registration is closed", 403)
            if path.endswith('register'):
                pair = self.accounts.register(body.get('phone'), body.get('password'), self.headers.get('User-Agent', ''), self.ip)
            else:
                phone, password = normalize_phone(body.get('phone')), password_input(body.get('password'))
                key = token_hash(phone)
                with self.limiter.phone_lock(key):
                    self.limiter.check_phone(key)
                    try:
                        pair = self.accounts.login(phone, password, self.headers.get('User-Agent', ''), self.ip)
                    except AuthError as err:
                        if err.status == 401:
                            self.limiter.fail_phone(key)
                        raise
                    self.limiter.reset_phone(key)
            return self._pair(pair, 201 if path.endswith("register") else 200)
        if path == "/api/auth/refresh":
            from_cookie = "refresh_token" not in body
            refresh = self.request.cookies.get("powerk_refresh", "") if from_cookie else body["refresh_token"]
            if not isinstance(refresh, str):
                raise AuthError("refresh_token must be a string")
            if from_cookie and refresh:
                self._csrf()
            return self._pair(self.sessions.refresh(refresh, self.ip), cookie_refresh=from_cookie)
        # A legacy shared credential has no user whose account could be managed.
        if self.identity is None:
            raise AuthError("session required", 401)
        if path == "/api/auth/me":
            return _json({"user": self.current_user})
        if path == "/api/auth/sessions":
            return _json({"sessions": self.sessions.list(self.identity)})
        if path == "/api/auth/logout":
            self.sessions.revoke(self.identity, self.identity.family_id, self.ip, action='logout')
            return self._clear_cookies(_json({"ok": True}))
        if path == "/api/auth/password":
            self.accounts.change_password(self.identity, body.get("current_password"), body.get("new_password"), self.ip)
            return _json({"ok": True})
        family_id = path[len("/api/auth/sessions/"):]
        self.sessions.revoke(self.identity, family_id, self.ip)
        response = _json({"ok": True})
        return self._clear_cookies(response) if family_id == self.identity.family_id else response

    def _deny(self) -> Response:
        if not self.token or self.headers.get("X-Powerk-Client") == "web":
            return _json({"error": "session required"}, 401)
        api = urlparse(self.path).path.startswith("/api/")
        body = b'{"error": "token required"}' if api else b"powerk: token required\n"
        return _response(body, "application/json" if api else "text/plain", 401,
                         **{"WWW-Authenticate": 'Basic realm="powerk"'})

    def _file(self, body: bytes, ctype: str, filename: str) -> Response:
        # no-store: Cloudflare otherwise caches .apk/.py downloads for hours and serves an old build after an update.
        return _response(body, ctype, **{"Content-Disposition": f'attachment; filename="{filename}"',
                                         "Cache-Control": "no-store"})

    async def _body(self) -> dict | Response:
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            return _json({"error": "Content-Type must be application/json"}, 415)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length < 0 or length > 16384:
                raise ValueError("body too large")
            raw = bytearray()
            async for chunk in self.request.stream():
                if len(raw) + len(chunk) > 16384:
                    raise ValueError("body too large")
                raw.extend(chunk)
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            return body
        except Exception:
            return _json({"error": "bad request"}, 400)

    def _query(self) -> dict:
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    @property
    def user_id(self) -> int | None:
        return self.current_user["id"] if self.current_user else None

    @property
    def actor(self):
        return self.user_id if self.user_id is not None else "legacy"

    def _route_policy(self, method: str, path: str, font: bool) -> str | None:
        self.strip_mac = self.strip_part = self.access_id = None
        if method == "GET" and (path in PUBLIC_GET or font):
            return "public"
        if (method, path) in API_POLICIES:
            return API_POLICIES[method, path]
        if re.fullmatch(r"/api/rules/[^/]+", path) and method in ("PUT", "DELETE"):
            return "rule"
        if re.fullmatch(r"/api/strips/claim/[^/]+", path) and method == "GET":
            return "account"
        if path.startswith('/api/me/push-tokens/') and method == 'DELETE' and path[len('/api/me/push-tokens/'):]:
            return 'account'
        match = re.fullmatch(r"/api/strips/([^/]+)(?:/(settings|access|leave|transfer)(?:/([0-9]+))?)?", path)
        if match:
            self.strip_mac, self.strip_part, self.access_id = match.groups()
            self.strip_mac = self.strip_mac.upper()
            return STRIP_POLICIES.get((method, self.strip_part or "", self.access_id is not None))
        return None

    def _authorize(self, policy: str, path: str, body: dict) -> None:
        if policy not in {"public", "list", "optional-read", "read", "control", "owner", "leave", "rule", "legacy", "account"}:
            raise AuthError("forbidden", 403)
        if policy == "public":
            return
        if policy in ("account", "leave") and self.user_id is None:
            raise AuthError("session required", 401)
        if policy == "legacy" and self.auth_method != "legacy":
            raise AuthError("use /api/strips/{mac}/settings and /api/me/notifications", 410)
        if self.auth_method == "legacy":
            if self.strip_mac and self.strip_mac not in self.hub.devices and self.strip_mac not in self.hub.sharing.claimed():
                raise AuthError("unknown strip", 404)
            return
        if policy in ("list", "account"):
            return
        roles = {"control": ("owner", "control"), "rule": ("owner", "control"), "owner": ("owner",),
                 "leave": ("control", "viewer")}.get(policy, ("owner", "control", "viewer"))
        if policy == "rule":
            rule = self.hub.store.rule(path[len("/api/rules/"):])
            if not rule:
                raise AuthError("unknown strip", 404)
            self.hub.sharing.require(rule["mac"], self.user_id, roles)
            # Moving a rule must authorize both its source and its destination.
            mac = str(body.get("mac", rule["mac"])).upper()
        else:
            mac = self.strip_mac or str(body.get("mac", "") if policy == "control" else self._query().get("mac", "")).upper()
        if policy == "optional-read" and not mac:
            return
        self.hub.sharing.require(mac, self.user_id, roles)

    def _notifications(self, method: str, body: dict) -> Response:
        if method == "PUT":
            channels = {k: v for k, v in body.items() if k != "alerts"}
            changes = self._settings_changes(channels, CHANNEL_KEYS)
            self.hub.sharing.update_notifications(self.user_id, changes, body.get("alerts", {}))
        result = self.hub.sharing.notifications(self.user_id)
        result['fcm'] = {'enabled': self.request.app.state.fcm.enabled,
                         'devices': len(self.request.app.state.push_tokens.for_user(self.user_id))}
        return _json(result)

    def _push_tokens(self, method, path, body):
        tokens = self.request.app.state.push_tokens
        if method == 'POST':
            tokens.register(self.identity, body, self.ip)
        else:
            tokens.delete(unquote(path[len('/api/me/push-tokens/'):]), self.user_id, self.ip)
        return _json({'ok': True})

    @staticmethod
    def _settings_changes(body: dict, keys: tuple) -> dict:
        for key in body:
            if key not in keys:
                raise ValueError(f"unknown setting {key!r}")
        return clean_settings(body)

    def _strip(self, method: str, body: dict) -> Response:
        sharing, mac, part = self.hub.sharing, self.strip_mac, self.strip_part
        if part == "settings":
            if method == "GET":
                return _json(sharing.settings(mac))
            return _json(sharing.update_settings(mac, self._settings_changes(body, STRIP_KEYS), self.user_id, self.ip))
        if part == "access":
            if method == "GET":
                return _json({"access": sharing.access(mac)})
            if method == "POST":
                sharing.share(mac, body.get("phone"), body.get("role"), self.user_id, self.ip)
            else:
                role = sharing.clean_role(body.get("role")) if method == "PUT" else None
                sharing.change_access(mac, int(self.access_id), self.user_id, role, self.ip)
        elif part == "transfer":
            sharing.transfer(mac, body.get("phone"), self.user_id, self.ip)
        elif part == "leave":
            sharing.leave(mac, self.user_id, self.ip)
        else:
            sharing.unclaim(mac, self.user_id, self.ip)
        return _json({"ok": True})

    def _claim(self, body: dict) -> Response:
        code = body.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9a-fA-F]{7}", code):
            raise AuthError("code must be 7 hex characters")
        claimed = self.hub.sharing.claimed()
        matches = [d.mac for d in list(self.hub.devices.values()) if d.mac.endswith(code.upper())
                   and self.hub.session(d.mac) and d.mac not in claimed]
        if len(matches) != 1:
            raise AuthError(CLAIM_ERROR, 404)
        return _json(self.hub.sharing.start_claim(self.user_id, matches[0], self.ip))

    def _audit(self, code: str, mac: str, **params) -> None:
        self.hub.event("info", code, code.replace("_", " "), mac, actor=self.actor, **params)

    def _get(self, path: str) -> Response:
        if path == '/api/me/security-log':
            q = self._query()
            try:
                limit = max(1, min(100, int(q.get('limit', 50))))
                before = int(q['before_id']) if q.get('before_id') else None
                if before is not None and not 1 <= before <= 2**63 - 1:
                    raise ValueError('invalid cursor')
            except ValueError:
                return _json({'error': 'limit must be a number and before_id a positive 64-bit integer'}, 400)
            rows = self.audit.list(self.user_id, limit, before)
            return _json({'events': rows, 'next_before_id': rows[-1]['id'] if len(rows) == limit else None})
        elif path == "/api/state":
            snap = self.hub.snapshot(self.user_id)
            snap["local_ip"], snap["port"] = self.local_ip, self.port
            return _json(snap)
        elif path == "/api/rules":
            mac = self._query().get("mac", "").upper()
            now = time.time()
            access = self.hub.sharing.accessible(self.user_id) if self.user_id is not None else None
            return _json({"rules": [self.engine.view(r, now) for r in self.hub.store.rules()
                                   if (not mac or r["mac"] == mac) and (access is None or r["mac"] in access)]})
        elif path == "/api/history":
            q = self._query()
            try:
                outlet = int(q["outlet"]) if q.get("outlet") else None
                if outlet is not None and outlet not in (1, 2, 3, 4):
                    raise ValueError("outlet must be 1-4")
                mac = q.get("mac", "").upper()
                if self.user_id is None and mac not in self.hub.devices:
                    raise ValueError("mac must be a known strip")
                s = self.hub.settings(mac)
                h = self.hub.db.history(mac, q.get("range", "week"), s["price_kwh"], outlet)
            except ValueError as err:
                return _json({"error": str(err)}, 400)
            h["currency"] = s["currency"]
            return _json(h)
        elif path == "/api/settings":
            return _json(public_settings(self.hub.store.settings()))
        elif path == "/api/events":
            q = self._query()
            try:
                limit = max(1, min(500, int(q.get("limit", 50))))
                before = int(q["before_id"]) if q.get("before_id") else None
            except ValueError:
                return _json({"error": "limit and before_id must be numbers"}, 400)
            mac = q.get("mac", "").upper() or None
            return _json({"events": self.hub.db.events(limit, before, user_id=self.user_id, mac=mac),
                        "unread_alerts": self.hub.db.unread(self.hub.read_pointer(self.user_id), self.user_id, mac)})
        elif path == "/api/debug":
            access = self.hub.sharing.accessible(self.user_id) if self.user_id is not None else None
            return _json({"devices": [{"mac": d.mac, "online": d.online, "last_getinfo": d.last_getinfo,
                                     "counter_wh": d.counter_wh} for d in list(self.hub.devices.values())
                                     if access is None or d.mac in access]})
        elif path.startswith("/fonts/"):
            return _response(self.request.app.state.fonts[path[7:]], "font/woff2",
                             **{"Cache-Control": "max-age=31536000, immutable"})
        elif path in ('/app.js', '/app.css'):
            body, ctype, etag = self.request.app.state.assets[path]
            headers = {'Cache-Control': 'public, max-age=0, must-revalidate', 'ETag': etag}
            tags = self.headers.get('If-None-Match', '').split(',')
            if any(tag.strip().removeprefix('W/') in (etag, '*') for tag in tags):
                return _response(b'', ctype, 304, **headers)
            return _response(body, ctype, **headers)
        elif path in ("/", "/index.html"):
            headers = {"Set-Cookie": f"powerk_t={quote(self.token)}; Path=/; HttpOnly; SameSite=Strict"} if self._legacy_authorized() else {}
            return _response(self.request.app.state.page, "text/html; charset=utf-8", **headers)
        elif path == "/powerk.py":               # public: lets a phone/borrowed laptop fetch this file to run `provision`
            return self._file(PROVISION_FILE.read_bytes(), "text/x-python", "powerk.py")
        elif path == "/powerk.apk":              # public: the Android app, once built (android/ -> gradlew assembleDebug)
            apk = self.request.app.state.apk
            if not apk.is_file():
                return _json({"error": "no APK built yet: cd android && gradlew assembleDebug"}, 404)
            return self._file(apk.read_bytes(), "application/vnd.android.package-archive", "powerk.apk")
        else:
            return _json({"error": "not found"}, 404)

    def _write(self, method: str, path: str, rule_id: str | None, body: dict) -> Response:
        store = self.hub.store

        if path == "/api/name":
            mac = str(body.get("mac", "")).upper()
            outlet, name = body.get("outlet"), body.get("name", "")
            if (mac not in self.hub.devices or not _is_outlet(outlet, 0)
                    or not isinstance(name, str) or len(name.strip()) > NAME_MAX):
                return _json({"error": f"need a known mac, outlet 0-4 and a name up to {NAME_MAX} characters"}, 400)
            store.set_name(mac, outlet, name.strip())
            self._audit("name_changed", mac, outlet=outlet)
            return _json({"ok": True})
        elif path == "/api/rules":
            try:
                rule = clean_rule(body, time.time())
            except ValueError as err:
                return _json({"error": str(err)}, 400)
            store.put_rule(rule)
            self._audit("rule_created", rule["mac"], rule_id=rule["id"])
            return _json({"ok": True, "rule": self.engine.view(rule)})
        elif rule_id:
            old = store.rule(rule_id)
            if not old:
                return _json({"error": "no such rule"}, 404)
            if method == "DELETE":
                store.delete_rule(rule_id)
                self.engine.reset(rule_id)
                self._audit("rule_deleted", old["mac"], rule_id=rule_id)
                return _json({"ok": True})
            try:
                rule = clean_rule(body, time.time(), base=old)
            except ValueError as err:
                return _json({"error": str(err)}, 400)
            store.put_rule(rule)
            self._audit("rule_updated", rule["mac"], rule_id=rule_id)
            self.engine.reset(rule_id)                    # e.g. a cycle restarts with its "on" phase
            return _json({"ok": True, "rule": self.engine.view(rule)})
        elif path == "/api/settings":
            try:
                changes = clean_settings(body)
            except ValueError as err:
                return _json({"error": str(err)}, 400)
            updated = store.update_settings(changes)
            # The legacy client still edits one global form. Its strip fields apply
            # to every claimed strip; owners can subsequently customize each one.
            strip_changes = {k: v for k, v in changes.items() if k in STRIP_KEYS}
            if strip_changes:
                for mac in self.hub.sharing.claimed():
                    self.hub.sharing.update_settings(mac, strip_changes, self.user_id, self.ip)
                self.audit.record('strip_settings_change', self.user_id, self.ip, 'legacy_defaults', changes=strip_changes)
            return _json(public_settings(updated))
        elif path == "/api/alerts/test":
            sent, failed = (self.hub.notifier.test() if self.user_id is None else
                            self.hub.notifier.test(self.hub.sharing.channels(self.user_id)))
            if self.user_id is not None:
                fcm_sent, fcm_failed = self.request.app.state.fcm.test(self.user_id)
                sent.extend(fcm_sent)
                failed.extend(fcm_failed)
            reply = {"ok": bool(sent) and not failed, "sent": sent, "failed": failed}
            if not sent and not failed:
                reply["error"] = "no push channel configured"
            return _json(reply)
        elif path == "/api/events/read":
            last = self.hub.db.last_event_id(self.user_id)
            through = body.get("through_id", last)
            if type(through) is not int or through < 0:
                return _json({"error": "through_id must be a whole number"}, 400)
            read = (store.raise_meta("events_read_id", min(through, last)) if self.user_id is None else
                    self.hub.sharing.mark_read(self.user_id, min(through, last)))
            return _json({"ok": True, "unread_alerts": self.hub.db.unread(read, self.user_id)})

    async def _onoff(self, req: dict) -> Response:
        try:
            mac = str(req["mac"]).upper()
            outlet = req["outlet"]
            on = req["on"]
            if not isinstance(on, bool) or not _is_outlet(outlet, 0):   # bool("false") is True, int(0.9) is "all": never guess
                raise ValueError("on must be true/false, outlet a whole number 0-4")
        except Exception:
            return _json({"error": "bad request"}, 400)
        s = self.hub.session(mac)
        if not s:
            return _json({"error": "device offline"}, 503)
        channels = [1, 2, 3, 4] if outlet == 0 else [outlet]
        try:
            task = asyncio.create_task(s.set_outlets(channels, on))
            pending = self.request.app.state.command_tasks
            pending.add(task)

            def finished(done):
                pending.discard(done)
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(finished)
            # Future.result(timeout=10) left the command running after the old HTTP request timed out.
            confirmed = await asyncio.wait_for(asyncio.shield(task), timeout=10)
        except Exception as err:
            self._audit("onoff", mac, outlet=outlet, on=on, confirmed=False)
            return _json({"error": f"command sent, outcome unknown: {err!r}"}, 502)
        # ok = commands sent; confirmed = a fresh snapshot shows every requested outlet in the wanted state
        self._audit("onoff", mac, outlet=outlet, on=on, confirmed=bool(confirmed))
        return _json({"ok": True, "confirmed": bool(confirmed)})

    async def dispatch(self) -> Response:
        path, method = urlparse(self.path).path, self.request.method
        is_api = path == '/api' or path.startswith('/api/')
        public_get = method == 'GET' and (path in PUBLIC_GET or (
            path.startswith('/fonts/') and path[7:] in self.request.app.state.fonts))
        if not public_get and not (method == 'POST' and path in PUBLIC_AUTH):
            await asyncio.to_thread(self._resolve_auth)
        reservation = None
        response = None
        try:
            if is_api:
                name = 'api'
                identity = 'user:' + str(self.user_id) if self.user_id is not None else 'ip:' + self.ip
                if method == 'POST' and path in PUBLIC_AUTH:
                    name, identity = path.rsplit('/', 1)[1], self.ip
                elif self.user_id is not None and method == 'POST' and path == '/api/strips/claim':
                    name = 'claim'
                elif self.user_id is not None and method in ('POST', 'PUT', 'DELETE') and re.fullmatch(
                        r'/api/strips/[^/]+/access(?:/[0-9]+)?', path):
                    name = 'access'
                elif self.user_id is not None and method in ('POST', 'DELETE') and (
                        path == '/api/me/push-tokens' or path.startswith('/api/me/push-tokens/')):
                    name = 'push_tokens'
                reservation = self.limiter.take(name, identity)
            response = await self._dispatch()
            return response
        except RateLimited as err:
            if self.limiter.sample(err.key):
                await asyncio.to_thread(self.audit.record, 'rate_limit', self.user_id, self.ip,
                                        err.key[0], key_hash=token_hash(str(err.key)), retry_after=err.retry_after)
            response = _json({'error': 'too many requests'}, 429)
            response.headers['Retry-After'] = str(err.retry_after)
            return response
        finally:
            # Reserve before hashing to make concurrent registrations atomic;
            # only successful creations consume the hourly account allowance.
            if reservation and reservation[0][0] == 'register' and (response is None or response.status_code != 201):
                self.limiter.refund(reservation)

    async def _dispatch(self) -> Response:
        method = self.request.method
        path = urlparse(self.path).path
        rule_id = path[len("/api/rules/"):] if path.startswith("/api/rules/") else None
        font = path.startswith("/fonts/") and path[7:] in self.request.app.state.fonts
        public = (method == "GET" and (path in PUBLIC_GET or font)) or (method == "POST" and path in PUBLIC_AUTH)
        if not public and not self.auth_method:
            return self._deny()
        auth_route = (method == "GET" and path in AUTH_GET) or (method == "POST" and path in AUTH_POST) or (
            method == "DELETE" and path.startswith("/api/auth/sessions/") and bool(path[len("/api/auth/sessions/"):]))
        try:
            if self.auth_method == "cookie" and method != "GET":
                self._csrf()
            if auth_route:
                body = {} if method in ("GET", "DELETE") else await self._body()
                if isinstance(body, Response):
                    return body
                try:
                    return await asyncio.to_thread(self._auth, method, path, body)
                finally:
                    # Includes refresh replay revocation; no changes to Sessions required.
                    await asyncio.to_thread(self.request.app.state.push_tokens.purge_revoked)
                    await self.request.app.state.live.recheck()
        except AuthError as err:
            return _json({"error": str(err)}, err.status)
        policy = self._route_policy(method, path, font)
        if policy is None:
            return _json({"error": "not found"}, 404)
        body = {} if method in ("GET", "DELETE") else await self._body()
        if isinstance(body, Response):
            return body

        def handle():
            self._authorize(policy, path, body)
            if self.strip_mac:
                return self._strip(method, body)
            if path == "/api/me/notifications":
                return self._notifications(method, body)
            if path == '/api/me/push-tokens' or path.startswith('/api/me/push-tokens/'):
                return self._push_tokens(method, path, body)
            if path.startswith("/api/strips/claim/"):
                return _json(self.hub.sharing.claim_status(self.user_id, path[len("/api/strips/claim/"):]))
            return self._get(path) if method == "GET" else self._write(method, path, rule_id, body)

        try:
            if path in ("/api/onoff", "/api/strips/claim"):
                await asyncio.to_thread(self._authorize, policy, path, body)
                # Online check and claim creation share the TCP event loop (no await between them).
                return self._claim(body) if path.endswith("/claim") else await self._onoff(body)
            # File/SQLite writes and notification HTTP calls must not stall TCP or rule execution.
            return await asyncio.to_thread(handle)
        except AuthError as err:
            return _json({"error": str(err)}, err.status)
        except ValueError as err:
            return _json({"error": str(err)}, 400)


class SecureFastAPI(FastAPI):
    async def __call__(self, scope, receive, send):
        await SecurityHeaders(super().__call__)(scope, receive, send)


def create_app(hub: Hub, engine: Engine | None = None, *, local_ip: str = "127.0.0.1",
               port: int = DEVICE_PORT, token: str = "", apk: str | Path | None = None,
               secure_cookies: bool = False, open_registration: bool = True,
               trusted_proxies=(), rate_limiter=None, fcm_service_account=None, fcm_http=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await app.state.live.close()
            await asyncio.to_thread(app.state.fcm.close)

    app = SecureFastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False, lifespan=lifespan)
    app.state.hub, app.state.engine = hub, engine if engine is not None else Engine(hub)
    hub.legacy_notifications = bool(token)
    app.state.local_ip, app.state.port, app.state.token = local_ip, port, token
    app.state.accounts = Accounts(hub.db)
    app.state.push_tokens = PushTokens(hub.db)
    app.state.push_tokens.purge_revoked()
    app.state.fcm = FCM(app.state.push_tokens, fcm_service_account, **({'http': fcm_http} if fcm_http else {}))
    hub.fcm = app.state.fcm
    app.state.trusted_proxies = parse_trusted_proxies(trusted_proxies)
    app.state.rate_limiter = rate_limiter if rate_limiter is not None else RateLimiter()
    app.state.secure_cookies, app.state.open_registration = secure_cookies, open_registration
    app.state.apk = Path(apk).resolve() if apk is not None else DEFAULT_APK
    app.state.page = (WEB_ROOT / "index.html").read_bytes()
    app.state.assets = {}
    for name, ctype in (('app.js', 'text/javascript; charset=utf-8'), ('app.css', 'text/css; charset=utf-8')):
        body = (WEB_ROOT / name).read_bytes()
        app.state.assets['/' + name] = (body, ctype, '"' + hashlib.sha256(body).hexdigest() + '"')
    app.state.fonts = {p.name: p.read_bytes() for p in (WEB_ROOT / "fonts").glob("*.woff2")}
    app.state.command_tasks = set()
    app.state.live = LiveUpdates(app.state)

    @app.websocket('/api/ws')
    async def websocket(ws: WebSocket):
        await app.state.live.handle(ws)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        return _json({"error": "not found"}, 404)

    # Request-only dispatch avoids coercion, automatic 422s, redirects and method-specific 405s.
    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "CONNECT"])
    async def dispatch(request: Request) -> Response:
        return await _Web(request).dispatch()

    return app
