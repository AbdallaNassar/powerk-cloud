import base64
from email.parser import BytesHeaderParser
from io import BytesIO

import pytest

from powerk.devices import Device
from powerk.security import SECURITY_HEADERS

MAC = "AABBCCDDEEFF"


def legacy_response(legacy, env, method, path, headers, body, token=""):
    handler = legacy.Web.__new__(legacy.Web)
    handler.hub, handler.engine = env.hub, env.engine
    handler.local_ip, handler.port, handler.token = "192.0.2.1", 10086, token
    handler.path, handler.headers = path, headers
    handler.command, handler.request_version = method, "HTTP/1.1"
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.rfile, handler.wfile = BytesIO(body), BytesIO()
    getattr(handler, "do_" + method)()
    head, content = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    status, head = head.split(b"\r\n", 1)
    # Step 4 deliberately replaces the legacy transport's Server/Date hacks.
    headers = {k.lower(): v for k, v in BytesHeaderParser().parsebytes(head).items()
               if k.lower() not in ('server', 'date')}
    headers.update({k.lower(): v for k, v in SECURITY_HEADERS.items()})
    return int(status.split()[1]), headers, content


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/state", None), ("GET", "/api/rules", None), ("GET", "/api/settings", None),
    ("GET", "/api/debug", None), ("GET", "/api/history?mac=" + MAC, None),
    ("GET", "/api/history?mac=" + MAC + "&range=year&outlet=2", None),
    ("GET", "/api/history", None), ("GET", "/api/history?mac=" + MAC + "&range=nope", None),
    ("GET", "/api/history?mac=" + MAC + "&outlet=0", None),
    ("GET", "/api/history?mac=" + MAC + "&outlet=nope", None),
    ("GET", "/api/events", None), ("GET", "/api/events?limit=nope", None),
    ("GET", "/api/events?before_id=nope", None), ("GET", "/api/events?limit=-2", None),
    ("POST", "/api/onoff", b"{}"), ("POST", "/api/onoff", b'{"mac":"AABBCCDDEEFF","outlet":true,"on":true}'),
    ("POST", "/api/onoff", b'{"mac":"AABBCCDDEEFF","outlet":0.0,"on":true}'),
    ("POST", "/api/onoff", b'{"mac":"AABBCCDDEEFF","outlet":1,"on":"false"}'),
    ("POST", "/api/onoff", b'{"mac":"AABBCCDDEEFF","outlet":1,"on":false}'),
    ("POST", "/api/name", b"{}"), ("POST", "/api/name", b'{"mac":"AABBCCDDEEFF","outlet":0,"name":false}'),
    ("POST", "/api/name", b'{"mac":"AABBCCDDEEFF","outlet":0,"name":" Desk "}'),
    ("POST", "/api/rules", b"{}"),
    ("POST", "/api/rules", b'{"mac":"AABBCCDDEEFF","kind":"timer","outlets":[1],"on":true,"minutes":0}'),
    ("POST", "/api/rules", b'{"mac":"AABBCCDDEEFF","kind":"schedule","outlets":[1],"on":true,"at":"25:00","days":[0]}'),
    ("PUT", "/api/rules/missing", b"{}"), ("DELETE", "/api/rules/missing", None),
    ("PUT", "/api/settings", b'{"unknown":1}'), ("PUT", "/api/settings", b'{"price_kwh":"1"}'),
    ("PUT", "/api/settings", b'{"price_kwh":true}'), ("PUT", "/api/settings", b'{"currency":" "}'),
    ("PUT", "/api/settings", b'{"budget":-1}'), ("PUT", "/api/settings", b'{"temp_max_c":121}'),
    ("PUT", "/api/settings", b'{"power_max_w":10}'), ("PUT", "/api/settings", b'{"ntfy_url":"ftp://x"}'),
    ("PUT", "/api/settings", b'{"telegram_token":false}'), ("PUT", "/api/settings", b'{"telegram_chat":4}'),
    ("PUT", "/api/settings", b'{"currency":" USD ","telegram_token":"abc"}'),
    ("POST", "/api/events/read", b'{"through_id":-1}'), ("POST", "/api/events/read", b'{"through_id":true}'),
    ("POST", "/api/events/read", b"{}"), ("POST", "/api/alerts/test", b"{}"),
    ("GET", "/fonts/Kalam-700-latin.woff2", None),
])
def test_responses_match_old_handler(client_factory, legacy, monkeypatch, method, path, body):
    monkeypatch.setattr(legacy.time, "time", lambda: 1790000000.0)
    with client_factory() as (env, client):
        env.hub.devices[MAC] = Device(MAC, "lgutap", "1", "192.0.2.2")
        headers = {} if body is None else {"Content-Type": "application/json", "Content-Length": str(len(body))}
        status, expected_headers, content = legacy_response(legacy, env, method, path, headers, body or b"")
        response = client.request(method, path, headers=headers, content=body)
        assert response.status_code == status
        assert response.content == content
        assert dict(response.headers) == expected_headers


@pytest.mark.parametrize("path", ["/api/state", "/nope", "/api/nope"])
@pytest.mark.parametrize("auth", ["missing", "header", "basic_user", "basic_password", "cookie", "query"])
def test_auth_responses_match_old_handler(client_factory, legacy, monkeypatch, path, auth):
    monkeypatch.setattr(legacy.time, "time", lambda: 1790000000.0)
    token = "a/b+c:d?e" if auth != "basic_user" else "a/b+c?e"
    headers = {}
    if auth == "header":
        headers["X-Token"] = token
    elif auth in ("basic_user", "basic_password"):
        pair = f"{token}:unused" if auth == "basic_user" else f"powerk:{token}"
        headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
    elif auth == "cookie":
        headers["Cookie"] = "powerk_t=" + legacy.quote(token)
    elif auth == "query":
        path += "?t=" + legacy.quote(token)
    with client_factory(token=token) as (env, client):
        status, expected_headers, content = legacy_response(legacy, env, "GET", path, headers, b"", token)
        response = client.get(path, headers=headers)
        assert response.status_code == status and response.content == content
        assert dict(response.headers) == expected_headers
