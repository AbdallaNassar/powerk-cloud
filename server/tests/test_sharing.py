"""Ownership boundaries, proof of possession and per-account data isolation."""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from powerk.devices import Device
from powerk.notify import Notifier
from powerk.rules import clean_rule
from powerk.store import Store

MAC = "AABBCCDDEEFF"
OTHER = "112233445566"
PHONES = {"owner": "+201000000001", "control": "+201000000002", "viewer": "+201000000003", "stranger": "+201000000004"}


def identities(env, client):
    """Password verification has separate coverage; use real account sessions here."""
    pairs = {}
    accounts = client.app.state.accounts
    with env.hub.db.lock, env.hub.db.conn:
        for role, phone in PHONES.items():
            uid = env.hub.db.conn.execute("INSERT INTO users(phone,password_hash,created_at) VALUES(?,?,?)",
                                          (phone, "unused", int(time.time()))).lastrowid
            pairs[role] = accounts.sessions.create_locked({"id": uid, "phone": phone, "created_at": int(time.time())}, "test", "127.0.0.1")
    return pairs


def headers(pairs, role):
    return {"X-Token": "fixture-token"} if role == "legacy" else {"Authorization": "Bearer " + pairs[role]["access_token"]}


def own(env, pairs, mac=MAC):
    sharing = env.hub.sharing
    claim = sharing.start_claim(pairs["owner"]["user"]["id"], mac)
    sharing.button(mac)
    assert sharing.claim_status(pairs["owner"]["user"]["id"], claim["claim_id"])["status"] == "done"
    sharing.share(mac, PHONES["control"], "control", pairs["owner"]["user"]["id"])
    sharing.share(mac, PHONES["viewer"], "viewer", pairs["owner"]["user"]["id"])


# Every domain route: list routes are filtered, strip routes require their declared role.
CASES = [
    ("GET", "/api/state", None, [200]*5),
    ("GET", "/api/debug", None, [200]*5),
    ("GET", "/api/history?mac={mac}", None, [200,200,200,404,200]),
    ("GET", "/api/rules", None, [200]*5),
    ("GET", "/api/rules?mac={mac}", None, [200,200,200,404,200]),
    ("POST", "/api/onoff", {"mac": MAC, "outlet": 1, "on": True}, [200,200,403,404,200]),
    ("POST", "/api/name", {"mac": MAC, "outlet": 0, "name": "Desk"}, [200,200,403,404,200]),
    ("POST", "/api/rules", {"mac": MAC, "kind": "timer", "minutes": 2, "on": True, "outlets": [1]}, [200,200,403,404,200]),
    ("PUT", "/api/rules/{rule}", {"enabled": False}, [200,200,403,404,200]),
    ("DELETE", "/api/rules/{rule}", None, [200,200,403,404,200]),
    ("GET", "/api/strips/{mac}/settings", None, [200,200,200,404,200]),
    ("PUT", "/api/strips/{mac}/settings", {"price_kwh": 7}, [200,403,403,404,200]),
    ("GET", "/api/strips/{mac}/access", None, [200,403,403,404,200]),
    ("POST", "/api/strips/{mac}/access", {"phone": PHONES["stranger"], "role": "viewer"}, [200,403,403,404,200]),
    ("PUT", "/api/strips/{mac}/access/{target}", {"role": "control"}, [200,403,403,404,200]),
    ("DELETE", "/api/strips/{mac}/access/{target}", None, [200,403,403,404,200]),
    ("POST", "/api/strips/{mac}/transfer", {"phone": PHONES["viewer"]}, [200,403,403,404,200]),
    ("POST", "/api/strips/{mac}/leave", {}, [403,200,200,404,401]),
    ("DELETE", "/api/strips/{mac}", None, [200,403,403,404,200]),
    ("GET", "/api/settings", None, [410,410,410,410,200]),
    ("PUT", "/api/settings", {}, [410,410,410,410,200]),
    ("GET", "/api/me/notifications", None, [200,200,200,200,401]),
    ("PUT", "/api/me/notifications", {}, [200,200,200,200,401]),
    ("POST", "/api/alerts/test", {}, [200]*5),
    ("GET", "/api/events", None, [200]*5),
    ("GET", "/api/events?mac={mac}", None, [200,200,200,404,200]),
    ("POST", "/api/events/read", {}, [200]*5),
    ("POST", "/api/strips/claim", {"code": OTHER[-7:]}, [200,200,200,200,401]),
    ("GET", "/api/strips/claim/{claim}", None, [200,404,404,404,401]),
]


@pytest.mark.parametrize("role,index", [(r,i) for i,r in enumerate(["owner","control","viewer","stranger","legacy"])])
@pytest.mark.parametrize("method,path,body,statuses", CASES)
def test_permission_matrix(client_factory, role, index, method, path, body, statuses):
    with client_factory() as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        async def switch(*_):
            return True
        for mac in (MAC, OTHER):
            d = Device(mac, "lgutap", "1", "127.0.0.1")
            d.online = True
            env.hub.devices[mac] = d
            env.hub.sessions[mac] = SimpleNamespace(device=d, writer=SimpleNamespace(is_closing=lambda: False), set_outlets=switch)
        rule = clean_rule({"mac": MAC, "kind": "timer", "outlets": [1], "minutes": 2, "on": True}, time.time())
        env.store.put_rule(rule)
        claim = env.hub.sharing.start_claim(pairs["owner"]["user"]["id"], "123456789ABC")
        path = path.format(mac=MAC, rule=rule["id"], target=pairs["viewer"]["user"]["id"], claim=claim["claim_id"])
        response = client.request(method, path, json=body, headers=headers(pairs, role))
        assert response.status_code == statuses[index], response.text
        if response.status_code == 403:
            assert response.json() == {"error": "forbidden"}
        if response.status_code == 404 and "claim/" not in path:
            assert response.json() == {"error": "unknown strip"}
        if role == "stranger" and method == "GET" and path in ("/api/state", "/api/debug", "/api/rules", "/api/events"):
            key = {"/api/state":"devices", "/api/debug":"devices", "/api/rules":"rules", "/api/events":"events"}[path]
            assert response.json()[key] == []


def test_claim_real_button_and_private_status(client_factory):
    with client_factory(connected=True) as (env, client):
        pairs = identities(env, client)
        owner, stranger = headers(pairs, "owner"), headers(pairs, "stranger")
        assert client.get("/api/state", headers=owner).json()["devices"] == []
        r = client.post("/api/strips/claim", json={"code": MAC[-7:].lower()}, headers=owner)
        assert r.status_code == 200
        claim = r.json()
        assert claim["expires_in"] == 60
        url = "/api/strips/claim/" + claim["claim_id"]
        assert client.get(url, headers=owner).json() == {"status": "pending"}
        assert client.get(url, headers=stranger).status_code == 404
        assert client.post("/api/strips/claim", json={"code": MAC[-7:]}, headers=stranger).status_code == 409
        async def button():
            env.writer.write(b"up:event:onoff:1:on\r\n")
            await env.writer.drain()
            for _ in range(100):
                if env.hub.sharing.role(MAC, pairs["owner"]["user"]["id"]) == "owner":
                    return
                await asyncio.sleep(.01)
            raise AssertionError("button did not claim strip")
        client.portal.call(button)
        assert client.get(url, headers=owner).json() == {"status": "done", "mac": MAC}
        assert client.get("/api/state", headers=owner).json()["devices"][0]["role"] == "owner"


def test_claim_expiry_and_uniform_404(client_factory, monkeypatch):
    with client_factory(connected=True) as (env, client):
        pairs = identities(env, client)
        h = headers(pairs, "owner")
        r = client.post("/api/strips/claim", json={"code": MAC[-7:]}, headers=h).json()
        from powerk import sharing
        now = time.time()
        monkeypatch.setattr(sharing.time, "time", lambda: now + 61)
        assert client.get("/api/strips/claim/" + r["claim_id"], headers=h).json() == {"status": "expired"}
        env.hub.sharing.button(MAC)
        assert env.hub.sharing.role(MAC, pairs["owner"]["user"]["id"]) is None
        def start(code):
            r = client.post("/api/strips/claim", json={"code": code}, headers=h)
            return r.status_code, r.json()
        unknown = start("0000000")
        env.dev.online = False
        offline = start(MAC[-7:])
        env.dev.online = True
        own(env, pairs)
        claimed = start(MAC[-7:])
        assert unknown == offline == claimed == (404, {"error": "no unclaimed online strip with this code"})


def test_sharing_transfer_leave_unclaim_and_rule_move(client_factory):
    with client_factory() as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        base = "/api/strips/" + MAC
        h = headers(pairs, "owner")
        before = client.get(base + "/access", headers=h).json()
        r = client.post(base + "/access", json={"phone": "+201000000099", "role": "control"}, headers=h)
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert client.get(base + "/access", headers=h).json() == before
        assert client.post(base + "/access", json={"phone": PHONES["viewer"], "role": "viewer"}, headers=h).json() == r.json()
        assert client.post(base + "/access", json={"phone": PHONES["viewer"], "role": "owner"}, headers=h).status_code == 400
        uid = pairs["owner"]["user"]["id"]
        assert client.delete(base + "/access/" + str(uid), headers=h).status_code == 403
        rule = clean_rule({"mac": MAC, "kind": "timer", "minutes": 2, "on": True, "outlets": [1]}, time.time())
        env.store.put_rule(rule)
        assert client.put("/api/rules/" + rule["id"], json={"mac": OTHER}, headers=h).status_code == 404
        assert env.store.rule(rule["id"])["mac"] == MAC
        assert client.post(base + "/transfer", json={"phone": PHONES["stranger"]}, headers=h).json() == {"error":"unknown strip"}
        assert client.post(base + "/transfer", json={"phone": PHONES["viewer"]}, headers=h).status_code == 200
        assert client.get(base + "/access", headers=h).status_code == 403
        assert client.post(base + "/leave", json={}, headers=h).status_code == 200
        assert client.get(base + "/settings", headers=h).status_code == 404
        assert client.delete(base, headers=headers(pairs,"viewer")).status_code == 200
        assert env.hub.sharing.accessible(pairs["control"]["user"]["id"]) == {}
        assert env.store.rule(rule["id"]) == rule


def test_settings_totals_limits_and_budget_are_per_strip(client_factory):
    with client_factory() as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        own(env, pairs, OTHER)
        env.hub.legacy_notifications = False
        for mac in (MAC, OTHER):
            env.hub.devices[mac] = Device(mac, "lgutap", "1", "")
            env.hub.db.add_energy(mac, 1, 520, time.time())
        env.hub.db.add_energy("FFFFFFFFFFFF", 1, 999999, time.time())
        h = headers(pairs, "owner")
        first = {"currency":"EGP", "price_kwh":100, "budget":100, "temp_max_c":34, "power_max_w":100}
        second = {"currency":"USD", "price_kwh":2, "budget":100, "temp_max_c":80, "power_max_w":2000}
        for mac, changes in ((MAC, first), (OTHER, second)):
            assert client.put(f"/api/strips/{mac}/settings", json=changes, headers=h).json() == changes
            records = [dict(o, temp_c=40, power_w=30) for o in env.hub.devices[mac].outlets.values()]
            env.hub.on_getinfo(env.hub.devices[mac], records, time.time())
        events = env.hub.db.events()
        assert {e["mac"] for e in events} == {MAC}
        assert {e["code"] for e in events} == {"temp_high", "power_high"}
        env.engine._budget(time.time())
        env.engine._budget(time.time())
        budgets = [e for e in env.hub.db.events() if e["code"] == "budget"]
        assert len(budgets) == 1 and budgets[0]["mac"] == MAC
        assert budgets[0]["params"]["cost"] == 52 and budgets[0]["params"]["pct"] == 50
        state = client.get("/api/state", headers=h).json()
        # Different currencies: compatibility totals use the first visible strip.
        assert state["month_kwh"] == .52 and state["month_cost"] == 52 and state["currency"] == "EGP"
        assert [(d["currency"], d["price_kwh"], d["month_cost"]) for d in state["devices"]] == [("EGP",100,52),("USD",2,1.04)]
        client.put(f"/api/strips/{OTHER}/settings", json={"currency":"EGP"}, headers=h)
        state = client.get("/api/state", headers=h).json()
        assert state["month_kwh"] == 1.04 and state["month_cost"] == 53.04
        assert client.get(f"/api/history?mac={OTHER}", headers=h).json()["total_cost"] == 1.04
        assert client.put(f"/api/strips/{MAC}/settings", json={"telegram_token":"leak"}, headers=h).status_code == 400
        assert client.put(f"/api/strips/{MAC}/settings", json={"temp_max_c":29}, headers=h).status_code == 400
        # Claim defaults do not inherit another person's legacy configuration.
        assert env.store.settings()["price_kwh"] == 2.14
        # The old Android global form remains effective for all strips.
        assert client.put("/api/settings", json={"price_kwh":3}).status_code == 200
        assert all(env.hub.settings(mac)["price_kwh"] == 3 for mac in (MAC, OTHER))


def test_events_read_pointers_and_revocation_are_scoped(client_factory):
    with client_factory() as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        stranger_id = pairs["stranger"]["user"]["id"]
        env.hub.sharing.start_claim(stranger_id, OTHER)
        env.hub.sharing.button(OTHER)
        for mac in (MAC, OTHER, None):
            env.hub.event("warn", "offline", "offline", mac)
        owner, control, stranger = [headers(pairs, r) for r in ("owner", "control", "stranger")]
        for h, mac in ((owner, MAC), (control, MAC), (stranger, OTHER)):
            response = client.get("/api/events", headers=h).json()
            assert response["unread_alerts"] == 1
            assert [e["mac"] for e in response["events"]] == [mac]
            assert response["events"][0]["params"]["actor"] == "strip"
        assert len(client.get("/api/events").json()["events"]) == 3
        assert client.post("/api/events/read", json={"through_id":10**9}, headers=owner).json()["unread_alerts"] == 0
        assert client.get("/api/state", headers=control).json()["unread_alerts"] == 1
        assert env.store.meta("events_read_id",0) == 0
        env.hub.event("alert", "temp_high", "hot", MAC)
        assert client.get("/api/events", headers=owner).json()["unread_alerts"] == 1
        assert client.post("/api/events/read", json={"through_id":0}, headers=owner).json()["unread_alerts"] == 1
        uid = pairs["control"]["user"]["id"]
        assert client.delete(f"/api/strips/{MAC}/access/{uid}", headers=owner).status_code == 200
        assert client.get("/api/events", headers=control).json() == {"events":[], "unread_alerts":0}
        assert client.get(f"/api/events?mac={MAC}", headers=control).status_code == 404


def test_notification_channels_preferences_and_current_user_test(client_factory):
    with client_factory() as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        env.hub.legacy_notifications = False
        calls = []
        env.hub.notifier.send = lambda title, text, settings: calls.append(settings)
        owner, viewer = headers(pairs,"owner"), headers(pairs,"viewer")
        for h, topic in ((owner,"owner"), (viewer,"viewer")):
            r = client.put("/api/me/notifications", json={"ntfy_url":"https://ntfy.sh/"+topic,"telegram_token":"private-"+topic,"telegram_chat":"chat"}, headers=h)
            assert r.status_code == 200 and "telegram_token" not in r.json() and r.json()["telegram_configured"]
            assert r.json()["alerts"][MAC]["offline"] is True
            assert r.json()["alerts"][MAC]["autooff"] is False
        env.hub.event("alert","temp_high","hot",MAC)
        assert {c["ntfy_url"] for c in calls} == {"https://ntfy.sh/owner", "https://ntfy.sh/viewer"}
        calls.clear()
        assert client.put("/api/me/notifications", json={"alerts":{MAC:{"temp_high":False}}}, headers=owner).status_code == 200
        assert client.put("/api/me/notifications", json={"alerts":{MAC:{"online":True}}}, headers=viewer).status_code == 200
        env.hub.event("alert","temp_high","hot",MAC)
        env.hub.event("info","online","online",MAC)
        assert [c["telegram_token"] for c in calls] == ["private-viewer"]*2
        calls.clear()
        env.hub.event("info","autooff","idle",MAC)
        env.hub.event("alert","temp_high","private",OTHER)
        env.hub.event("alert","temp_high","global")
        assert calls == []
        tested = []
        def test_channels(settings):
            tested.append(settings)
            return ["ntfy"], []
        env.hub.notifier.test = test_channels
        assert client.post("/api/alerts/test", json={}, headers=owner).json()["sent"] == ["ntfy"]
        assert tested[0]["telegram_token"] == "private-owner"
        assert client.put("/api/me/notifications", json={"alerts":{OTHER:{"offline":False}},"ntfy_url":""}, headers=owner).status_code == 404
        assert client.get("/api/me/notifications", headers=owner).json()["ntfy_url"] == "https://ntfy.sh/owner"
        for body in ({"alerts":[]}, {"alerts":{MAC:{"offline":1}}}, {"alerts":{MAC:{"wat":True}}}, {"budget":3}):
            assert client.put("/api/me/notifications", json=body, headers=owner).status_code == 400
        client.put("/api/me/notifications", json={"telegram_token":""}, headers=owner)
        assert client.get("/api/me/notifications", headers=owner).json()["telegram_configured"] is False
        assert client.post(f"/api/strips/{MAC}/leave", json={}, headers=viewer).status_code == 200
        assert client.get("/api/me/notifications", headers=viewer).json()["alerts"] == {}
        env.hub.event("alert","temp_high","hot",MAC)
        assert calls == []


@pytest.mark.parametrize("migrated", [False, True])
def test_event_channels_and_legacy_test_after_migration(client_factory, monkeypatch, migrated):
    # Execute the real channel dispatch synchronously, intercepting only HTTP delivery.
    monkeypatch.setattr("powerk.notify.threading", SimpleNamespace(
        Thread=lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args))))
    with client_factory() as (env, client):
        identities(env, client)
        env.store.set_meta("devices", {MAC: {}})
        channels = {"ntfy_url": "https://ntfy.sh/owner", "telegram_token": "owner-token", "telegram_chat": "123"}
        env.store.update_settings(channels)
        if migrated:
            env.hub.sharing.migrate(env.store, PHONES["owner"])
        # Reload the persisted marker, as on server restart after the CLI migration.
        env.hub.store = Store(env.data / "powerk.json")
        notifier = env.hub.notifier = Notifier(env.hub.store)
        deliveries, scopes = [], []
        monkeypatch.setattr(notifier, "_post", lambda url, body, headers: deliveries.append(url))
        send = notifier.send

        def record_send(title, text, settings=None):
            scopes.append(settings)
            send(title, text, settings)

        monkeypatch.setattr(notifier, "send", record_send)
        assert env.hub.legacy_notifications is True
        env.hub.event("alert", "temp_high", "hot", MAC)
        assert deliveries == ["https://ntfy.sh/owner", "https://api.telegram.org/botowner-token/sendMessage"]
        assert scopes == ([channels] if migrated else [None])

        deliveries.clear()
        scopes.clear()
        env.hub.event("warn", "offline", "no strip attached")
        assert scopes == ([] if migrated else [None])
        assert len(deliveries) == (0 if migrated else 2)

        # Explicit legacy tests must still send to globals, including after migration.
        env.hub.store.update_settings({"ntfy_url": "https://ntfy.sh/legacy", "telegram_token": "legacy-token"})
        deliveries.clear()
        response = client.post("/api/alerts/test", json={})
        assert response.status_code == 200
        assert response.json() == {"ok": True, "sent": ["ntfy", "telegram"], "failed": []}
        assert deliveries == ["https://ntfy.sh/legacy", "https://api.telegram.org/botlegacy-token/sendMessage"]


def test_migration_cli_is_once_and_legacy_can_read_write(client_factory, legacy, monkeypatch, capsys):
    from powerk import main as runner
    with client_factory() as (env, client):
        pairs = identities(env, client)
        env.store.set_meta("devices", {MAC:{"model":"lgutap","fw":"1"}})
        env.store.set_name(MAC,0,"Desk")
        env.store.update_settings({"currency":"USD", "price_kwh":7, "ntfy_url":"https://ntfy.sh/topic", "telegram_token":"private"})
        rule = clean_rule({"mac":MAC,"kind":"timer","minutes":2,"on":True,"outlets":[1]}, time.time())
        env.store.put_rule(rule)
        env.hub.db.add_energy(OTHER,1,100,time.time())
        previous_owner = pairs["stranger"]["user"]["id"]
        env.hub.sharing.start_claim(previous_owner, MAC)
        env.hub.sharing.button(MAC)
        original = (env.data / "powerk.json").read_bytes()
        monkeypatch.setattr("sys.argv", ["powerk","migrate","--data",str(env.data),"--owner",PHONES["owner"]])
        assert runner.main() == 0
        assert "Migrated 2 strips" in capsys.readouterr().out
        migrated = (env.data / "powerk.json").read_bytes()
        migrated_data = json.loads(migrated)
        timestamp = migrated_data["meta"].pop("accounts_migrated")
        assert isinstance(timestamp, int) and timestamp > 0
        assert migrated_data == json.loads(original)
        uid = pairs["owner"]["user"]["id"]
        assert env.hub.sharing.accessible(uid) == {MAC:"owner",OTHER:"owner"}
        assert env.hub.sharing.role(MAC, previous_owner) == "control"
        with env.hub.db.lock:
            owners = env.hub.db.conn.execute("SELECT mac,user_id FROM strip_access WHERE role='owner' ORDER BY mac").fetchall()
        assert owners == [(OTHER,uid),(MAC,uid)]
        assert env.hub.sharing.settings(MAC)["price_kwh"] == 7
        assert env.hub.sharing.channels(uid)["telegram_token"] == "private"
        env.hub.sharing.update_settings(MAC,{"price_kwh":9})
        env.hub.sharing.unclaim(OTHER)
        assert runner.main() == 0
        assert "already completed" in capsys.readouterr().out
        assert env.hub.sharing.settings(MAC)["price_kwh"] == 9 and OTHER not in env.hub.sharing.claimed()
        assert (env.data / "powerk.json").read_bytes() == migrated
        # Repair migrations performed before the JSON marker existed, without recopying data.
        (env.data / "powerk.json").write_bytes(original)
        assert runner.main() == 0
        assert "already completed" in capsys.readouterr().out
        assert (env.data / "powerk.json").read_bytes() == migrated
        assert env.hub.sharing.settings(MAC)["price_kwh"] == 9 and OTHER not in env.hub.sharing.claimed()
        old_store = legacy.Store(env.data / "powerk.json")
        old_db = legacy.Db(str(env.data / "powerk.db"))
        try:
            assert old_store.name(MAC,0) == "Desk" and old_store.rules() == [rule]
            assert old_store.settings()["telegram_token"] == "private"
            assert old_store.meta("accounts_migrated") == timestamp
            assert old_db._sum_wh(OTHER,0) == 100
            old_db.add_event({"ts":time.time(),"code":"offline","level":"warn","mac":MAC,"outlet":None,"text":"old","params":{}})
            assert env.hub.db.events()[0]["text"] == "old"
        finally:
            old_db.conn.close()
        monkeypatch.setattr("sys.argv", ["powerk","migrate","--data",str(env.data),"--owner","+201000000099"])
        with pytest.raises(SystemExit, match="existing account"):
            runner.main()


def test_tcp_eight_per_ip_and_releases_slots(run_strip, capsys):
    async def check(env):
        sockets = []
        try:
            for _ in range(7):
                sockets.append(await asyncio.open_connection("127.0.0.1",env.port))
            await asyncio.sleep(.05)
            assert env.hub.connections_per_ip["127.0.0.1"] == 8
            reader, writer = await asyncio.open_connection("127.0.0.1",env.port)
            sockets.append((reader,writer))
            assert await asyncio.wait_for(reader.read(),1) == b""
            sockets[0][1].close()
            await sockets[0][1].wait_closed()
            for _ in range(100):
                if env.hub.connections_per_ip["127.0.0.1"] == 7:
                    break
                await asyncio.sleep(.01)
            assert env.hub.connections_per_ip["127.0.0.1"] == 7
            sockets.append(await asyncio.open_connection("127.0.0.1",env.port))
            await asyncio.sleep(.05)
            assert env.hub.connections_per_ip["127.0.0.1"] == 8
        finally:
            for _, writer in sockets:
                writer.close()
                await writer.wait_closed()
    run_strip(check)
    assert "TCP session limit (8)" in capsys.readouterr().out


def test_undeclared_policy_fails_closed(client_factory, monkeypatch):
    from powerk.api import API_POLICIES
    monkeypatch.setitem(API_POLICIES, ("GET","/api/state"), "unrecognized-policy")
    with client_factory() as (_, client):
        assert client.get("/api/state").status_code == 403
