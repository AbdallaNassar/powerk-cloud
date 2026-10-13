"""Optional HTTP v1 FCM, with injectable transport and a bounded background pool."""
from __future__ import annotations

import base64
import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

TOKEN_URL = 'https://oauth2.googleapis.com/token'
SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def post(url, body, headers):
    request = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        response = urllib.request.build_opener(_NoRedirect).open(request, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(1024 * 1024)
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            data = {}
        return response.code, data, dict(response.headers)


class FCM:
    def __init__(self, tokens, service_account=None, *, http=post, clock=time.time, sleep=None,
                 workers=2, capacity=64):
        self.tokens, self.http, self.clock = tokens, http, clock
        self.stopped = threading.Event()
        self.sleep = sleep or self.stopped.wait
        self.enabled = bool(service_account)
        self.oauth_lock = threading.Lock()
        self.cached_token, self.refresh_at = '', 0
        self.slots = threading.BoundedSemaphore(capacity)
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='powerk-fcm')
        if self.enabled:
            try:
                account = json.loads(Path(service_account).read_text(encoding='utf-8'))
                self.project, self.email = account['project_id'], account['client_email']
                if not isinstance(self.project, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,127}', self.project):
                    raise ValueError()
                if not isinstance(self.email, str) or not self.email or len(self.email) > 320:
                    raise ValueError()
                self.key = serialization.load_pem_private_key(account['private_key'].encode(), password=None)
                if not isinstance(self.key, rsa.RSAPrivateKey):
                    raise ValueError()
            except Exception:
                # Neither file contents nor cryptographic parser exceptions reach logs.
                raise ValueError('invalid FCM service account configuration') from None

    def assertion(self):
        def encode(data):
            return base64.urlsafe_b64encode(data).rstrip(b'=')
        now = int(self.clock())
        header = {'alg': 'RS256', 'typ': 'JWT'}
        claims = {'iss': self.email, 'scope': SCOPE, 'aud': TOKEN_URL, 'iat': now, 'exp': now + 3600}
        signed = b'.'.join(encode(json.dumps(value, separators=(',', ':')).encode()) for value in (header, claims))
        signature = self.key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
        return (signed + b'.' + encode(signature)).decode()

    def request(self, url, body, headers, *, allowed=None):
        for attempt in range(4):
            if self.stopped.is_set() or (allowed is not None and not allowed()):
                raise RuntimeError('FCM stopped')
            status, data, response_headers = self.http(url, body, headers)
            if (status != 429 and not 500 <= status < 600) or attempt == 3:
                return status, data
            minimum = 60 if status == 429 else 2 ** attempt
            retry_after = next((v for k, v in response_headers.items() if k.lower() == 'retry-after'), 0)
            try:
                delay = max(minimum, min(60, float(retry_after)))
            except (TypeError, ValueError):
                delay = minimum
            self.sleep(delay)
        raise RuntimeError('unreachable')

    def access_token(self):
        with self.oauth_lock:
            if self.cached_token and self.clock() < self.refresh_at:
                return self.cached_token
            body = urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                              'assertion': self.assertion()}).encode()
            status, data = self.request(TOKEN_URL, body, {'Content-Type': 'application/x-www-form-urlencoded'})
            if status != 200 or not isinstance(data.get('access_token'), str):
                raise RuntimeError('OAuth token exchange failed')
            self.cached_token = data['access_token']
            self.refresh_at = self.clock() + max(0, int(data.get('expires_in', 3600)) - 300)
            return self.cached_token

    @staticmethod
    def message(token, event):
        alert = event.get('level') in ('warn', 'alert')
        mac, code = event.get('mac') or '', event['code']
        tag = f'{mac}:{code}'
        return {'message': {
            'token': token,
            'notification': {'title': 'powerk: ' + code.replace('_', ' '), 'body': event['text']},
            'data': {'type': 'test' if code == 'test' else 'event', 'mac': mac,
                     'outlet': str(event.get('outlet') or 0), 'event_id': str(event.get('id') or 0), 'code': code},
            'android': {'priority': 'HIGH' if alert else 'NORMAL', 'collapse_key': tag,
                        'notification': {'channel_id': 'alerts' if alert else 'info', 'tag': tag}},
        }}

    def deliver(self, token, family_id, event):
        try:
            if not self.enabled or not self.tokens.active(token, family_id, event):
                return 'device no longer registered'
            access = self.access_token()
            # OAuth may have waited on the network. Recheck permissions after it returns.
            if self.stopped.is_set() or not self.tokens.active(token, family_id, event):
                return 'device no longer registered'
            status, data = self.request(f'https://fcm.googleapis.com/v1/projects/{self.project}/messages:send',
                json.dumps(self.message(token, event)).encode(),
                {'Authorization': 'Bearer ' + access, 'Content-Type': 'application/json'},
                allowed=lambda: self.tokens.active(token, family_id, event))
            if 200 <= status < 300:
                return None
            details = data.get('error', {}).get('details', [])
            invalid = status == 404 or any(
                d.get('@type') == 'type.googleapis.com/google.firebase.fcm.v1.FcmError' and
                d.get('errorCode') in ('UNREGISTERED', 'INVALID_ARGUMENT') or
                any(v.get('field') == 'message.token' for v in d.get('fieldViolations', [])) for d in details)
            if invalid and not self.stopped.is_set():
                self.tokens.delete_invalid(token, family_id)
            if status == 401:
                with self.oauth_lock:
                    self.cached_token = ''
            return f'HTTP {status}'
        except Exception:
            # Exception messages and provider bodies can contain tokens or signing material.
            return 'FCM delivery failed'

    def _deliver_user(self, user_id, event):
        errors = []
        sent = False
        for token, family in self.tokens.for_user(user_id):
            if self.stopped.is_set():
                break
            error = self.deliver(token, family, event)
            if error:
                errors.append(error)
            else:
                sent = True
        return (['fcm'] if sent else [], [{'channel': 'fcm', 'error': e} for e in sorted(set(errors))])

    def submit(self, user_id, event):
        if not self.enabled or self.stopped.is_set() or not self.slots.acquire(blocking=False):
            return None
        try:
            future = self.pool.submit(self._deliver_user, user_id, dict(event))
        except RuntimeError:
            self.slots.release()
            return None
        future.add_done_callback(lambda _: self.slots.release())
        return future

    def send(self, user_id, event):
        return self.submit(user_id, event) is not None

    def test(self, user_id):
        if not self.enabled:
            return [], []
        future = self.submit(user_id, {'code': 'test', 'level': 'info', 'text': 'Test notification from powerk'})
        if future is None:
            return [], [{'channel': 'fcm', 'error': 'push queue full'}]
        return future.result()

    def close(self):
        self.stopped.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
