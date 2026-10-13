"""No network: verify signed OAuth assertions and HTTP v1 requests at the wire boundary."""
import base64
import json
import threading
from urllib.parse import parse_qs

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


@pytest.fixture
def service_account(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / 'account.json'
    path.write_text(json.dumps({'project_id': 'test-project', 'client_email': 'sender@test.iam.gserviceaccount.com',
                               'private_key': key.private_bytes(serialization.Encoding.PEM,
                                   serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()}))
    return path, key


class Tokens:
    def __init__(self):
        self.deleted = []

    def delete_invalid(self, token, family_id):
        self.deleted.append((token, family_id))

    def active(self, token, family_id, event=None):
        return True


def test_jwt_signature_claims_and_token_cache(service_account):
    from powerk.fcm import FCM
    path, key = service_account
    calls, now = [], [1800000000]
    def http(url, body, headers):
        calls.append((url, body, headers))
        return 200, {'access_token': 'oauth-token', 'expires_in': 3600}, {}
    sender = FCM(Tokens(), path, http=http, clock=lambda: now[0])
    try:
        assert sender.access_token() == 'oauth-token'
        url, body, headers = calls[0]
        assert url == 'https://oauth2.googleapis.com/token'
        form = parse_qs(body.decode())
        assert form['grant_type'] == ['urn:ietf:params:oauth:grant-type:jwt-bearer']
        assertion = form['assertion'][0]
        head, claims, signature = assertion.split('.')
        decode = lambda s: base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
        assert json.loads(decode(head)) == {'alg': 'RS256', 'typ': 'JWT'}
        assert json.loads(decode(claims)) == {
            'iss': 'sender@test.iam.gserviceaccount.com', 'scope': 'https://www.googleapis.com/auth/firebase.messaging',
            'aud': 'https://oauth2.googleapis.com/token', 'iat': 1800000000, 'exp': 1800003600,
        }
        key.public_key().verify(decode(signature), (head + '.' + claims).encode(), padding.PKCS1v15(), hashes.SHA256())
        now[0] += 3299
        assert sender.access_token() == 'oauth-token' and len(calls) == 1
        now[0] += 2
        sender.access_token()
        assert len(calls) == 2
    finally:
        sender.close()


@pytest.mark.parametrize('level,priority,channel', [('alert', 'HIGH', 'alerts'), ('warn', 'HIGH', 'alerts'), ('info', 'NORMAL', 'info')])
def test_message_contract_and_retry(service_account, level, priority, channel):
    from powerk.fcm import FCM
    sent, waits = [], []
    def http(url, body, headers):
        if url.endswith('/token'):
            return 200, {'access_token': 'oauth', 'expires_in': 3600}, {}
        sent.append((url, json.loads(body), headers))
        return (503, {}, {}) if len(sent) < 3 else (200, {'name': 'accepted'}, {})
    sender = FCM(Tokens(), service_account[0], http=http, sleep=waits.append)
    ev = {'id': 42, 'mac': 'AABBCCDDEEFF', 'outlet': 2, 'code': 'temp_high', 'level': level, 'text': 'Outlet hot'}
    try:
        assert sender.deliver('device', 'family', ev) is None
        assert len(sent) == 3 and len(waits) == 2
        url, body, headers = sent[-1]
        assert url == 'https://fcm.googleapis.com/v1/projects/test-project/messages:send'
        assert headers['Authorization'] == 'Bearer oauth'
        assert body['message'] == {
            'token': 'device', 'notification': {'title': 'powerk: temp high', 'body': 'Outlet hot'},
            'data': {'type': 'event', 'mac': 'AABBCCDDEEFF', 'outlet': '2', 'event_id': '42', 'code': 'temp_high'},
            'android': {'priority': priority, 'collapse_key': 'AABBCCDDEEFF:temp_high',
                        'notification': {'channel_id': channel, 'tag': 'AABBCCDDEEFF:temp_high'}},
        }
    finally:
        sender.close()


@pytest.mark.parametrize('status,error,delete', [
    (404, {'status': 'NOT_FOUND'}, True),
    (400, {'details': [{'@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError', 'errorCode': 'INVALID_ARGUMENT'}]}, True),
    (400, {'status': 'INVALID_ARGUMENT', 'details': [{'@type': 'type.googleapis.com/google.rpc.BadRequest',
              'fieldViolations': [{'field': 'message.notification', 'description': 'bad payload'}]}]}, False),
])
def test_invalid_token_is_deleted_but_payload_errors_are_not(service_account, status, error, delete):
    from powerk.fcm import FCM
    tokens = Tokens()
    def http(url, body, headers):
        return (200, {'access_token': 'oauth', 'expires_in': 3600}, {}) if url.endswith('/token') else (status, {'error': error}, {})
    sender = FCM(tokens, service_account[0], http=http)
    try:
        assert sender.deliver('bad-device', 'family', {'code': 'test', 'level': 'info', 'text': 'test'})
        assert tokens.deleted == ([('bad-device', 'family')] if delete else [])
    finally:
        sender.close()


def test_disabled_fcm_never_uses_transport():
    from powerk.fcm import FCM
    def fail(*args):
        raise AssertionError('disabled FCM must not call HTTP')
    sender = FCM(Tokens(), http=fail)
    assert sender.enabled is False
    assert sender.send(1, {}) is False
    assert sender.test(1) == ([], [])
    sender.close()


def test_fcm_routing_uses_access_preferences_and_event_ids(client_factory, service_account):
    from test_sharing import MAC, OTHER, headers, identities, own
    sent = []
    arrived = threading.Event()
    def http(url, body, request_headers):
        if url.endswith('/token'):
            return 200, {'access_token': 'oauth', 'expires_in': 3600}, {}
        sent.append(json.loads(body)['message'])
        arrived.set()
        return 200, {'name': 'accepted'}, {}
    with client_factory(token='', fcm_service_account=service_account[0], fcm_http=http) as (env, client):
        pairs = identities(env, client)
        own(env, pairs)
        for role in ('owner', 'viewer', 'stranger'):
            assert client.post('/api/me/push-tokens', headers=headers(pairs, role), json={
                'token': role + '-device', 'platform': 'android',
            }).status_code == 200
        # No notification-settings row is needed for FCM's default alert preferences.
        client.put('/api/me/notifications', headers=headers(pairs, 'viewer'), json={'alerts': {MAC: {'temp_high': False}}})
        env.hub.event('info', 'online', 'default info off', MAC)
        env.hub.event('warn', 'offline', 'hidden strip', OTHER)
        env.hub.event('warn', 'offline', 'no strip')
        env.hub.event('alert', 'temp_high', 'hot', MAC, 2)
        assert arrived.wait(2)
        result = client.post('/api/alerts/test', headers=headers(pairs, 'owner'), json={}).json()
        assert result == {'ok': True, 'sent': ['fcm'], 'failed': []}
        client.app.state.fcm.close()
        assert len(sent) == 2
        assert {message['token'] for message in sent} == {'owner-device'}
        alert = next(m for m in sent if m['data']['type'] == 'event')
        assert alert['data']['event_id'] == str(env.hub.db.last_event_id())
        assert alert['data']['outlet'] == '2'
        test = next(m for m in sent if m['data']['type'] == 'test')
        assert test['data'] == {'type': 'test', 'mac': '', 'outlet': '0', 'event_id': '0', 'code': 'test'}
        assert client.get('/api/me/notifications', headers=headers(pairs, 'owner')).json()['fcm'] == {'enabled': True, 'devices': 1}


def test_bounded_worker_refuses_more_jobs_and_runs_off_caller_thread(service_account):
    from powerk.fcm import FCM
    started, release = threading.Event(), threading.Event()
    caller, workers = threading.get_ident(), []
    class Registered(Tokens):
        def for_user(self, user_id):
            return [('device', 'family')]
    def http(url, body, headers):
        workers.append(threading.get_ident())
        started.set()
        assert release.wait(2)
        return 200, {'access_token': 'oauth', 'expires_in': 3600}, {}
    sender = FCM(Registered(), service_account[0], http=http, workers=1, capacity=1)
    try:
        assert sender.send(1, {'code': 'test', 'level': 'info', 'text': 'test'}) is True
        assert started.wait(2)
        assert sender.send(1, {}) is False
    finally:
        release.set()
        sender.close()
    assert workers and all(t != caller for t in workers)


def test_rate_limit_retries_and_honors_retry_after(service_account):
    from powerk.fcm import FCM
    calls, waits = [], []
    def http(url, body, headers):
        calls.append(url)
        if url.endswith('/token'):
            return 200, {'access_token': 'oauth', 'expires_in': 3600}, {}
        if len(calls) == 2:
            return 429, {}, {'Retry-After': '2'}
        return 200, {}, {}
    sender = FCM(Tokens(), service_account[0], http=http, sleep=waits.append)
    try:
        assert sender.deliver('device', 'family', {'code': 'test', 'text': 'test'}) is None
        assert len(calls) == 3 and waits[0] >= 2
    finally:
        sender.close()


def test_retry_rechecks_revocation_after_backoff(service_account):
    from powerk.fcm import FCM
    class Revoked(Tokens):
        live = True
        def active(self, token, family, event=None):
            return self.live
    tokens, calls = Revoked(), []
    def http(url, body, headers):
        if url.endswith('/token'):
            return 200, {'access_token': 'oauth', 'expires_in': 3600}, {}
        calls.append(url)
        return 503, {}, {}
    sender = FCM(tokens, service_account[0], http=http, sleep=lambda _: setattr(tokens, 'live', False))
    try:
        assert sender.deliver('device', 'family', {'code': 'test', 'text': 'test'})
        assert len(calls) == 1
    finally:
        sender.close()


def test_invalid_token_deletion_is_persisted_and_does_not_delete_reassigned_registration(client_factory, service_account):
    from powerk.fcm import FCM
    from test_sharing import headers, identities
    with client_factory(token='') as (env, client):
        pairs = identities(env, client)
        for role in ('owner', 'viewer'):
            assert client.post('/api/me/push-tokens', headers=headers(pairs, role),
                               json={'token': 'same-device', 'platform': 'android'}).status_code == 200
        tokens = client.app.state.push_tokens
        old_family = client.app.state.accounts.sessions.resolve(pairs['owner']['access_token']).family_id
        tokens.delete_invalid('same-device', old_family)
        registration = tokens.for_user(pairs['viewer']['user']['id'])
        assert len(registration) == 1
        def http(url, body, headers):
            return (200, {'access_token': 'oauth'}, {}) if url.endswith('/token') else (404, {}, {})
        sender = FCM(tokens, service_account[0], http=http)
        try:
            sender.deliver(*registration[0], {'code': 'test', 'text': 'test'})
            assert tokens.for_user(pairs['viewer']['user']['id']) == []
        finally:
            sender.close()


def test_malformed_service_account_error_never_exposes_secrets(tmp_path):
    from powerk.fcm import FCM
    path = tmp_path / 'bad.json'
    path.write_text('{"project_id":"do-not-log", "private_key":"do-not-log"}')
    with pytest.raises(ValueError) as error:
        FCM(Tokens(), path)
    assert str(error.value) == 'invalid FCM service account configuration'
