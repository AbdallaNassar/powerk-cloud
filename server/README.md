# powerk server

The FastAPI package preserves strip protocol, rules, notifications and existing
API response shapes, with phone/password accounts, secure sessions, strip ownership
and sharing. Accounts start with no strips; every strip request checks the current role.
The original `powerk.py` remains available for rollback; it ignores the additive
account and sharing tables in `powerk.db`. Stop one server before starting the other against
the same data directory. Rolling back also restores the old token/open-mode auth.

Requires Python **3.11+** (`websockets==17.2` needs it). Production runs in the
Docker image on Python 3.12; local development uses Python 3.13.

From this source checkout:

```sh
cd server
python -m venv .venv
# Activate .venv (Windows: .venv\Scripts\Activate.ps1; Unix: source .venv/bin/activate)
python -m pip install -e ".[test]"
python -m powerk serve --data /path/to/existing/data
python -m pytest tests -q
# Optional browser-script checks (Node.js, no npm dependencies):
node --test tests/
```

`python -m powerk` without a subcommand also serves. **The default data directory
is the current working directory**, so use `--data` to reuse production files.
Options retain their legacy defaults: `--port 10086`, `--web-port 8080`, `--ip`,
repeatable/comma-separated `--mac`, and `--data`. `--apk PATH` overrides
the APK download; its default is the repo's Android debug build. Keep the source
checkout: the public `/powerk.py` download serves `../tools/provision.py` under
the same `powerk.py` filename. Docs/OpenAPI endpoints are disabled.

Account options:

- `--open-registration` / `--no-open-registration`: defaults to open. Closing
  registration does not prevent existing accounts from signing in.
- `--secure-cookies`: enable behind HTTPS; off for local HTTP development.
- `--fcm-service-account PATH` / `POWERK_FCM_SERVICE_ACCOUNT`: optional Firebase
  service-account JSON. Unset/empty disables FCM; an invalid configured file fails
  startup without exposing its contents. See the [deployment guide](../deploy/README.md#optional-android-push-notifications-fcm).
- `--trusted-proxy CIDR`: trust client-IP headers only from matching TCP peers;
  repeat the flag or separate CIDRs with commas. Default: no trusted proxies.
  For the supplied Compose backend use `--trusted-proxy 172.30.86.0/24` (already
  prepended to `POWERK_ARGS` in Compose). Never trust arbitrary Internet clients.
- `--token YOUR_TOKEN`: optional legacy shared credential for older Android
  clients, accepted via `X-Token`, Basic, `?t=`, or `powerk_t`. It still grants full
  strip access. **No token configured no longer means an open API.**
- `--mac`: optional extra TCP allowlist, independent of ownership. Claims enforce
  ownership even when this allowlist is empty. Unclaimed strips stay connected and
  polled, but account users cannot see them. TCP allows eight concurrent connections
  per source IP (including connections awaiting bootinfo); excess connections are logged and closed.

To add a strip, sign in and choose **Add a strip**. Enter the seven-character suffix
of its setup Wi-Fi name (`TONLY_TAP_XXXXXXX`) or the code on its label. It must be
online and unclaimed. Press **any physical button** within the 60-second countdown;
the server claims it on the first `up:event:onoff:<0-4>:on|off`. Pressing a button
switches an outlet; you can switch it back. Pending claims survive restarts and
only the claimant can poll their status. Unknown, offline and already-owned codes
give the same error. Only one pending claim is allowed per strip.

Owners can share with registered phone usernames as `control` or `viewer` through
**People**. Controls may switch, rename and edit rules; viewers may only read.
Owners alone change strip settings and access, transfer to an existing member, or
unclaim (the UI requires typing the strip name). The former owner becomes control
after transfer. Members can leave. Removing access takes effect on the next request
and is rechecked for every WebSocket frame and queued FCM delivery.
Names, rules and history survive unclaim; a new claim starts with default settings.
Settings now separates owner-edited strip prices/budgets/limits from each user's
channels and per-strip alert toggles. Personal info pushes default off, warn/alert on.

Before using existing legacy data with accounts, create the intended owner's account,
stop the server, and run this **once** from `server/`:

```sh
python -m powerk migrate --data /path/to/existing/data --owner +201001234567
```

The phone must already exist. The migration finds strips in `meta.devices` and
energy/event history, assigns every one to that account, and copies global strip
settings plus that user's notification channels. Any previous owner becomes control;
other members retain access. It prints the number migrated. A database marker prevents later runs
from recopying data, even after settings edits, transfers or unclaims. After the database commit,
migration records a timestamp in `powerk.json` at `meta.accounts_migrated`; rerunning the command
repairs this marker if missing. Names, rules, history and global settings remain unchanged.
History-only strips are restored
offline on the next server start. Back up `powerk.json` and `powerk.db` before an
operational migration as usual; the unchanged legacy Store/Db can still read/write them.

Legacy `/api/settings` remains a global form: strip-field writes update all claimed
strips as well as the global fallback for unclaimed strips. Account users instead get
410 directing them to `/api/strips/{mac}/settings` and `/api/me/notifications`.
Before migration, `--token` enables global event notifications independently of personal preferences.
With `meta.accounts_migrated` present, events push only to personal channels, avoiding duplicate
delivery to copied destinations. The legacy app's Send test button still tests global channels.
For installations migrated before this marker was introduced, rerun the migration command.
Rollback restores the original global settings behavior and all-strip token access.

The page, bundled fonts, provisioner and APK stay public so the login screen can
load. All API endpoints require authentication except registration/login/refresh.
Phone usernames normalize to E.164 (or Egyptian `01XXXXXXXXX` to `+201XXXXXXXXX`),
with no SMS/OTP. Passwords use pinned `argon2-cffi==25.1.0`, 10–128 characters and a
bundled common-password denylist. See [Accounts and sessions](../API.md#accounts-and-sessions)
for requests, errors, cookie paths and the CSRF header contract.

Android/API clients get opaque access and refresh tokens in JSON. The web UI sends
`X-Powerk-Client: web` and receives HttpOnly access/refresh cookies instead of raw
tokens in its response body. It sends the double-submit CSRF header on writes,
shares a refresh attempt across simultaneous requests, and uses Web Locks when
available to coordinate browser tabs. It retries a failed authenticated call once
after refresh, then returns to login. It stores only language/theme preferences
in localStorage. Settings includes password changes and session management.

`accounts.py` owns users, phone/password policy and Argon2id verification;
`sessions.py` owns session families, hashed tokens, expiry, rotation and revocation.
They add `users`, `session_families`, `refresh_tokens` and `access_tokens` via
`CREATE TABLE IF NOT EXISTS`, without modifying the legacy tables or `store.py`.
An idempotent `ALTER TABLE` adds nullable `refresh_tokens.child_hash`; existing unused
tokens remain valid, while previously consumed tokens without a child link retain
replay revocation behavior. `REFRESH_REUSE_GRACE_SECONDS = 60` allows one retry of a
consumed token before 60 seconds elapse, only while its family is active and its
original child refresh token is unused. The retry marks that child used, issues a
fresh pair in the same family, and records `refresh_grace` without secrets. The
original child link stays fixed to block a second grace redemption. Other reuse
revokes the family and returns `401`; clients must still serialize refreshes.
Only SHA-256 token hashes reach SQLite. Refresh rotation is transactional, including
across connections; consumed hashes are retained for replay detection. Hourly
housekeeping retains used refresh rows and their child links for the full grace
window, even if their original expiry passes. Afterward it replaces them with
minimal `refresh_replays` hash/family markers, and removes expired unused refresh
tokens, expired access tokens, and revoked families older than 30 days. The markers preserve
replay detection while credentials remain live. Password hashing and housekeeping
run off the asyncio loop. Family metadata uses the resolved client IP: trusted
peers may supply `X-Real-IP`, with a right-to-left untrusted-hop X-Forwarded-For
fallback. Untrusted peers cannot override their IP. Uvicorn proxy handling is disabled
by the runner so the app always sees the TCP peer.

`sharing.py` owns additive `strips`, `strip_access`, `strip_settings`,
`user_notifications`, `alert_preferences`, `event_reads`, `strip_claims` and
`sharing_migrations` tables. Claims, ownership transfer and migration are transactional.
The existing events schema is unchanged: new actors live in `params.actor`.

`_Web` resolves `_Web.current_user` (also `request.state.current_user`),
`request.state.session_family_id`, and `request.state.auth_method` once per request.
Account methods are `bearer` or `cookie`; `legacy` has no user and is a full strip-access
bypass. Self-specific routes (claim, leave, personal notifications) need an account.
`API_POLICIES` / `STRIP_POLICIES` register every domain route with an explicit policy;
dispatch refuses unregistered routes or unrecognized policies before calling handlers.
Permission checks read SQLite on every request, and rule moves check both MACs.
List handlers and SQL event queries filter by access, including `/api/debug`.
There is no permission cache. See [the API contract](../API.md#ownership-and-permissions)
for role/status details and the first-strip fallback for mixed-currency totals.
The physical-button claim still relies on the firmware's plaintext
device protocol; it is not cryptographic device authentication.

`ratelimit.py` has configurable constants for login (20/IP/10 min and phone backoff
after 5 failures: 1, 2, 4, 8, then 15 min), registration (3 accounts/IP/hour), refresh
(60/IP/10 min), claim (5/user/hour), all access writes (20/user/hour), and other API
requests (120/user/minute, or IP for anonymous/legacy), WebSocket connection attempts
(30/IP/minute), and push-token writes (20/user/hour). HTTP responses are `429` with
`{"error":"too many requests"}` and integer `Retry-After` seconds. Unknown phones
follow the same dummy password verification/backoff path. Success resets the phone
penalty; 24 idle hours also expire it. Other idle keys expire after their window.
State is bounded to 10,000 keys per process: at capacity new keys are rejected,
never allowed to evict a live penalty. Restarting resets all counters; multiple
workers have separate limits. Use Cloudflare edge rules as an additional layer.

`audit.py` owns the additive `audit_log` table. Account, session, claim, sharing,
ownership and strip-settings actions are recorded without credentials. Unknown
phone failures use a normalized phone hash. Rate blocks are sampled once per key
per minute. `GET /api/me/security-log?limit=50&before_id=...` exposes only the signed-in
account's rows. Retention deletes rows older than 180 days daily. The housekeeping
worker starts immediately, checks claim expiry each minute, and performs token and
audit cleanup hourly/daily. Shutdown waits at most 10 seconds for rule actions,
then cancels remaining actions before SQLite closes.

The public UI uses `web/app.js` and `web/app.css`, with ETags for revalidation.
Every app response gets the strict CSP documented in [API.md](../API.md#security-headers),
nosniff, no-referrer, same-origin COOP and CORP. There are no inline script/style
exceptions: interactions use delegated actions, fixed styles use CSS classes, and
chart dimensions use finite numeric CSSOM properties. Server data is escaped in
HTML templates. The app and runner send no Server header; uvicorn owns Date.
HSTS remains on Caddy. Public provisioner/APK downloads remain available.

The stdlib-only provisioner also works on Python 3.8+ / Termux:

```sh
python ../tools/provision.py provision --ip 192.168.1.50 --ssid WIFI --password PW
# The "provision" word is optional.
```

The tests port every legacy selftest assertion and add HTTP, asset, provisioning,
account/session/CSRF, full role matrices, claims, sharing, per-user notifications,
per-strip alarms/budgets, migration and old/new storage compatibility checks. They use temporary
data and fake strips connected over real local TCP sockets. Legacy response parity
excludes the intentionally public page and account/sharing additions.

Live updates use `GET /api/ws` with Bearer auth for apps, or the `powerk_access`
cookie plus an exact same-origin check for browsers. In HTTPS deployments enable
`--secure-cookies` so the browser Origin is checked against HTTPS even behind Caddy.
Explicit legacy `X-Token` / `?t=` credentials also work; Basic and the legacy cookie
are not WebSocket credentials. Rejected connections complete the handshake only to
send close code 4401 (authentication) or 4429 (limits), without sending state.

`realtime.py` sends the scoped `/api/state` snapshot as `type: state`, complete
changed strips as `type: strip`, new visible events as `type: event`, access-set
invalidation as `type: access`, and an application `ping` every 25 seconds. It
samples cached device state every 250 ms (no additional strip commands), ignores
timestamp/current-only changes and power changes below 1 W, and coalesces pending
strip updates. The per-connection queue holds at most 32 messages; overflow or a
send blocked for 5 seconds closes with 4408. Sends are spaced by at least 250 ms.
There are at most five sockets per account and per resolved IP; legacy sockets
share one account bucket. These bounds are per process, like HTTP rate limits.
Run a single worker because the device Hub is also process-local.

Permissions and the original opening token are rechecked before each send and
every 250 ms, even with no device activity. Revocation/refresh replay/password
changes also trigger an API-layer recheck and push-token cleanup. Password changes
retain the caller's family as before. An opening access token expires after 15
minutes: the socket closes with **4401**, even if that family has refreshed since
connection. Refresh once via HTTP and reconnect with the new credential. Commands
remain HTTP. There is no event replay cursor on the socket; refetch `/api/events`
after reconnect when the activity screen is visible. See [the protocol](../API.md#get-apiws-websocket-upgrade).

The web UI prefers the socket for accounts, polls every 2 seconds while it is down,
and reconnects with exponential backoff/jitter. Legacy browser sessions continue
polling. A 55-second heartbeat watchdog catches silent failures; logging out clears
the socket and reconnect timers. CSP stays strict with `connect-src 'self'` (the
[CSP3 matching rule](https://www.w3.org/TR/CSP3/#match-url-to-source-expression)
covers same-host/port ws/wss). Node tests exercise fallback, access invalidation,
and HTTP/live-update races; a local TCP test checks the uvicorn upgrade and codes.

`push.py` adds `push_tokens` with user, platform, app version, creation/last-seen time,
and session-family ownership. Registration is transactional, capped at ten devices
per user, and records only a short token hash in the audit log. Re-registering a
device updates its session family; moving it to another account stops pushes for
its old account. Logout/revocation deletes that family's registrations. Push tokens
are stored in SQLite because FCM needs their original values; protect DB backups.

`fcm.py` uses pinned `cryptography==50.0.2` for RS256 OAuth assertions, stdlib HTTPS,
and a two-thread pool bounded to 64 outstanding recipient jobs (new work is dropped
when full). OAuth is cached until five minutes before expiry. HTTP 5xx/429 retry at
most three times with backoff; 429 waits at least 60 seconds and respects Retry-After
up to 60 seconds. Invalid tokens are deleted; generic malformed-payload errors do
not delete registrations. Access/preferences/session ownership are checked again
before delivery and retries. Tests inject the HTTP transport and wait function, so
OAuth and FCM tests never reach the network. Shutdown cancels queued work and waits
for active HTTP calls (10-second timeout). Uvicorn uses pinned `websockets==17.2`
through its sans-IO adapter; there are no additional dependencies.
