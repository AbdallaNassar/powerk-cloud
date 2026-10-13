import asyncio
import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import pytest

from powerk import api

MAC = "AABBCCDDEEFF"
TOKEN = "token /+?value"


def basic(user, password):
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@pytest.mark.parametrize("path", ["/api/state", "/", "/index.html", "/fonts/Kalam-700-latin.woff2"])
@pytest.mark.parametrize("auth", ["none", "header", "cookie", "basic_user", "basic_password", "query"])
def test_auth_matrix(client_factory, path, auth):
    with client_factory(token="" if auth == "none" else TOKEN) as (_, client):
        headers = {}
        if auth == "header":
            headers["X-Token"] = TOKEN
        elif auth == "cookie":
            headers["Cookie"] = "powerk_t=" + quote(TOKEN)
        elif auth == "basic_user":
            headers["Authorization"] = basic(TOKEN, "unused")
        elif auth == "basic_password":
            headers["Authorization"] = basic("powerk", TOKEN)
        if auth == "query":
            path += "?t=" + quote(TOKEN)
        response = client.get(path, headers=headers)
        if auth == "none" and path == "/api/state":
            assert response.status_code == 401
            return
        assert response.status_code == 200
        assert int(response.headers["content-length"]) == len(response.content)
        if path.split("?")[0] in ("/", "/index.html"):
            if auth == "none":
                assert "set-cookie" not in response.headers
            else:
                assert response.headers["set-cookie"] == f"powerk_t={quote(TOKEN)}; Path=/; HttpOnly; SameSite=Strict"
                assert client.get("/api/state").status_code == 200


@pytest.mark.parametrize("headers", [
    {}, {"X-Token": "wrong"}, {"Cookie": "powerk_t=wrong"},
    {"Authorization": basic("wrong", "wrong")}, {"Authorization": "Basic !!!!"},
    {"Authorization": "Basic /w=="}, {"Cookie": "bad cookie; powerk_t=wrong"},
])
@pytest.mark.parametrize("path", ["/api/state?t=wrong"])
def test_auth_denied_exactly(client_factory, headers, path):
    with client_factory(token=TOKEN) as (_, client):
        response = client.get(path, headers=headers)
        assert response.status_code == 401
        is_api = path.startswith("/api/")
        assert response.content == (b'{"error": "token required"}' if is_api else b"powerk: token required\n")
        assert response.headers["www-authenticate"] == 'Basic realm="powerk"'
        assert response.headers["content-type"] == ("application/json" if is_api else "text/plain")
        assert "cache-control" not in response.headers  # _deny() never added it.
        assert int(response.headers["content-length"]) == len(response.content)


def test_auth_precedence_and_first_query_value(client_factory):
    with client_factory(token=TOKEN) as (_, client):
        query = "/api/state?t=" + quote(TOKEN)
        assert client.get(query, headers={"X-Token": "wrong"}).status_code == 200
        assert client.get(query, headers={"Authorization": "Basic /w=="}).status_code == 401
        assert client.get(query, headers={"Authorization": "Basic /w==", "X-Token": TOKEN}).status_code == 200
        assert client.get("/api/state?t=wrong&t=" + quote(TOKEN)).status_code == 401


@pytest.mark.parametrize("path,content_type,body", [
    ("/nope", "text/plain", b"powerk: token required\n"),
    ("/api/nope", "application/json", b'{"error": "token required"}'),
])
def test_unknown_get_auth_before_routing(client_factory, path, content_type, body):
    with client_factory(token=TOKEN) as (_, client):
        response = client.get(path)
        assert response.status_code == 401
        assert response.content == body
        assert response.headers["content-type"] == content_type
        assert response.headers["www-authenticate"] == 'Basic realm="powerk"'
        assert int(response.headers["content-length"]) == len(body)
        assert "cache-control" not in response.headers

        response = client.get(path, headers={"X-Token": TOKEN})
        assert response.status_code == 404
        assert response.content == b'{"error": "not found"}'
        assert response.headers["content-type"] == "application/json"
        assert response.headers["cache-control"] == "no-store"
        assert "www-authenticate" not in response.headers


@pytest.mark.parametrize("method,path", [
    ("GET", "/missing"), ("GET", "/api/missing"), ("GET", "/api/onoff"),
    ("GET", "/api/state/"), ("GET", "/api/%73tate"), ("GET", "/api/rules/abc"),
    ("GET", "/fonts/missing.woff2"), ("GET", "/docs"), ("GET", "/redoc"),
    ("GET", "/openapi.json"), ("POST", "/api/state"), ("PUT", "/api/name"),
    ("DELETE", "/api/rules"), ("PUT", "/api/rules/"), ("PATCH", "/api/settings"),
    ("OPTIONS", "/api/state"), ("TRACE", "/"), ("HEAD", "/api/state"),
    ("PROPFIND", "/api/state"), ("POST", "/powerk.py"),
])
def test_unknown_and_wrong_methods_are_404(client_factory, method, path):
    with client_factory() as (_, client):
        response = client.request(method, path)
        assert response.status_code == 404
        if method != "HEAD":
            assert response.content == b'{"error": "not found"}'
        assert response.headers["content-type"] == "application/json"
        assert response.headers["cache-control"] == "no-store"
        assert "allow" not in response.headers


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded"])
def test_writes_require_json(client_factory, content_type):
    with client_factory() as (_, client):
        headers = {} if content_type is None else {"Content-Type": content_type}
        response = client.post("/api/alerts/test", content=b"{}", headers=headers)
        assert response.status_code == 415
        assert response.content == b'{"error": "Content-Type must be application/json"}'
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("body", [b"[]", b"null", b"true", b"4", b'"string"', b"{", b"\xff", b" " * 16385])
def test_invalid_and_oversized_bodies(client_factory, body):
    with client_factory() as (_, client):
        response = client.post("/api/alerts/test", content=body, headers={"Content-Type": "application/json"})
        assert response.status_code == 400
        assert response.content == b'{"error": "bad request"}'


def test_body_size_boundary_empty_and_chunked(client_factory):
    with client_factory() as (_, client):
        headers = {"Content-Type": "Application/JSON; charset=utf-8"}
        for body in (b"", b'{"padding":"' + b" " * (16384 - 14) + b'"}'):
            assert client.post("/api/alerts/test", content=body, headers=headers).status_code == 200
        response = client.post("/api/alerts/test", content=iter([b" " * 8192, b" " * 8193]), headers=headers)
        assert response.status_code == 400
        assert response.json() == {"error": "bad request"}
        for length in ("16385", "-1", "nope"):
            response = client.post("/api/alerts/test", content=b"{}", headers={**headers, "Content-Length": length})
            assert response.status_code == 400


def test_auth_before_body_validation(client_factory):
    with client_factory(token=TOKEN) as (_, client):
        response = client.post("/api/onoff", content="invalid")
        assert response.status_code == 401
        assert response.json() == {"error": "token required"}


def test_every_api_route_happy_path(client_factory):
    with client_factory(connected=True) as (env, client):
        state = client.get("/api/state")
        assert state.status_code == 200
        assert state.headers["cache-control"] == "no-store"
        state = state.json()
        assert state["api_version"] == 2 and state["port"] == 10086 and state["local_ip"] == "192.0.2.1"
        assert state["devices"][0]["mac"] == MAC and state["devices"][0]["online"] is True

        response = client.post("/api/onoff", json={"mac": MAC.lower(), "outlet": 0, "on": True})
        assert response.status_code == 200 and response.json() == {"ok": True, "confirmed": True}
        assert env.state_on == {1, 2, 3, 4}
        assert [c for c in env.commands if c.startswith("up:onoff:")] == [f"up:onoff:{n}:on" for n in range(1, 5)]
        assert client.post("/api/name", json={"mac": MAC, "outlet": 0, "name": " Desk "}).json() == {"ok": True}
        assert client.post("/api/name", json={"mac": MAC, "outlet": 3, "name": "Fridge"}).json() == {"ok": True}
        assert client.get("/api/state").json()["devices"][0]["label"] == "Desk"

        response = client.post("/api/rules", json={"mac": MAC, "outlets": [0], "kind": "cycle", "on_min": 2, "off_min": 3})
        assert response.status_code == 200
        rule = response.json()["rule"]
        assert rule["outlets"] == [1, 2, 3, 4] and rule["next_at"] is None and rule["phase"] is None
        assert client.get("/api/rules?mac=" + MAC.lower()).json() == {"rules": [rule]}
        assert client.get("/api/rules?mac=unknown").json() == {"rules": []}
        env.engine.rt[rule["id"]] = {"phase": "on", "next_at": 42}
        response = client.put("/api/rules/" + rule["id"], json={"enabled": False})
        assert response.status_code == 200 and response.json()["rule"]["enabled"] is False
        assert rule["id"] not in env.engine.rt
        assert client.delete("/api/rules/" + rule["id"]).json() == {"ok": True}
        assert client.get("/api/rules").json() == {"rules": []}

        env.hub.db.add_energy(MAC, 1, 520, state["server_time"])
        response = client.get("/api/history", params={"mac": MAC, "range": "day", "outlet": 1})
        assert response.status_code == 200
        history = response.json()
        assert history["total_kwh"] == 0.52 and len(history["buckets"]) == 24 and history["currency"] == "EGP"
        assert client.get("/api/settings").json()["telegram_configured"] is False
        settings = client.put("/api/settings", json={"currency": "USD", "price_kwh": 3, "telegram_token": "secret"})
        assert settings.status_code == 200 and settings.json()["telegram_configured"] is True
        assert "telegram_token" not in settings.json()
        assert client.get("/api/settings").json() == settings.json()

        env.hub.event("warn", "offline", "test offline", MAC)
        response = client.get("/api/events?limit=50")
        assert response.status_code == 200 and response.json()["unread_alerts"] == 1
        event_id = response.json()["events"][0]["id"]
        response = client.post("/api/events/read", json={"through_id": event_id})
        assert response.json() == {"ok": True, "unread_alerts": 0}
        assert client.post("/api/events/read", json={}).json() == {"ok": True, "unread_alerts": 0}
        earlier = client.get("/api/events?before_id=" + str(event_id)).json()["events"]
        assert earlier and all(e["level"] == "info" and e["params"]["actor"] == "legacy" for e in earlier)
        response = client.get("/api/debug")
        assert response.status_code == 200 and response.json()["devices"][0]["last_getinfo"].startswith("up:getinfo:")
        response = client.post("/api/alerts/test", json={})
        assert response.status_code == 200
        assert response.json() == {"ok": False, "sent": [], "failed": [], "error": "no push channel configured"}
        env.hub.notifier.test = lambda: (["ntfy"], [])
        assert client.post("/api/alerts/test", json={}).json() == {"ok": True, "sent": ["ntfy"], "failed": []}


def test_notifier_does_not_block_http_or_tcp(client_factory):
    entered, release = threading.Event(), threading.Event()
    with client_factory(connected=True) as (env, client):
        def slow_test():
            entered.set()
            assert release.wait(5)
            return ["ntfy"], []
        env.hub.notifier.test = slow_test
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(client.post, "/api/alerts/test", json={})
            try:
                assert entered.wait(2)
                response = pool.submit(client.get, "/api/state").result(timeout=2)
                assert response.status_code == 200
                assert pool.submit(client.portal.call, env.sess.refresh, 1).result(timeout=2) is True
            finally:
                release.set()
            assert pending.result(timeout=2).json()["sent"] == ["ntfy"]


def test_onoff_uses_device_loop_and_reports_errors(client_factory):
    with client_factory(connected=True) as (env, client):
        device_loop = client.portal.call(asyncio.get_running_loop)
        original = env.sess.set_outlets
        async def checked(channels, on):
            assert asyncio.get_running_loop() is device_loop
            return await original(channels, on)
        env.sess.set_outlets = checked
        assert client.post("/api/onoff", json={"mac": MAC, "outlet": 2, "on": False}).json()["confirmed"] is True
        async def unconfirmed(*args):
            return False
        env.sess.set_outlets = unconfirmed
        assert client.post("/api/onoff", json={"mac": MAC, "outlet": 2, "on": True}).json() == {"ok": True, "confirmed": False}
        async def broken(*args):
            raise OSError("broken")
        env.sess.set_outlets = broken
        response = client.post("/api/onoff", json={"mac": MAC, "outlet": 2, "on": True})
        assert response.status_code == 502
        assert response.json() == {"error": "command sent, outcome unknown: OSError('broken')"}
    with client_factory() as (_, client):
        response = client.post("/api/onoff", json={"mac": MAC, "outlet": 2, "on": True})
        assert response.status_code == 503 and response.json() == {"error": "device offline"}


def test_onoff_timeout_does_not_cancel_command(client_factory, monkeypatch):
    with client_factory(connected=True) as (env, client):
        release = asyncio.Event()
        finished = threading.Event()
        async def slow_switch(*args):
            await release.wait()
            finished.set()
            return True
        env.sess.set_outlets = slow_switch
        wait_for = asyncio.wait_for
        async def short_wait(awaitable, timeout):
            assert timeout == 10
            return await wait_for(awaitable, 0.02)
        monkeypatch.setattr(api.asyncio, "wait_for", short_wait)
        response = client.post("/api/onoff", json={"mac": MAC, "outlet": 1, "on": True})
        assert response.status_code == 502
        assert response.json() == {"error": "command sent, outcome unknown: TimeoutError()"}
        assert len(client.app.state.command_tasks) == 1
        client.portal.call(release.set)
        assert finished.wait(1)
