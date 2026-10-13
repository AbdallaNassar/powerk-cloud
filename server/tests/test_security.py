"""Security boundaries use deterministic clocks and real HTTP/SQLite."""
import asyncio
import hashlib
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from powerk.ratelimit import LIMITS, RateLimiter, RateLimited
from powerk.security import client_ip, parse_trusted_proxies, SECURITY_HEADERS
from test_accounts import PHONE, PASSWORD, register, bearer
from test_sharing import identities, headers, own, MAC, PHONES


class Clock:
    def __init__(self):
        self.value = 1000000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest.mark.parametrize('name', list(LIMITS))
def test_sliding_limits(name):
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    count, seconds = LIMITS[name]
    for _ in range(count):
        limiter.take(name, 'key')
    with pytest.raises(RateLimited) as blocked:
        limiter.take(name, 'key')
    assert blocked.value.retry_after == seconds
    clock.advance(seconds - .25)
    with pytest.raises(RateLimited) as blocked:
        limiter.take(name, 'key')
    assert blocked.value.retry_after == 1
    clock.advance(.25)
    limiter.take(name, 'key')


def test_phone_backoff_reset_idle_eviction_and_bound():
    clock = Clock()
    limiter = RateLimiter(clock=clock, max_keys=2)
    for _ in range(5):
        limiter.check_phone('phone')
        limiter.fail_phone('phone')
    for delay in (60, 120, 240, 480, 900, 900):
        with pytest.raises(RateLimited) as blocked:
            limiter.check_phone('phone')
        assert blocked.value.retry_after == delay
        clock.advance(delay)
        limiter.check_phone('phone')
        limiter.fail_phone('phone')
    limiter.reset_phone('phone')
    limiter.check_phone('phone')
    limiter.reset_phone('phone')
    limiter.take('api', 'one')
    limiter.take('api', 'two')
    with pytest.raises(RateLimited):
        limiter.take('api', 'three')
    clock.advance(86401)
    limiter.take('api', 'three')
    assert len(limiter.entries) <= 2


@pytest.mark.parametrize('peer,trusted,headers_,expected', [
    ('192.0.2.1', [], {'X-Real-IP': '198.51.100.2'}, '192.0.2.1'),
    ('192.0.2.1', ['10.0.0.0/8'], {'X-Real-IP': '198.51.100.2', 'X-Forwarded-For': '203.0.113.3'}, '192.0.2.1'),
    ('10.0.0.2', ['10.0.0.0/8'], {'X-Real-IP': '198.51.100.2', 'X-Forwarded-For': '203.0.113.3'}, '198.51.100.2'),
    ('10.0.0.2', ['10.0.0.0/8'], {'X-Forwarded-For': '6.6.6.6, 198.51.100.2, 10.0.0.3'}, '198.51.100.2'),
    ('10.0.0.2', ['10.0.0.0/8'], {'X-Real-IP': 'invalid', 'X-Forwarded-For': '198.51.100.2, unknown'}, '10.0.0.2'),
    ('::1', ['::1/128'], {'X-Real-IP': '2001:db8::2'}, '2001:db8::2'),
])
def test_proxy_boundary(peer, trusted, headers_, expected):
    from starlette.datastructures import Headers
    assert client_ip(peer, Headers(headers_), parse_trusted_proxies(trusted)) == expected
    assert len(parse_trusted_proxies(['10.0.0.0/8,::1/128', '192.0.2.0/24'])) == 3
    with pytest.raises(ValueError):
        parse_trusted_proxies(['not-a-cidr'])


@pytest.mark.parametrize('path', ['/', '/api/state', '/app.js', '/app.css', '/powerk.py', '/missing'])
def test_response_headers_and_assets(client_factory, path):
    with client_factory(token='') as (_, client):
        r = client.get(path)
        for key, value in SECURITY_HEADERS.items():
            assert r.headers[key] == value
        assert 'server' not in r.headers and 'date' not in r.headers
        if path in ('/app.js', '/app.css'):
            assert r.status_code == 200
            assert r.headers['etag']
            assert client.get(path, headers={'If-None-Match': r.headers['etag']}).status_code == 304


def test_login_unknown_phone_backoff_parity(client_factory, monkeypatch):
    clock = Clock()
    with client_factory(token='', rate_limiter=RateLimiter(clock=clock)) as (env, client):
        register(client)
        accounts = client.app.state.accounts
        verified = []
        monkeypatch.setattr(accounts, '_verify', lambda encoded, password: verified.append(encoded) or False)
        for phone in (PHONE, '+201001234568'):
            for _ in range(5):
                assert client.post('/api/auth/login', json={'phone': phone, 'password': 'wrong'}).status_code == 401
            r = client.post('/api/auth/login', json={'phone': phone, 'password': 'wrong'})
            assert r.status_code == 429 and r.json() == {'error': 'too many requests'}
            assert r.headers['retry-after'] == '60'
        assert len(verified) == 10
        clock.advance(60)
        for phone in (PHONE, '+201001234568'):
            assert client.post('/api/auth/login', json={'phone': phone, 'password': 'wrong'}).status_code == 401
            assert client.post('/api/auth/login', json={'phone': phone, 'password': 'wrong'}).headers['retry-after'] == '120'
        rows = env.hub.db.conn.execute("SELECT user_id,detail_json FROM audit_log WHERE action='login_failure'").fetchall()
        assert len(rows) == 12
        unknown = [json.loads(detail) for uid, detail in rows if uid is None]
        assert unknown[0]['phone_hash'] == hashlib.sha256(b'+201001234568').hexdigest()
        assert '+201001234568' not in json.dumps(rows)


@pytest.mark.parametrize('name,method,path,body,normal', [
    ('login', 'POST', '/api/auth/login', {'phone': 'bad', 'password': 'wrong'}, 400),
    ('refresh', 'POST', '/api/auth/refresh', {'refresh_token': 'unknown'}, 401),
    ('claim', 'POST', '/api/strips/claim', {'code': 'bad'}, 400),
    ('access', 'POST', '/api/strips/AABBCCDDEEFF/access', {'phone': '+201111111111', 'role': 'viewer'}, 200),
    ('api', 'GET', '/api/state', None, 200),
])
def test_each_http_limit_and_retry_after(client_factory, name, method, path, body, normal):
    clock = Clock()
    with client_factory(token='', rate_limiter=RateLimiter(clock=clock)) as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        auth = headers(pairs, 'owner')
        count, seconds = LIMITS[name]
        for _ in range(count):
            assert client.request(method, path, json=body, headers=auth).status_code == normal
        for _ in range(3):
            r = client.request(method, path, json=body, headers=auth)
            assert r.status_code == 429 and r.json() == {'error': 'too many requests'}
            assert r.headers['retry-after'] == str(seconds)
        assert env.hub.db.conn.execute("SELECT count(*) FROM audit_log WHERE action='rate_limit'").fetchone()[0] == 1
        if seconds > 60:
            clock.advance(60)
            assert client.request(method, path, json=body, headers=auth).status_code == 429
            assert env.hub.db.conn.execute("SELECT count(*) FROM audit_log WHERE action='rate_limit'").fetchone()[0] == 2
            clock.advance(seconds - 60)
        else:
            clock.advance(seconds)
        assert client.request(method, path, json=body, headers=auth).status_code == normal


def test_registration_counts_successes_and_resets_hourly(client_factory):
    clock = Clock()
    with client_factory(token='', rate_limiter=RateLimiter(clock=clock)) as (_, client):
        for _ in range(5):
            assert client.post('/api/auth/register', json={'phone': 'bad'}).status_code == 400
        for n in range(3):
            register(client, phone=f'+20100000000{n}')
        r = client.post('/api/auth/register', json={'phone': PHONE, 'password': PASSWORD})
        assert r.status_code == 429 and r.headers['retry-after'] == '3600'
        clock.advance(3600)
        register(client)


def test_login_success_resets_phone_penalty(client_factory):
    clock = Clock()
    with client_factory(token='', rate_limiter=RateLimiter(clock=clock)) as (_, client):
        register(client)
        for _ in range(5):
            assert client.post('/api/auth/login', json={'phone': '01001234567', 'password': 'wrong'}).status_code == 401
        clock.advance(60)
        assert client.post('/api/auth/login', json={'phone': PHONE, 'password': PASSWORD}).status_code == 200
        for _ in range(5):
            assert client.post('/api/auth/login', json={'phone': PHONE, 'password': 'wrong'}).status_code == 401
        assert client.post('/api/auth/login', json={'phone': PHONE, 'password': PASSWORD}).headers['retry-after'] == '60'


def test_access_writes_share_one_per_user_bucket(client_factory):
    with client_factory(token='', rate_limiter=RateLimiter(limits={**LIMITS, 'access': (2, 3600)})) as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        uid = pairs['viewer']['user']['id']
        auth = headers(pairs, 'owner')
        path = f'/api/strips/{MAC}/access'
        assert client.post(path, json={'phone': PHONES['stranger'], 'role': 'viewer'}, headers=auth).status_code == 200
        assert client.put(f'{path}/{uid}', json={'role': 'control'}, headers=auth).status_code == 200
        assert client.delete(f'{path}/{uid}', headers=auth).status_code == 429
        # Other users have their own counters even behind the same NAT.
        assert client.delete(f'{path}/{uid}', headers=headers(pairs, 'control')).status_code == 403


def test_anonymous_limit_and_user_limit_are_distinct(client_factory):
    with client_factory(token='', rate_limiter=RateLimiter(limits={**LIMITS, 'api': (1, 60)})) as (env, client):
        pairs = identities(env, client)
        assert client.get('/api/state').status_code == 401
        assert client.get('/api/not-a-route').status_code == 429
        for role in ('owner', 'control'):
            assert client.get('/api/state', headers=headers(pairs, role)).status_code == 200
            assert client.get('/api/state', headers=headers(pairs, role)).status_code == 429
        assert client.get('/').status_code == 200


@pytest.mark.parametrize('trusted,expected', [((), '10.0.0.2'), (('10.0.0.0/8',), '198.51.100.2')])
def test_resolved_ip_used_for_session_audit_and_limits(client_factory, trusted, expected):
    limiter = RateLimiter(limits={**LIMITS, 'refresh': (1, 600)})
    with client_factory(token='', trusted_proxies=trusted, rate_limiter=limiter) as (env, fixture):
        with TestClient(fixture.app, client=('10.0.0.2', 5678)) as client:
            client.headers.update({'X-Real-IP': '198.51.100.2', 'X-Forwarded-For': '203.0.113.2'})
            pair = register(client)
            sessions = client.get('/api/auth/sessions', headers=bearer(pair)).json()['sessions']
            assert sessions[0]['ip'] == expected
            assert env.hub.db.conn.execute("SELECT ip FROM audit_log WHERE action='register'").fetchone()[0] == expected
            assert client.post('/api/auth/refresh', json={'refresh_token': 'bad'}).status_code == 401
            client.headers['X-Real-IP'] = '198.51.100.3'
            assert client.post('/api/auth/refresh', json={'refresh_token': 'bad'}).status_code == (401 if trusted else 429)


def test_audit_auth_actions_and_private_pagination(client_factory):
    with client_factory(token='') as (env, client):
        first = register(client)
        second = client.post('/api/auth/login', json={'phone': PHONE, 'password': PASSWORD}).json()
        assert client.post('/api/auth/login', json={'phone': PHONE, 'password': 'wrong'}).status_code == 401
        assert client.post('/api/auth/refresh', json={'refresh_token': second['refresh_token']}).status_code == 200
        assert client.post('/api/auth/refresh', json={'refresh_token': second['refresh_token']}).status_code == 200
        assert client.post('/api/auth/refresh', json={'refresh_token': second['refresh_token']}).status_code == 401
        auth = bearer(first)
        assert client.post('/api/auth/password', json={'current_password': PASSWORD, 'new_password': 'another quiet river'}, headers=auth).status_code == 200
        third = client.post('/api/auth/login', json={'phone': PHONE, 'password': 'another quiet river'}).json()
        sid = client.get('/api/auth/sessions', headers=bearer(third)).json()['sessions']
        target = next(s['id'] for s in sid if s['current'])
        assert client.delete('/api/auth/sessions/' + target, headers=auth).status_code == 200
        other = register(client, phone='+201001234568')
        own_rows = client.get('/api/me/security-log', headers=auth).json()['events']
        assert {r['action'] for r in own_rows} >= {'register', 'login_success', 'login_failure', 'refresh_grace', 'refresh_reuse', 'password_change', 'session_revoked'}
        assert all(r['user_id'] == first['user']['id'] and r['ip'] == 'testclient' for r in own_rows)
        assert [r['id'] for r in own_rows] == sorted([r['id'] for r in own_rows], reverse=True)
        page = client.get('/api/me/security-log?limit=2', headers=auth).json()
        next_page = client.get('/api/me/security-log?limit=2&before_id=' + str(page['next_before_id']), headers=auth).json()
        assert {r['id'] for r in page['events']}.isdisjoint(r['id'] for r in next_page['events'])
        assert len(client.get('/api/me/security-log', headers=bearer(other)).json()['events']) == 1
        assert client.get('/api/me/security-log?limit=oops', headers=auth).status_code == 400
        assert client.get('/api/me/security-log?before_id=' + '9'*100, headers=auth).status_code == 400
        assert client.get('/api/me/security-log').status_code == 401
        assert client.post('/api/auth/logout', json={}, headers=auth).status_code == 200
        assert env.hub.db.conn.execute("SELECT count(*) FROM audit_log WHERE action='logout'").fetchone()[0] == 1
        raw = json.dumps(env.hub.db.conn.execute('SELECT detail_json FROM audit_log').fetchall())
        assert PASSWORD not in raw and first['access_token'] not in raw and first['refresh_token'] not in raw


def test_audit_sharing_actions_and_claim_expiry(client_factory, monkeypatch):
    import powerk.sharing as module
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        owner = pairs['owner']['user']['id']
        sharing = env.hub.sharing
        claim = sharing.start_claim(owner, MAC, '198.51.100.7')
        sharing.button(MAC)
        auth = headers(pairs, 'owner')
        path = f'/api/strips/{MAC}'
        assert client.post(path + '/access', json={'phone': PHONES['viewer'], 'role': 'viewer'}, headers=auth).status_code == 200
        vid = pairs['viewer']['user']['id']
        assert client.put(path + f'/access/{vid}', json={'role': 'control'}, headers=auth).status_code == 200
        assert client.delete(path + f'/access/{vid}', headers=auth).status_code == 200
        assert client.post(path + '/access', json={'phone': PHONES['control'], 'role': 'control'}, headers=auth).status_code == 200
        assert client.put(path + '/settings', json={'currency': 'USD'}, headers=auth).status_code == 200
        assert client.post(path + '/transfer', json={'phone': PHONES['control']}, headers=auth).status_code == 200
        assert client.post(path + '/leave', json={}, headers=auth).status_code == 200
        assert client.delete(path, headers=headers(pairs, 'control')).status_code == 200
        expiring = sharing.start_claim(owner, MAC, '198.51.100.8')
        monkeypatch.setattr(module.time, 'time', lambda: time.time_ns() / 1e9 + 61)
        sharing.expire_claims()
        sharing.expire_claims()
        rows = env.hub.db.conn.execute('SELECT action,ip,target FROM audit_log').fetchall()
        assert {r[0] for r in rows} >= {'claim_started', 'claim_completed', 'claim_expired', 'share', 'role_change', 'remove_access', 'leave', 'transfer', 'unclaim', 'strip_settings_change'}
        assert ('claim_completed', '198.51.100.7', claim['claim_id']) in rows
        assert rows.count(('claim_expired', '198.51.100.8', expiring['claim_id'])) == 1


def test_housekeeping_preserves_live_credentials_and_replay_detection(client_factory, monkeypatch):
    from powerk import sessions as sessions_module
    from powerk.housekeeping import Housekeeping
    from powerk.sessions import AuthError, token_hash
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        sessions, db = client.app.state.accounts.sessions, env.hub.db
        now = int(time.time())
        clock = Clock()
        clock.value = now
        monkeypatch.setattr(sessions_module, 'now', clock)
        old_pair = pairs['owner']
        rotated = sessions.refresh(old_pair['refresh_token'])
        clock.advance(60)
        now = int(clock.value)
        recent = sessions.resolve(pairs['viewer']['access_token'])
        old = sessions.resolve(pairs['stranger']['access_token'])
        sessions.revoke(recent, recent.family_id)
        sessions.revoke(old, old.family_id)
        with db.lock, db.conn:
            db.conn.execute('UPDATE session_families SET revoked_at=? WHERE id=?', (now - 30*86400 - 1, old.family_id))
            db.conn.execute('INSERT INTO access_tokens VALUES(?,?,?)', ('expired', recent.family_id, now))
            db.conn.execute('INSERT INTO refresh_tokens(token_hash,family_id,created_at,expires_at) VALUES(?,?,?,?)',
                            ('expired', recent.family_id, now-1, now))
            db.conn.execute('INSERT INTO audit_log(ts,user_id,ip,action,target,detail_json) VALUES(?,NULL,?,?,?,?)',
                            (now-180*86400-1, '', 'old', '', '{}'))
            db.conn.execute('INSERT INTO audit_log(ts,user_id,ip,action,target,detail_json) VALUES(?,NULL,?,?,?,?)',
                            (now-180*86400, '', 'boundary', '', '{}'))
        cleanup = Housekeeping(sessions, env.hub.sharing, clock=clock)
        cleanup.run_due()
        assert sessions.resolve(rotated['access_token']) is not None
        assert sessions.resolve(pairs['control']['access_token']) is not None
        assert db.conn.execute('SELECT 1 FROM session_families WHERE id=?', (recent.family_id,)).fetchone()
        assert not db.conn.execute('SELECT 1 FROM session_families WHERE id=?', (old.family_id,)).fetchone()
        for table in ('access_tokens', 'refresh_tokens', 'refresh_replays'):
            assert not db.conn.execute(f'SELECT 1 FROM {table} WHERE family_id=?', (old.family_id,)).fetchone()
            assert not db.conn.execute(f'SELECT 1 FROM {table} WHERE token_hash=?', ('expired',)).fetchone()
        assert not db.conn.execute('SELECT 1 FROM refresh_tokens WHERE token_hash=?', (token_hash(old_pair['refresh_token']),)).fetchone()
        assert not db.conn.execute("SELECT 1 FROM audit_log WHERE action='old'").fetchone()
        assert db.conn.execute("SELECT 1 FROM audit_log WHERE action='boundary'").fetchone()
        with pytest.raises(AuthError):
            sessions.refresh(old_pair['refresh_token'], '198.51.100.2')
        assert sessions.resolve(rotated['access_token']) is None


def test_housekeeping_schedule_and_off_loop_execution():
    from powerk.housekeeping import Housekeeping
    clock = Clock()
    calls = []
    audit = SimpleNamespace(prune=lambda now: calls.append(('audit', now)))
    sessions = SimpleNamespace(audit=audit, prune=lambda now: calls.append(('tokens', now)))
    sharing = SimpleNamespace(expire_claims=lambda: None)
    cleanup = Housekeeping(sessions, sharing, clock=clock)
    cleanup.run_due()
    clock.advance(3599); cleanup.run_due()
    assert [c[0] for c in calls] == ['tokens', 'audit']
    clock.advance(1); cleanup.run_due()
    assert [c[0] for c in calls] == ['tokens', 'audit', 'tokens']
    clock.advance(86400); cleanup.run_due()
    assert [c[0] for c in calls][-2:] == ['tokens', 'audit']

    async def exercise():
        main_thread = threading.get_ident()
        done = asyncio.Event()
        loop = asyncio.get_running_loop()
        def work():
            assert threading.get_ident() != main_thread
            loop.call_soon_threadsafe(done.set)
        cleanup.run_due = work
        task = asyncio.create_task(cleanup.loop())
        await asyncio.wait_for(done.wait(), 1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())


def test_rule_shutdown_is_bounded(client_factory):
    with client_factory() as (env, _):
        async def exercise():
            engine = env.engine
            engine.inflight.add('stuck')
            task = asyncio.create_task(asyncio.Event().wait())
            engine.action_tasks.add(task)
            started = asyncio.get_running_loop().time()
            await asyncio.wait_for(engine.shutdown(.03), .2)
            assert asyncio.get_running_loop().time() - started < .2
            assert task.cancelled()
        asyncio.run(exercise())


def test_headers_cover_unhandled_errors_and_public_downloads(client_factory, tmp_path, monkeypatch):
    apk = tmp_path / 'public.apk'
    apk.write_bytes(b'APK')
    with client_factory(token='', apk=apk) as (env, fixture):
        def broken(*args):
            raise RuntimeError('test error')
        with TestClient(fixture.app, raise_server_exceptions=False) as client:
            assert client.get('/powerk.apk').content == b'APK'
            for path in ('/powerk.apk', '/fonts/Kalam-700-latin.woff2'):
                response = client.get(path)
                assert response.status_code == 200 and 'server' not in response.headers
                assert all(response.headers[k] == v for k, v in SECURITY_HEADERS.items())
            monkeypatch.setattr(fixture.app.state.accounts.sessions, 'resolve', broken)
            response = client.get('/api/state')
            assert response.status_code == 500 and 'server' not in response.headers
            assert all(response.headers[k] == v for k, v in SECURITY_HEADERS.items())


def test_concurrent_phone_guesses_are_serialized(client_factory, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    with client_factory(token='') as (_, client):
        verified = []
        monkeypatch.setattr(client.app.state.accounts, '_verify', lambda *_: verified.append(True) or False)
        with ThreadPoolExecutor(max_workers=8) as workers:
            statuses = list(workers.map(lambda _: client.post('/api/auth/login', json={'phone': PHONE, 'password': 'wrong'}).status_code, range(8)))
        assert statuses.count(401) == 5 and statuses.count(429) == 3
        assert len(verified) == 5


def test_sample_rate_limit_without_crossing_window_boundary():
    clock = Clock()
    limiter = RateLimiter(clock=clock, limits={'api': (1, 60)})
    limiter.take('api', 'key')
    clock.advance(59)
    with pytest.raises(RateLimited) as blocked:
        limiter.take('api', 'key')
    assert limiter.sample(blocked.value.key)
    clock.advance(1)
    limiter.take('api', 'key')
    with pytest.raises(RateLimited) as blocked:
        limiter.take('api', 'key')
    assert not limiter.sample(blocked.value.key)


def test_same_share_audit_shape_for_unknown_phone(client_factory):
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        for phone in (PHONES['stranger'], '+201111111111'):
            assert client.post(f'/api/strips/{MAC}/access', json={'phone': phone, 'role': 'viewer'}, headers=headers(pairs, 'owner')).json() == {'ok': True}
        rows = env.hub.db.conn.execute("SELECT detail_json FROM audit_log WHERE action='share' ORDER BY id DESC LIMIT 2").fetchall()
        assert all(set(json.loads(row[0])) == {'phone_hash', 'role'} for row in rows)


def test_background_cleanup_finishes_before_shutdown_even_after_repeated_cancel():
    from powerk.housekeeping import Housekeeping
    started, released, finished = threading.Event(), threading.Event(), threading.Event()
    cleanup = Housekeeping(None, None)
    def work():
        started.set()
        released.wait(1)
        finished.set()
    cleanup.run_due = work
    async def exercise():
        task = asyncio.create_task(cleanup.loop())
        while not started.is_set():
            await asyncio.sleep(.001)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        released.set()
        await asyncio.gather(task, return_exceptions=True)
        assert finished.is_set()
    asyncio.run(exercise())


def test_phone_penalty_expires_after_idle_day():
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    for _ in range(5):
        limiter.fail_phone('key')
    clock.advance(86401)
    limiter.check_phone('key')
    limiter.fail_phone('key')
    limiter.check_phone('key')
    assert limiter.entries['phone', 'key'].failures == 1
