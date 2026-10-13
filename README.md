# powerk

Control the LG U+ / Jinheung **MTTL-W01** four-outlet smart strip from a browser or
Android app, using your own server instead of the vendor cloud.

**English** | [العربية](README.ar.md)

| Component | Implementation |
|---|---|
| Server | `server/`: FastAPI, device TCP server, rules, energy history and accounts |
| Clients | Web UI and `android/` (Kotlin / Jetpack Compose) |
| Provisioner | `tools/provision.py`: standalone Python standard library script, downloaded as `/powerk.py` |
| Device connection | Native plaintext `up:...` protocol to the server's IPv4 address, TCP **10086** |

## How it works

```text
phone / browser -- HTTPS --> Cloudflare -- HTTPS --> Caddy --> powerk
                                                               ^
                                                               | TCP 10086
                                                             strip
```

Provisioning writes your server's **IP address** into the strip. The strip connects
out from home; no home-router port forwarding, DNS override or firmware flashing is
needed. It does not connect through Cloudflare. The production web path uses
Cloudflare, Caddy and HTTPS; local development can connect directly over LAN HTTP.

The server runs rules even when the phone is off. Accounts see only owned or shared
strips. The web UI uses `/api/ws` for live updates and polls every two seconds while
disconnected. Commands still use HTTP. The Android app does the same and receives
push notifications through FCM.

## Repository guide

| Path | Purpose |
|---|---|
| [server/README.md](server/README.md) | Server installation, CLI, accounts and implementation details |
| [deploy/README.md](deploy/README.md) | Docker Compose, certificates, firewall, backups and rollback |
| [android/README.md](android/README.md) | App setup, accounts and validation |
| [android/PERFORMANCE.md](android/PERFORMANCE.md) | Release builds, R8 and performance checks |
| [API.md](API.md) | HTTP, WebSocket and FCM contracts |
| `tools/provision.py` | Wi-Fi and server-IP setup only |
| `powerk.py` | Old server retained for rollback; not the current server entry point |

Runtime data is `powerk.json` plus `powerk.db` in `--data` (current directory by
default; `/data` in Docker). Back up both; they contain account and notification data.

## Requirements

- MTTL-W01 strip and 2.4 GHz Wi-Fi; the recorded firmware is `0.1.54-1.0.66`.
- An always-on server with a stable IPv4 address reachable by the strip.
- Docker Compose for the supplied deployment, or Python **3.11+** for the server.
- Python **3.8+** on a Wi-Fi-capable device for provisioning; the server itself can use Ethernet.
- A browser or Android **8.0+** phone.

## Self-hosting with Docker

The supplied deployment targets an Ubuntu VPS and the production hostname above.
For your own host, adapt its domain, IP, certificates and any MAC allowlist using the
[operations guide](deploy/README.md). Complete its Cloudflare, Origin CA,
Authenticated Origin Pulls and firewall steps **before starting the services**.

1. From the repository, prepare the configuration:

   ```sh
   cd deploy
   cp .env.example .env
   chmod 600 .env
   ```

2. Edit `.env`: set `POWERK_DOMAIN` to your hostname and `POWERK_IP` to your server IPv4; set `POWERK_MAC` to your strip's
   MAC or leave it empty. For an account-only install, leave `POWERK_TOKEN` empty.
   Set `POWERK_ARGS=--secure-cookies`. Registration is open by default; add
   `--no-open-registration` when you want to close it. Leave
   `POWERK_FCM_SERVICE_ACCOUNT` empty unless you install the Firebase credentials
   described in the guide.
3. Prepare `certs/`, `backups/` and the firewall as documented, then validate and start:

   ```sh
   sudo docker compose build --pull powerk
   sudo docker compose pull caddy backup
   sudo docker compose config --quiet
   sudo docker compose run --rm --no-deps caddy caddy validate \
     --config /etc/caddy/Caddyfile --adapter caddyfile
   sudo docker compose up -d
   sudo docker compose ps
   sudo docker compose logs --tail=100 powerk caddy backup
   ```

4. Open your HTTPS hostname, register, then provision and claim a strip as below.

Only origin TCP **443** is restricted to Cloudflare; TCP **10086** must remain
reachable by the strip. The backend's HTTP **8080** is private. The backup container
takes a snapshot at startup and every 24 hours, retaining 14 complete snapshots.
Keep off-server copies too. Existing installations should follow the guide's cutover
steps and the ownership migration below before retiring the old service.

## Local development

From the repository root:

```sh
cd server
python -m venv .venv
# Unix: source .venv/bin/activate
# PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m pytest tests -q
# Optional browser-script tests; requires Node.js, no npm dependencies:
node --test tests/
python -m powerk serve --data ./data
```

Open `http://localhost:8080`, or `http://<LAN-IP>:8080` on your phone, and register.
Accounts are required even without `--token`. Local HTTP is unencrypted; secure
cookies are off by default for this workflow. Allow TCP 8080 and 10086 on the server's
LAN firewall, keep it awake, and use a fixed IP or DHCP reservation. Run one server
worker: device connections and live updates are held in that process.

## Provision a strip

1. Start the server and note its LAN IPv4 or VPS public IPv4. Download the provisioner
   **before** joining the strip's setup network if using a different device.
2. Hold the strip's main button for about 10 seconds until the LED blinks quickly.
3. Join `TONLY_TAP_XXXXXXX`, password `LGU_XXXXXXX` (the same seven characters).
   No internet on that network is normal.
4. From the repository root, run:

   ```sh
   python tools/provision.py --ip <SERVER-IP> --ssid "YOURWIFI" --password "YOURWIFIPW"
   ```

   Expect `up:ip:ip_ok`, then `up:connect:connect_ok`. The optional `provision`
   subcommand is also accepted. `--ip` must be IPv4, not the HTTPS hostname;
   SSID/password cannot contain `:` or newlines.
5. Rejoin your normal network. The strip connects to `<SERVER-IP>:10086`.
   Check server logs, then claim it: unclaimed strips do not appear in account lists.

The strip stores one server address. Repeat provisioning only when changing that
address or Wi-Fi credentials. The downloaded `/powerk.py` is the provisioner, even
though the repository's root `powerk.py` is the rollback server. Ignore the
provisioner's old hints to start `python powerk.py`; run `python -m powerk serve`
from `server/` or use Compose.

### If the server has no Wi-Fi

Only the device doing setup needs Wi-Fi and access to `192.168.1.1:30300`.

| Option | Steps |
|---|---|
| Android with Termux | On your normal network, install Python with `pkg install python`; download `https://<YOUR-HOST>/powerk.py`. Join the setup Wi-Fi and run `python powerk.py --ip <SERVER-IP> --ssid "YOURWIFI" --password "YOURWIFIPW"`. |
| Any TCP client app | Join the setup Wi-Fi; send the two lines below to `192.168.1.1:30300`, each in its own connection, ending with CRLF. |
| USB Wi-Fi adapter | Connect it to a computer and use the provisioning steps above. |
| Borrowed laptop | Copy `tools/provision.py` or download `/powerk.py`; use the **server's** IP, not the laptop's. |

```text
up:ip:<SERVER-IP>               -> up:ip:ip_ok
up:connect:<SSID>:<PASSWORD>    -> up:connect:connect_ok
```

## First account, claim and sharing

1. Register with your phone number and a password of 10–128 characters. Egyptian
   `01XXXXXXXXX` numbers normalize to `+201XXXXXXXXX`; international numbers use `+`.
   Common passwords and the phone number itself are rejected. **No SMS or OTP is sent**;
   the number is a username, not verified identity.
2. Choose **Add a strip** and enter its seven-character hexadecimal setup code
   (the suffix of `TONLY_TAP_XXXXXXX`). The strip must be online and unclaimed.
3. Press any physical strip button within **60 seconds**. **This switches an outlet**;
   choose a safe load and switch it back if needed. Ordinary API commands do not claim it.
4. As owner, open **People** and share by a registered user's phone number, choosing
   `control` or `viewer`. The recipient must register first; sharing to an unknown
   number does not create an invitation or grant later access.

| Action | owner | control | viewer |
|---|:---:|:---:|:---:|
| Read state, rules, energy, events and strip settings | Yes | Yes | Yes |
| Switch outlets, rename, create/edit/delete rules | Yes | Yes | No |
| Set strip currency, price, budget and alert limits | Yes | No | No |
| View/manage members, transfer ownership, unclaim | Yes | No | No |
| Set own notification channels and alert preferences | Yes | Yes | Yes |
| Leave a shared strip | No | Yes | Yes |

Transfer requires an existing member; the former owner becomes `control`. Unclaiming
removes everyone's access and resets strip settings and alert preferences, but keeps
names, rules and history. Access is checked on each request and outgoing WebSocket frame.

### Existing installations

Create the intended owner's account against the existing data first. Back up
`powerk.json` and `powerk.db`, stop the server, then run from `server/`:

```sh
python -m powerk migrate --data /path/to/existing/data --owner +201001234567
```

This one-time migration assigns existing strips to that account, copies global strip
settings and the owner's notification channels, and preserves names, rules and history.
For Compose, stop `powerk` and use its data volume with an overridden entry point:

```sh
sudo docker compose stop powerk
sudo docker compose run --rm --no-deps --entrypoint python powerk \
  -m powerk migrate --data /data --owner +201001234567
sudo docker compose up -d powerk
```

Never run the old and new servers against the same data simultaneously. See
[server/README.md](server/README.md) for migration markers and rollback behavior.

## Automation, energy and notifications

| Feature | Behavior |
|---|---|
| Schedule | Switch selected outlets at a local time on selected weekdays |
| Timer | Switch once after a delay; wait up to five minutes if offline |
| Cycle | Alternate on/off durations |
| Auto-off | Switch off after power stays below a threshold for a duration |
| Energy | Day/week/month/year history, estimated cost at each strip's flat price |
| Budget | Per-strip alerts at 50%, 75%, 90% and 100% |
| Alerts | Offline after 60 seconds, return online, temperature/power limits and rule activity |

Rules use the **server's timezone** (`Africa/Cairo` in Compose). A schedule missed
while offline is logged and not replayed. Counter readings are estimates, not a bill.
The first reading after server startup is a baseline; usage during server downtime is
not recovered. A strip reconnecting while the server stays running can fill its gap
from the retained counter baseline.

Each user sets personal **ntfy** and/or **Telegram** channels and per-strip event
preferences, then uses **Send test**. Warning/alert notifications default on;
information events default off. The server also supports optional **FCM** with a
Firebase service account and registered device tokens; the Android app registers
its device after sign-in and removes it on sign-out.

## Security

- Passwords use Argon2id. Account access tokens last 15 minutes; refresh tokens rotate
  and last 30 days from issue. A lost refresh response permits one retry within a
  **60-second grace window**, only while the original child token is unused.
- Web authentication uses HttpOnly cookies and CSRF protection; enable secure cookies
  behind HTTPS. Users can change passwords and revoke sessions.
- Rate limits cover login, registration, refresh, claims, sharing, API calls and sockets.
  Respect HTTP `429` and `Retry-After`.
- The web UI has a strict CSP, escaped data and XSS regression tests. Personal audit
  history is available at `/api/me/security-log`.
- Caddy uses Cloudflare Origin CA and Authenticated Origin Pulls. The supplied firewall
  restricts origin HTTPS to Cloudflare; trusted-proxy settings control client-IP headers.
- The strip's TCP protocol is **plaintext and has no cryptographic device authentication**.
  Physical claiming and an optional MAC allowlist do not change that limitation.
- An optional legacy `--token` grants full strip access, bypassing account roles.
  Leave it unset for account-only operation. Public assets, provisioner and APK
  downloads do not expose account data.

## Android app

The app supports accounts, physical claims, roles, sharing, ownership transfer,
per-strip settings, personal notifications, rules, energy and alerts. It includes
Arabic/English, three themes, outlet/strip/usage widgets and a Quick Settings tile.
Viewer accounts cannot use control actions.

Set the server in the app to your own HTTPS origin. To change the built-in default, set
`powerk.serverUrl=https://your.domain` in `android/local.properties` before building.
Local HTTP is accepted for private IPs, loopback and `.local` hosts. Access and refresh
tokens use Android Keystore-backed encrypted storage. App, widgets and tile share
refresh handling. In the foreground the app keeps a WebSocket open (polling every
60 s as a safety net, every 2 s when the socket is down) and receives FCM pushes.
Building without `android/app/google-services.json` disables push.

Build with JDK 17+ and the Android SDK:

```sh
cd android
./gradlew :app:assembleRelease
# Windows: .\gradlew.bat :app:assembleRelease
adb install -r app/build/outputs/apk/release/app-release.apk
```

Release builds use R8 and resource shrinking. Without `keystore.properties`, they
use debug signing; see [PERFORMANCE.md](android/PERFORMANCE.md) for signing setup.
`/powerk.apk` serves the file selected by `--apk`, or the debug build by default,
if present. For Compose, place a release APK at `deploy/apk/powerk.apk` and append
`--apk /apk/powerk.apk` to `POWERK_ARGS`. See [android/README.md](android/README.md).

## Web UI and API

The web UI has Outlets, Rules, Energy, Alerts and Settings, plus account and sharing
screens. Arabic RTL and English, three themes and bundled fonts work without external
page assets. HTML, JavaScript and CSS live under `server/powerk/web/`.

See [API.md](API.md) for Bearer tokens, web cookies/CSRF, permissions, HTTP commands,
WebSocket frames, notification registration and error handling. `/api/debug` exposes
raw strip diagnostics only for strips the account can access.

## Protocol reference

Wire format the strip speaks on TCP 10086 :

| Direction | Frame |
|---|---|
| strip → server | `up:bootinfo:<model>;<mac>;<mac>;<fw>;connect` |
| strip → server | `up:getinfo:<ch>:<runtime>;<relay on/off>;<state>;<overload>;<overheat>;<power mW>;<energy hex Wh>;<prev hex>;<config hex>;<status>;<event hex>;<temp C>` ×4 |
| strip → server | `up:power_report:<ch>:<mV>` (≥50000) or `:<mA>` |
| strip → server | `up:query:<rssi>` |
| strip → server | `up:event:onoff:<0-4>:on\|off` (physical button, `0` = master) |
| server → strip | `up:getinfo:all`, `up:onoff:<1-4>:on\|off`, `up:power_report:1:vol`, `up:query:wifirssi` |
| setup AP `192.168.1.1:30300` | `up:ip:<ip>` → `up:ip:ip_ok`, `up:connect:<ssid>:<pw>` → `up:connect:connect_ok` |

There is no `up:onoff:0`; "all" is sent as a loop over outlets 1–4. The device pads
some frames with NUL bytes and the port is fixed at 10086.

## Troubleshooting

| Symptom | Check / fix |
|---|---|
| Provisioner says `Not reachable` | Join `TONLY_TAP_*`, repeat setup mode, and check access to `192.168.1.1:30300`. |
| Account shows no strips | Provisioning is not claiming. Claim an online, unowned strip or ask its owner to share with your registered phone. Existing data needs `migrate --owner`. |
| Claim fails or expires | Check the seven hex characters, TCP 10086, ownership and physical button press within 60 seconds. |
| Strip offline | Check 2.4 GHz Wi-Fi, stable server IPv4, TCP 10086 firewall and `docker compose logs powerk`; run only one server. |
| HTTPS fails but strip connects | Check Cloudflare DNS/proxy, Origin CA/AOP certificates, Caddy logs and Cloudflare firewall ranges. Direct origin HTTPS is intentionally blocked. |
| `401` or repeated sign-in | Sign in again if refresh fails; check session revocation and correct server origin. Behind HTTPS enable `--secure-cookies`. |
| `403` on a write | Check the role and, for browser cookie requests, CSRF. Viewers cannot control; only owners change strip settings. |
| `429` | Wait for `Retry-After`; avoid repeated login/claim attempts or duplicate polling clients. |
| Live browser updates stop | Polling should resume; check WebSocket upgrades and secure cookies through the proxy. Android currently polls by design. |
| Schedule uses wrong hour | Check the server/container timezone, not the phone's clock. |
| No notification | Check your own channels and strip preferences, then Send test. Current Android alerts use ntfy/Telegram. |
| APK returns `404` | Build an APK and configure `--apk`; Docker does not bundle an Android build. |

## What this does not do

- MQTT/Home Assistant entities, Matter or firmware OTA.
- SMS verification or phone-based password recovery.
- Tiered tariffs, taxes or billing-grade energy measurement; prices are flat per strip.
- Encrypt or cryptographically authenticate the stock strip protocol.
- Run server rules while the server is stopped.

---

## Need something built?

I turn ideas into working apps, websites and systems — phones, browsers, servers,
and beyond. Careful engineering, honest scope, fair prices, results that actually
work. If this project was useful to you, yours can be next.

| | |
|---|---|
| **WhatsApp** | [wa.me/201093480689](https://wa.me/201093480689) — fastest reply |
| **Call** | [+20 109 348 0689](tel:+201093480689) |
| **Email** | [1ahmed.tohamy@gmail.com](mailto:1ahmed.tohamy@gmail.com) |

Tell me what you want to build; you get a clear plan and a price before anything
starts.


