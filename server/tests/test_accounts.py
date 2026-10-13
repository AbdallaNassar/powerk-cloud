"""Account/session contracts over HTTP with the real SQLite and Argon2 implementations."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from argon2 import PasswordHasher

PHONE = "+201001234567"
PASSWORD = "a quiet river at dawn"
WEB = {"X-Powerk-Client": "web"}


def register(client, phone=PHONE, password=PASSWORD, **kwargs):
    response = client.post("/api/auth/register", json={"phone": phone, "password": password}, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def login(client, phone=PHONE, password=PASSWORD, **kwargs):
    response = client.post("/api/auth/login", json={"phone": phone, "password": password}, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def bearer(pair):
    return {"Authorization": "Bearer " + pair["access_token"]}


def csrf(client):
    return {"X-CSRF-Token": client.cookies["powerk_csrf"]}


@pytest.mark.parametrize("phone,normalized", [
    ("01001234567", PHONE), ("(010) 0123-4567", PHONE),
    ("+20 (100) 123-4567", PHONE), ("+12345678", "+12345678"),
    ("+123456789012345", "+123456789012345"),
])
def test_phone_normalization(client_factory, phone, normalized):
    with client_factory(token="") as (_, client):
        assert register(client, phone)["user"]["phone"] == normalized


@pytest.mark.parametrize("phone", [
    "", "1001234567", "02001234567", "0100123456", "010012345678", "201001234567",
    "+1234567", "+1234567890123456", "+012345678", "+20/1001234567",
    "+20.1001234567", "+٢٠١٠٠١٢٣٤٥٦٧", "+20\n1001234567", True, None, 1001234567,
])
def test_invalid_phones_are_400(client_factory, phone):
    with client_factory(token="") as (_, client):
        for endpoint in ("register", "login"):
            r = client.post("/api/auth/" + endpoint, json={"phone": phone, "password": PASSWORD})
            assert r.status_code == 400 and set(r.json()) == {"error"}


@pytest.mark.parametrize("password", [
    "123456789", "x" * 129, "password123", "PASSWORD123", "1234567890", "qwertyuiop",
    "201001234567", "01001234567", "+201001234567", None, True, 1234567890,
])
def test_password_policy(client_factory, password):
    with client_factory(token="") as (_, client):
        r = client.post("/api/auth/register", json={"phone": PHONE, "password": password})
        assert r.status_code == 400 and set(r.json()) == {"error"}


@pytest.mark.parametrize("password", ["river-fold", "x" * 128, "كلمة سر طويلة ومختلفة"])
def test_password_policy_boundaries(client_factory, password):
    with client_factory(token="") as (_, client):
        register(client, password=password)
        login(client, password=password)


def test_register_login_refresh_logout_and_hash_only_storage(client_factory):
    with client_factory(token="") as (env, client):
        first = register(client)
        assert first["expires_in"] == 900
        assert set(first["user"]) == {"id", "phone", "created_at"}
        assert len(first["access_token"]) >= 43 and len(first["refresh_token"]) >= 43
        assert first["access_token"] != first["refresh_token"]
        assert not client.cookies
        assert client.get("/api/auth/me", headers=bearer(first)).json() == {"user": first["user"]}
        assert client.get("/api/state", headers=bearer(first)).status_code == 200
        duplicate = client.post("/api/auth/register", json={"phone": "01001234567", "password": PASSWORD})
        assert duplicate.status_code == 409 and duplicate.json() == {"error": "phone already registered"}
        second = login(client)
        r = client.post("/api/auth/refresh", json={"refresh_token": second["refresh_token"]})
        assert r.status_code == 200
        fresh = r.json()
        assert fresh["user"] == first["user"] and fresh["expires_in"] == 900
        assert fresh["access_token"] != second["access_token"]
        assert fresh["refresh_token"] != second["refresh_token"]
        with env.hub.db.lock:
            dump = "\n".join(env.hub.db.conn.iterdump())
            encoded = env.hub.db.conn.execute("SELECT password_hash FROM users").fetchone()[0]
        assert encoded.startswith("$argon2id$") and PasswordHasher().verify(encoded, PASSWORD)
        for pair in (first, second, fresh):
            for key in ("access_token", "refresh_token"):
                assert pair[key] not in dump
                assert hashlib.sha256(pair[key].encode()).hexdigest() in dump
        assert PASSWORD not in dump
        assert client.post("/api/auth/logout", json={}, headers=bearer(fresh)).json() == {"ok": True}
        assert client.get("/api/state", headers=bearer(fresh)).status_code == 401
        assert client.get("/api/state", headers=bearer(second)).status_code == 401
        assert client.post("/api/auth/refresh", json={"refresh_token": fresh["refresh_token"]}).status_code == 401
        assert client.get("/api/state", headers=bearer(first)).status_code == 200


def test_refresh_reuse_revokes_only_that_family(client_factory, monkeypatch):
    from powerk import sessions
    clock = [1800000000]
    monkeypatch.setattr(sessions, "now", lambda: clock[0])
    with client_factory(token="") as (_, client):
        first = register(client)
        other = login(client)
        rotated = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]}).json()
        clock[0] += 60
        replay = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert replay.status_code == 401
        for pair in (first, rotated):
            assert client.get("/api/auth/me", headers=bearer(pair)).status_code == 401
            assert client.post("/api/auth/refresh", json={"refresh_token": pair["refresh_token"]}).status_code == 401
        assert client.get("/api/auth/me", headers=bearer(other)).status_code == 200


def test_concurrent_refresh_has_only_one_live_chain(client_factory):
    with client_factory(token="") as (env, client):
        pair = register(client)
        barrier = Barrier(2)
        def rotate():
            barrier.wait(timeout=5)
            return client.post("/api/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(rotate) for _ in range(2)]
            responses = [r.result() for r in requests]
        assert [r.status_code for r in responses] == [200, 200]
        pairs = [r.json() for r in responses]
        service = client.app.state.accounts.sessions
        assert len({service.resolve(p["access_token"]).family_id for p in pairs}) == 1
        live = env.hub.db.conn.execute("SELECT token_hash FROM refresh_tokens WHERE used_at IS NULL").fetchall()
        assert len(live) == 1
        winner = next(p for p in pairs if hashlib.sha256(p["refresh_token"].encode()).hexdigest() == live[0][0])
        assert client.post("/api/auth/refresh", json={"refresh_token": winner["refresh_token"]}).status_code == 200
        assert env.hub.db.conn.execute("SELECT count(*) FROM audit_log WHERE action='refresh_grace'").fetchone()[0] == 1


def test_token_expiry_and_token_types(client_factory, monkeypatch):
    from powerk import sessions
    clock = [1800000000]
    monkeypatch.setattr(sessions, "now", lambda: clock[0])
    with client_factory(token="") as (_, client):
        pair = register(client)
        assert client.get("/api/state", headers={"Authorization": "Bearer " + pair["refresh_token"]}).status_code == 401
        assert client.post("/api/auth/refresh", json={"refresh_token": pair["access_token"]}).status_code == 401
        clock[0] += 899
        assert client.get("/api/auth/me", headers=bearer(pair)).status_code == 200
        clock[0] += 1
        assert client.get("/api/auth/me", headers=bearer(pair)).status_code == 401
        clock[0] = 1800000000 + 30 * 86400
        assert client.post("/api/auth/refresh", json={"refresh_token": pair["refresh_token"]}).status_code == 401


def test_password_change_revokes_other_families(client_factory):
    with client_factory(token="") as (_, client):
        current, other = register(client), login(client)
        endpoint = "/api/auth/password"
        assert client.post(endpoint, headers=bearer(current), json={"current_password": "wrong pass!", "new_password": "another quiet river"}).status_code == 401
        assert client.post(endpoint, headers=bearer(current), json={"current_password": PASSWORD, "new_password": "password123"}).status_code == 400
        assert client.get("/api/auth/me", headers=bearer(other)).status_code == 200
        assert client.post(endpoint, headers=bearer(current), json={"current_password": PASSWORD, "new_password": "another quiet river"}).json() == {"ok": True}
        assert client.get("/api/auth/me", headers=bearer(current)).status_code == 200
        assert client.get("/api/auth/me", headers=bearer(other)).status_code == 401
        assert client.post("/api/auth/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 401
        assert client.post("/api/auth/refresh", json={"refresh_token": current["refresh_token"]}).status_code == 200
        assert client.post("/api/auth/login", json={"phone": PHONE, "password": PASSWORD}).status_code == 401
        login(client, password="another quiet river")


def test_sessions_list_and_delete_ownership(client_factory):
    with client_factory(token="") as (_, client):
        first = register(client, headers={"User-Agent": "phone one"})
        second = login(client, headers={"User-Agent": "phone two"})
        stranger = register(client, "+201112345678")
        listing = client.get("/api/auth/sessions", headers=bearer(first)).json()["sessions"]
        assert len(listing) == 2
        assert all(set(s) == {"id", "created_at", "last_used_at", "user_agent", "ip", "current"} for s in listing)
        assert all(s["ip"] == "testclient" for s in listing)
        current = next(s for s in listing if s["current"])
        other = next(s for s in listing if not s["current"])
        assert current["user_agent"] == "phone one" and other["user_agent"] == "phone two"
        path = "/api/auth/sessions/" + other["id"]
        assert client.delete(path, headers=bearer(stranger)).status_code == 404
        assert client.get("/api/auth/me", headers=bearer(second)).status_code == 200
        assert client.delete(path, headers=bearer(first)).json() == {"ok": True}
        assert client.get("/api/auth/me", headers=bearer(second)).status_code == 401
        assert client.delete(path, headers=bearer(first)).status_code == 404
        assert len(client.get("/api/auth/sessions", headers=bearer(first)).json()["sessions"]) == 1
        assert client.delete("/api/auth/sessions/" + current["id"], headers=bearer(first)).status_code == 200
        assert client.get("/api/auth/me", headers=bearer(first)).status_code == 401


@pytest.mark.parametrize("secure", [False, True])
def test_web_cookies_csrf_refresh_and_logout(client_factory, secure):
    with client_factory(token="", secure_cookies=secure) as (_, client):
        if secure:
            client.base_url = "https://testserver"
        response = client.post("/api/auth/register", json={"phone": PHONE, "password": PASSWORD}, headers=WEB)
        assert response.status_code == 201
        assert set(response.json()) == {"user", "expires_in"}
        cookies = response.headers.get_list("set-cookie")
        assert len(cookies) == 3
        for name, path, age in [("powerk_access", "/", 900), ("powerk_refresh", "/api/auth/", 2592000), ("powerk_csrf", "/", 2592000)]:
            value = next(c for c in cookies if c.startswith(name + "="))
            assert f"Path={path}" in value and f"Max-Age={age}" in value
            assert "samesite=strict" in value.lower()
            assert ("HttpOnly" in value) == (name != "powerk_csrf")
            assert ("Secure" in value) == secure
        assert client.get("/api/auth/me").status_code == 200
        assert client.put("/api/settings", json={"currency": "USD"}).status_code == 403
        assert client.put("/api/settings", json={}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
        assert client.put("/api/settings", json={}, headers={"X-CSRF-Token": "غير صحيح".encode("utf-8")}).status_code == 403
        assert client.put("/api/settings", json={"currency": "USD"}, headers=csrf(client)).status_code == 410
        assert client.put("/api/me/notifications", json={}, headers=csrf(client)).status_code == 200
        assert client.put("/api/settings", content="{}", headers=csrf(client)).status_code == 415
        before = client.cookies["powerk_refresh"]
        assert client.post("/api/auth/refresh", json={}).status_code == 403
        # Invalid Bearer headers cannot turn an ambient cookie into CSRF-free authorization.
        assert client.post("/api/auth/refresh", json={}, headers={"Authorization": "Bearer invalid"}).status_code in (401, 403)
        client.cookies.delete("powerk_access")
        r = client.post("/api/auth/refresh", json={}, headers=csrf(client))
        assert r.status_code == 200 and set(r.json()) == {"user", "expires_in"}
        assert client.cookies["powerk_refresh"] != before
        family = client.get("/api/auth/sessions").json()["sessions"][0]["id"]
        assert client.delete("/api/auth/sessions/" + family).status_code == 403
        assert client.post("/api/auth/logout", json={}, headers=csrf(client)).status_code == 200
        assert not client.cookies
        assert client.get("/api/state").status_code == 401


def test_bearer_writes_skip_csrf_even_with_stale_cookies(client_factory):
    with client_factory(token="") as (_, client):
        pair = register(client)
        client.cookies.set("powerk_access", "stale")
        assert client.put("/api/settings", json={}, headers=bearer(pair)).status_code == 410
        assert client.put("/api/me/notifications", json={}, headers=bearer(pair)).status_code == 200
        assert client.put("/api/settings", json={}, headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_unknown_phone_uses_dummy_hash_and_same_login_error(client_factory, monkeypatch):
    from powerk.accounts import DUMMY_HASH
    checked = []
    verify = PasswordHasher.verify
    def observed(self, encoded, password):
        checked.append(encoded)
        return verify(self, encoded, password)
    with client_factory(token="") as (_, client):
        register(client)
        monkeypatch.setattr(PasswordHasher, "verify", observed)
        unknown = client.post("/api/auth/login", json={"phone": "+201112345678", "password": PASSWORD})
        assert checked == [DUMMY_HASH]
        wrong = client.post("/api/auth/login", json={"phone": PHONE, "password": "a wrong password"})
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json() == {"error": "wrong phone or password"}


def test_login_rehashes_and_data_survives_reopening(client_factory):
    from powerk.api import create_app
    from powerk.devices import Hub
    from powerk.store import Db, Store
    from fastapi.testclient import TestClient
    with client_factory(token="") as (env, client):
        pair = register(client)
        old = PasswordHasher(time_cost=1).hash(PASSWORD)
        with env.hub.db.lock, env.hub.db.conn:
            env.hub.db.conn.execute("UPDATE users SET password_hash=?", (old,))
        login(client)
        with env.hub.db.lock:
            encoded = env.hub.db.conn.execute("SELECT password_hash FROM users").fetchone()[0]
        assert encoded != old and not PasswordHasher().check_needs_rehash(encoded)
        db = Db(str(env.data / "powerk.db"))
        try:
            with TestClient(create_app(Hub(Store(env.data / "powerk.json"), db))) as reopened:
                assert reopened.get("/api/auth/me", headers=bearer(pair)).status_code == 200
        finally:
            db.conn.close()


def test_legacy_rollback_reads_and_writes_database_with_accounts(client_factory, legacy):
    with client_factory(token="") as (env, client):
        pair = register(client)
        before = env.hub.db.conn.execute("SELECT name, sql FROM sqlite_master WHERE name IN ('energy','events') ORDER BY name").fetchall()
        old = legacy.Db(str(env.data / "powerk.db"))
        try:
            old.add_energy("AABBCCDDEEFF", 1, 100, 1800000000)
            old.add_event({"ts": 1800000000, "level": "warn", "code": "offline", "mac": "AABBCCDDEEFF",
                           "outlet": None, "text": "offline", "params": {}})
            assert old._sum_wh("AABBCCDDEEFF", 0) == 100
            assert env.hub.db.events()[0]["code"] == "offline"
            assert before == old.conn.execute("SELECT name, sql FROM sqlite_master WHERE name IN ('energy','events') ORDER BY name").fetchall()
        finally:
            old.conn.close()
        assert client.get("/api/auth/me", headers=bearer(pair)).status_code == 200


def test_rotation_serializes_across_database_connections(client_factory):
    from powerk.sessions import AuthError, Sessions
    from powerk.store import Db
    with client_factory(token="") as (env, client):
        pair = register(client)
        other_db = Db(str(env.data / "powerk.db"))
        try:
            services = (client.app.state.accounts.sessions, Sessions(other_db))
            barrier = Barrier(2)
            def rotate(service):
                barrier.wait(timeout=5)
                try:
                    return service.refresh(pair["refresh_token"])
                except AuthError as error:
                    return error.status
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(rotate, services))
            assert all(isinstance(r, dict) for r in results)
            assert len({services[0].resolve(r["access_token"]).family_id for r in results}) == 1
            live = env.hub.db.conn.execute("SELECT token_hash FROM refresh_tokens WHERE used_at IS NULL").fetchall()
            assert len(live) == 1
            winner = next(r for r in results if hashlib.sha256(r["refresh_token"].encode()).hexdigest() == live[0][0])
            assert services[1].refresh(winner["refresh_token"])["user"] == pair["user"]
            assert env.hub.db.conn.execute("SELECT count(*) FROM audit_log WHERE action='refresh_grace'").fetchone()[0] == 1
        finally:
            other_db.conn.close()


def test_web_denial_uses_login_screen_without_basic_challenge(client_factory):
    with client_factory(token="secret") as (_, client):
        response = client.get("/api/state", headers=WEB)
        assert response.status_code == 401
        assert "www-authenticate" not in response.headers


def test_web_login_and_delete_current_session_clear_cookies(client_factory):
    with client_factory(token="") as (_, client):
        register(client)
        login(client, headers=WEB)
        listing = client.get("/api/auth/sessions").json()["sessions"]
        current = next(s for s in listing if s["current"])
        assert client.delete("/api/auth/sessions/" + current["id"], headers=csrf(client)).status_code == 200
        assert not client.cookies


def test_last_used_updates_on_access_and_refresh(client_factory, monkeypatch):
    from powerk import sessions
    clock = [1800000000]
    monkeypatch.setattr(sessions, "now", lambda: clock[0])
    with client_factory(token="") as (_, client):
        first = register(client)
        second = login(client)
        clock[0] += 30
        assert client.get("/api/state", headers=bearer(first)).status_code == 200
        clock[0] += 20
        rows = client.get("/api/auth/sessions", headers=bearer(second)).json()["sessions"]
        assert next(r for r in rows if not r["current"])["last_used_at"] == 1800000030
        assert client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 200
        rows = client.get("/api/auth/sessions", headers=bearer(second)).json()["sessions"]
        assert next(r for r in rows if not r["current"])["last_used_at"] == 1800000050


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/state"), ("GET", "/api/auth/me"), ("GET", "/api/auth/sessions"),
    ("GET", "/api/debug"), ("POST", "/api/name"), ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/password"), ("DELETE", "/api/auth/sessions/x"), ("GET", "/api/missing"),
])
def test_api_closed_without_session_or_legacy_token(client_factory, method, path):
    with client_factory(token="") as (_, client):
        r = client.request(method, path, json={})
        assert r.status_code == 401 and set(r.json()) == {"error"}


@pytest.mark.parametrize("token", ["", "legacy-secret"])
def test_public_page_does_not_leak_legacy_access(client_factory, tmp_path, token):
    apk = tmp_path / "demo.apk"
    apk.write_bytes(b"demo")
    with client_factory(token=token, apk=apk) as (_, client):
        for path in ("/", "/index.html", "/fonts/Kalam-700-latin.woff2", "/powerk.py", "/powerk.apk"):
            r = client.get(path)
            assert r.status_code == 200 and "set-cookie" not in r.headers
        assert client.get("/api/state").status_code == 401


def test_closed_registration_and_manual_validation(client_factory):
    with client_factory(token="", open_registration=False) as (_, client):
        r = client.post("/api/auth/register", json={"phone": PHONE, "password": PASSWORD})
        assert r.status_code == 403 and r.json() == {"error": "registration is closed"}
        assert client.post("/api/auth/login", json={"phone": PHONE, "password": PASSWORD}).status_code == 401
    with client_factory(token="") as (_, client):
        for path in ("register", "login", "refresh"):
            url = "/api/auth/" + path
            assert client.post(url, content="{}").status_code == 415
            assert client.post(url, json=[]).status_code == 400
            assert client.post(url, json={"phone": None, "password": False, "refresh_token": 123}).status_code == 400
