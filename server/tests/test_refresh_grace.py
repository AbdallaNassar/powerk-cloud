"""Lost refresh responses allow one bounded retry without opening another chain."""
import json

import pytest

from powerk import sessions as sessions_module
from powerk.sessions import AuthError, Sessions, token_hash
from powerk.store import Db
from test_accounts import bearer, login, register


@pytest.fixture
def clock(monkeypatch):
    value = [1800000000]
    monkeypatch.setattr(sessions_module, "now", lambda: value[0])
    return value


def refresh(client, pair):
    return client.post("/api/auth/refresh", json={"refresh_token": pair["refresh_token"]})


@pytest.mark.parametrize("delay", [0, 59])
def test_lost_response_retry_replaces_child_and_records_safe_audit(client_factory, clock, delay):
    with client_factory(token="") as (env, client):
        parent = register(client)
        clock[0] += 899  # The grace interval starts at rotation, not token creation.
        lost = refresh(client, parent).json()
        clock[0] += delay
        response = refresh(client, parent)
        assert response.status_code == 200
        replacement = response.json()
        assert replacement["user"] == parent["user"]
        assert replacement["expires_in"] == 900
        for key in ("access_token", "refresh_token"):
            assert len({pair[key] for pair in (parent, lost, replacement)}) == 3
        service = client.app.state.accounts.sessions
        identity = service.resolve(replacement["access_token"])
        assert identity is not None
        assert identity.family_id == service.resolve(lost["access_token"]).family_id
        assert client.get("/api/auth/me", headers=bearer(replacement)).status_code == 200
        events = client.get("/api/me/security-log", headers=bearer(replacement)).json()["events"]
        grace = [event for event in events if event["action"] == "refresh_grace"]
        assert len(grace) == 1
        assert grace[0]["user_id"] == parent["user"]["id"]
        assert grace[0]["ip"] == "testclient" and grace[0]["target"] == identity.family_id
        assert grace[0]["detail"] == {}
        dump = "\n".join(env.hub.db.conn.iterdump())
        for pair in (parent, lost, replacement):
            for key in ("access_token", "refresh_token"):
                assert pair[key] not in dump
                assert token_hash(pair[key]) not in json.dumps(grace)
        assert refresh(client, replacement).status_code == 200
        # A replaced child cannot redeem normally or claim grace of its own.
        assert refresh(client, lost).status_code == 401
        assert service.resolve(replacement["access_token"]) is None


@pytest.mark.parametrize("delay", [60, 61])
def test_retry_at_or_after_deadline_revokes_only_its_family(client_factory, clock, delay):
    with client_factory(token="") as (_, client):
        parent, other = register(client), login(client)
        child = refresh(client, parent).json()
        clock[0] += delay
        assert refresh(client, parent).status_code == 401
        for pair in (parent, child):
            assert client.get("/api/auth/me", headers=bearer(pair)).status_code == 401
        assert refresh(client, child).status_code == 401
        assert client.get("/api/auth/me", headers=bearer(other)).status_code == 200


def test_consumed_child_prevents_parent_grace(client_factory, clock):
    with client_factory(token="") as (_, client):
        parent = register(client)
        child = refresh(client, parent).json()
        grandchild = refresh(client, child).json()
        assert refresh(client, parent).status_code == 401
        for pair in (parent, child, grandchild):
            assert client.get("/api/auth/me", headers=bearer(pair)).status_code == 401
        assert refresh(client, grandchild).status_code == 401


def test_second_grace_attempt_revokes_family(client_factory, clock):
    with client_factory(token="") as (_, client):
        parent = register(client)
        lost = refresh(client, parent).json()
        response = refresh(client, parent)
        assert response.status_code == 200
        replacement = response.json()
        clock[0] += 1
        assert refresh(client, parent).status_code == 401
        for pair in (parent, lost, replacement):
            assert client.get("/api/auth/me", headers=bearer(pair)).status_code == 401
        assert refresh(client, replacement).status_code == 401


def test_revoked_family_cannot_use_grace(client_factory, clock):
    with client_factory(token="") as (env, client):
        parent = register(client)
        child = refresh(client, parent).json()
        assert client.post("/api/auth/logout", json={}, headers=bearer(child)).status_code == 200
        assert refresh(client, parent).status_code == 401
        assert not env.hub.db.conn.execute("SELECT 1 FROM audit_log WHERE action='refresh_grace'").fetchone()


def test_housekeeping_preserves_grace_even_when_parent_expires(client_factory, clock):
    from powerk.housekeeping import Housekeeping

    with client_factory(token="") as (env, client):
        parent = register(client)
        clock[0] += 30 * 86400 - 1
        child = refresh(client, parent).json()
        used_at = clock[0]
        clock[0] += 59
        service = client.app.state.accounts.sessions
        # Exercise the actual housekeeping entrypoint and its supplied clock.
        Housekeeping(service, env.hub.sharing, clock=lambda: clock[0]).run_due()
        assert refresh(client, parent).status_code == 200
        assert refresh(client, child).status_code == 401
        clock[0] = used_at + 60
        service.prune(clock[0])
        digest = token_hash(parent["refresh_token"])
        assert not env.hub.db.conn.execute("SELECT 1 FROM refresh_tokens WHERE token_hash=?", (digest,)).fetchone()
        assert env.hub.db.conn.execute("SELECT 1 FROM refresh_replays WHERE token_hash=?", (digest,)).fetchone()


def test_pruned_parent_still_revokes_live_family(client_factory, clock):
    with client_factory(token="") as (_, client):
        parent = register(client)
        child = refresh(client, parent).json()
        clock[0] += 60
        client.app.state.accounts.sessions.prune(clock[0])
        assert refresh(client, parent).status_code == 401
        assert client.get("/api/auth/me", headers=bearer(child)).status_code == 401


def test_failed_grace_issuance_rolls_back_child_invalidation(client_factory, clock, monkeypatch):
    with client_factory(token="") as (_, client):
        parent = register(client)
        service = client.app.state.accounts.sessions
        child = service.refresh(parent["refresh_token"])

        def fail_issue(*args):
            raise RuntimeError("issuance failed")

        with monkeypatch.context() as patch:
            patch.setattr(service, "issue_locked", fail_issue)
            with pytest.raises(RuntimeError, match="issuance failed"):
                service.refresh(parent["refresh_token"])
        assert all(event["action"] != "refresh_grace" for event in service.audit.list(parent["user"]["id"]))
        replacement = service.refresh(parent["refresh_token"])
        assert service.resolve(replacement["access_token"]) is not None
        with pytest.raises(AuthError) as rejected:
            service.refresh(child["refresh_token"])
        assert rejected.value.status == 401


@pytest.mark.parametrize("used", [False, True])
def test_old_schema_migrates_idempotently_and_preserves_tokens(tmp_path, clock, used):
    db = Db(str(tmp_path / "old.db"))
    try:
        with db.conn:
            db.conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, phone TEXT, created_at INTEGER)")
            db.conn.execute("INSERT INTO users VALUES(1,'+201001234567',1800000000)")
            db.conn.execute("CREATE TABLE session_families (id TEXT PRIMARY KEY, user_id INTEGER, "
                            "created_at INTEGER, last_used_at INTEGER, user_agent TEXT, ip TEXT, revoked_at INTEGER)")
            db.conn.execute("INSERT INTO session_families VALUES('family',1,1800000000,1800000000,'','',NULL)")
            db.conn.execute("CREATE TABLE refresh_tokens (token_hash TEXT PRIMARY KEY, family_id TEXT, "
                            "created_at INTEGER, expires_at INTEGER, used_at INTEGER)")
            db.conn.execute("INSERT INTO refresh_tokens VALUES(?,'family',1800000000,1802592000,?)",
                            (token_hash("old-token"), clock[0] if used else None))
        Sessions(db)
        service = Sessions(db)
        if used:
            # Pre-upgrade consumed rows have no known child, so remain replay-only.
            with pytest.raises(AuthError) as rejected:
                service.refresh("old-token")
            assert rejected.value.status == 401
            assert db.conn.execute("SELECT revoked_at FROM session_families").fetchone()[0] == clock[0]
        else:
            service.refresh("old-token")
            replacement = service.refresh("old-token")
            assert service.resolve(replacement["access_token"]).family_id == "family"
    finally:
        db.conn.close()
