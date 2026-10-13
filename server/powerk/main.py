"""Run the device TCP server, rules engine and FastAPI on one asyncio loop."""
from __future__ import annotations

import argparse
import asyncio
import os
import socket
from pathlib import Path

import uvicorn

from .api import create_app
from .accounts import Accounts
from .devices import Hub, parse_macs
from .protocol import DEVICE_PORT, WEB_PORT
from .rules import Engine
from .store import Db, Store
from .sharing import Sharing
from .sessions import AuthError
from .security import parse_trusted_proxies
from .housekeeping import Housekeeping


def local_ipv4s() -> list[str]:
    try:
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        ips = []
    return [i for i in ips if not i.startswith(("127.", "169.254."))]


async def cmd_serve(args) -> int:
    data = Path(args.data).resolve() if args.data else Path.cwd()
    data.mkdir(parents=True, exist_ok=True)
    store = Store(data / "powerk.json")
    hub = Hub(store, Db(str(data / "powerk.db")), allow=parse_macs(args.mac))
    hub.restore()
    engine = Engine(hub)
    connections = set()

    def connected(reader, writer):
        task = asyncio.create_task(hub.handle_client(reader, writer))
        connections.add(task)
        task.add_done_callback(connections.discard)

    server = await asyncio.start_server(connected, "0.0.0.0", args.port)
    candidates = local_ipv4s()
    ip = args.ip or (candidates or ["127.0.0.1"])[0]

    app = create_app(hub, engine, local_ip=ip, port=args.port, token=args.token, apk=args.apk,
                     secure_cookies=args.secure_cookies, open_registration=args.open_registration,
                     trusted_proxies=getattr(args, 'trusted_proxy', []),
                     fcm_service_account=getattr(args, 'fcm_service_account', None))
    httpd = uvicorn.Server(uvicorn.Config(
        app, host="0.0.0.0", port=args.web_port, access_log=False, log_level="warning",
        server_header=False, proxy_headers=False,
        ws='websockets-sansio', ws_max_size=4096, ws_max_queue=4,
    ))

    print(f"powerk")
    print(f"  web UI (phone/PC)  http://{ip}:{args.web_port}")
    print(f"  strip server       TCP {args.port}")
    print(f"  auth               accounts{' + legacy token' if args.token else ' (session required)'}")
    print(f"  registration       {'open' if args.open_registration else 'closed'}")
    if args.token:
        print(f"                     browser: user 'powerk' + the token as password; app: Settings -> Token")
    print(f"  strips allowed     {', '.join(sorted(hub.allow)) if hub.allow else 'any (--mac is an optional extra allowlist)'}")
    print("  ownership          physical-button claims; unclaimed strips hidden from accounts")
    print(f"  data               {data}")
    print(f"  if not provisioned yet:  python powerk.py provision --ip {ip} --ssid WIFI --password PW")
    if app.state.apk.is_file():
        print(f"  android app        http://{ip}:{args.web_port}/powerk.apk")
    if len(candidates) > 1 and not args.ip:
        print(f"  other local IPs: {', '.join(c for c in candidates if c != ip)}  (pick one with --ip if wrong)")
    print("  Ctrl+C to stop")
    housekeeping = Housekeeping(app.state.accounts.sessions, hub.sharing)
    background = [asyncio.create_task(hub.poll_loop()), asyncio.create_task(engine.loop()),
                  asyncio.create_task(housekeeping.loop())]
    background_cancelled = False

    def cancel_background():
        nonlocal background_cancelled
        if not background_cancelled:
            background_cancelled = True
            for task in background:
                task.cancel()

    async def serve_http():
        try:
            await httpd.serve()
        finally:
            cancel_background()

    try:
        await asyncio.gather(serve_http(), *background)
    except asyncio.CancelledError:
        if not httpd.should_exit:
            raise
    finally:
        server.close()
        cancel_background()
        await asyncio.gather(*background, return_exceptions=True)
        for session in list(hub.sessions.values()):
            session.writer.close()
        pending = list(connections | app.state.command_tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await server.wait_closed()
        # Existing rule actions can still report their outcome after their connection closes.
        await engine.shutdown()
        await app.state.live.close()
        await asyncio.to_thread(app.state.fcm.close)
        hub.db.conn.close()
    return 0


def cmd_migrate(args) -> int:
    data = Path(args.data).resolve()
    db = Db(str(data / "powerk.db"))
    try:
        Accounts(db)
        result = Sharing(db).migrate(Store(data / "powerk.json"), args.owner)
    except AuthError as err:
        raise SystemExit(str(err)) from None
    finally:
        db.conn.close()
    if result["already_migrated"]:
        print("Ownership migration already completed; notification marker ensured.")
    else:
        print(f"Migrated {result['migrated']} strips to {args.owner}; copied strip settings and owner notification channels.")
        print("Names, rules, history and legacy global settings preserved; previous owners retain control access.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run device server + web UI (default)")
    s.add_argument("--port", type=int, default=DEVICE_PORT, help=f"device TCP port (default {DEVICE_PORT}, the strip's fixed port)")
    s.add_argument("--web-port", type=int, default=WEB_PORT)
    s.add_argument("--ip", help="IP to print in the UI/provision hint (default: auto-detect)")
    s.add_argument("--token", default="", help="optional legacy shared API token; grants full strip access alongside accounts")
    s.add_argument("--secure-cookies", action="store_true", help="mark account cookies Secure (enable behind HTTPS)")
    s.add_argument('--trusted-proxy', action='append', default=[], metavar='CIDR',
                   help='trust X-Real-IP/X-Forwarded-For only from these peer networks (repeatable/comma separated; default none)')
    s.add_argument("--open-registration", action=argparse.BooleanOptionalAction, default=True,
                   help="allow new accounts (default: open)")
    s.add_argument("--mac", action="append", default=[], help="optional extra MAC allowlist (comma separated or repeated); ownership uses claims")
    s.add_argument("--data", help="directory for powerk.json and powerk.db (default: current working directory)")
    s.add_argument("--apk", help="APK to serve at /powerk.apk (default: repo Android debug build)")
    s.add_argument('--fcm-service-account', default=os.environ.get('POWERK_FCM_SERVICE_ACCOUNT') or None,
                   metavar='PATH', help='FCM service-account JSON (or POWERK_FCM_SERVICE_ACCOUNT; default disabled)')
    m = sub.add_parser("migrate", help="assign existing strips to an existing account, once")
    m.add_argument("--data", required=True, help="directory containing powerk.json and powerk.db")
    m.add_argument("--owner", required=True, help="phone number of an existing account")
    args = ap.parse_args()

    if args.cmd == "migrate":
        return cmd_migrate(args)
    if args.cmd in (None, "serve"):
        for key, default in (("port", DEVICE_PORT), ("web_port", WEB_PORT), ("ip", None), ("token", ""), ("mac", []),
                             ("data", None), ("apk", None), ("secure_cookies", False), ("open_registration", True), ("trusted_proxy", [])):
            setattr(args, key, getattr(args, key, default))
        if not hasattr(args, 'fcm_service_account'):
            args.fcm_service_account = os.environ.get('POWERK_FCM_SERVICE_ACCOUNT') or None
        try:
            parse_trusted_proxies(args.trusted_proxy)
        except ValueError as err:
            ap.error(f'--trusted-proxy needs valid CIDRs: {err}')
        try:
            return asyncio.run(cmd_serve(args))
        except KeyboardInterrupt:
            return 0
    ap.error("unknown command")
