"""Transport trust and response headers (no trust in forwarding by default)."""
from __future__ import annotations

from ipaddress import ip_address, ip_network

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
       "frame-ancestors 'none'; object-src 'none'")
SECURITY_HEADERS = {
    'Content-Security-Policy': CSP,
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Resource-Policy': 'same-origin',
}


def parse_trusted_proxies(values):
    return tuple(ip_network(item.strip(), strict=False) for value in values for item in value.split(','))


def _address(value):
    # Ports, lists, zone identifiers and obfuscated names are not client IPs.
    if '%' in value:
        raise ValueError('scoped address')
    address = ip_address(value.strip())
    return getattr(address, 'ipv4_mapped', None) or address


def client_ip(peer, headers, trusted):
    def is_trusted(address):
        return any(address in network for network in trusted)
    try:
        address = _address(peer)
    except ValueError:
        return peer
    if not is_trusted(address):
        return str(address)
    try:
        return str(_address(headers.get('x-real-ip', '')))
    except ValueError:
        pass
    # Walk from the peer toward the client. Stop at the first untrusted hop.
    # A malformed hop is a broken trust chain, not permission to skip past it.
    for item in reversed(headers.get('x-forwarded-for', '').split(',')):
        try:
            hop = _address(item)
        except ValueError:
            return str(address)
        if not is_trusted(hop):
            return str(hop)
    return str(address)


class SecurityHeaders:
    """Outermost ASGI wrapper also covers unhandled 500s and framework responses."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def secured(message):
            if message['type'] == 'http.response.start':
                headers = [(k, v) for k, v in message.get('headers', []) if k.lower() != b'server']
                replace = {k.lower().encode(): v.encode() for k, v in SECURITY_HEADERS.items()}
                headers = [(k, v) for k, v in headers if k.lower() not in replace]
                message = {**message, 'headers': headers + list(replace.items())}
            await send(message)
        await self.app(scope, receive, secured)
