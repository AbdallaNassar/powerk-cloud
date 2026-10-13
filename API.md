# powerk HTTP API (v2)

JSON over HTTP, served by the FastAPI package (`python -m powerk serve`) on the web port (default 8080).
The original `powerk.py` remains a rollback server with the old shared-token contract.

## Conventions

- **Auth.** Every `/api/*` endpoint requires an account session or a valid legacy shared token,
  except `POST /api/auth/register`, `POST /api/auth/login`, and `POST /api/auth/refresh`.
  **Omitting `--token` no longer opens the API.** Apps send `Authorization: Bearer <access_token>`;
  the web UI uses cookies and CSRF protection (see below). An invalid/expired session returns `401`.
  The optional `--token` still grants full strip access via `X-Token`, HTTP Basic (user `powerk`,
  password = token; the old token-as-user form also works), `?t=`, or `powerk_t`.
  Legacy failures retain `401 {"error":"token required"}` and the Basic challenge; requests with
  `X-Powerk-Client: web` get `{"error":"session required"}` without a browser Basic-auth prompt.
- **Bodies.** `POST` and `PUT` bodies are JSON objects and need `Content-Type: application/json`;
  otherwise the server returns `415`. `DELETE` takes no body.
- **Errors.** Every error is `{"error":"<human readable>"}` with a 4xx/5xx status code:
  - `400`: bad field or query parameter
  - `401`: missing, expired, invalid or revoked credentials
  - `403`: insufficient strip role (`{"error":"forbidden"}`), CSRF failure or registration closed
  - `404`: unknown path, rule or strip
  - `409`: phone already registered or a claim is already pending
  - `410`: account users requesting the retired global settings endpoint
  - `415`: wrong content type
  - `429`: `{"error":"too many requests"}`, with an integer `Retry-After` header in seconds
  - `502`: command sent but the outcome is unknown
  - `503`: strip offline
- **Values.**
  - Times are integer Unix seconds and need a 64-bit integer (`Long` in Kotlin).
  - MACs are 12 uppercase hex digits.
  - Booleans must be real JSON booleans; the string `"false"` is rejected.
  - Clients must ignore unknown response fields.
- **Local time.** Server local time defines days, months and schedules. `/api/state` returns
  `server_time` and `utc_offset_seconds` so a client can show times the way the server sees them.
- **Polling.** `/api/state` returns cached state and never waits for the strip, so polling it every few
  seconds is cheap. Load rules, history, settings and events when their screen opens, and again after a
  change. Account clients can use `/api/ws` for live changes; the web UI polls every 2 seconds while
  disconnected. HTTP remains the command transport.

## Accounts and sessions

Accounts see only strips they own or have been given access to. New accounts start with no strips.
Open registration is the default; disable it with
`--no-open-registration` (existing accounts can still log in), or enable it with `--open-registration`.

Phone numbers are usernames, with **no SMS, OTP or verification**. Spaces, hyphens and parentheses
are removed. Accepted forms are `+` followed by 8–15 ASCII digits (first digit nonzero), or an
11-digit Egyptian mobile `01XXXXXXXXX`, normalized to `+201XXXXXXXXX`. Other input returns `400`.
Passwords have 10–128 characters. Common passwords (case-insensitive local list) and the phone
number itself (international digits, `+` form or Egyptian local form) are rejected. Passwords are
hashed with Argon2id and rehashed at login when parameters change.

### Token delivery and cookies

For Android and other API clients, registration, login and refresh return:

```json
{"user":{"id":1,"phone":"+201001234567","created_at":1800000000},
 "access_token":"<opaque random token>","refresh_token":"<opaque random token>","expires_in":900}
```

Access tokens last **15 minutes**. Refresh tokens last **30 days from issue**; each successful refresh
consumes that refresh token and issues a new pair in the same family. Clients must serialize refreshes.
Access tokens already issued in that family remain valid until their expiry or family revocation.

For a lost refresh response, `POST /api/auth/refresh` allows **one retry per consumed token before
60 seconds have elapsed since its rotation**, provided the family is not revoked and the child
refresh token issued by that rotation has not been used. The retry invalidates that child refresh
token, returns a fresh pair in the same family, and records a secret-free `refresh_grace` audit event.
A second retry of that parent, reuse at or after 60 seconds, or reuse after the child was consumed
returns `401` and revokes the whole family, including its access tokens. Consumed tokens from before
the grace migration (without a recorded child) retain this revocation behavior.

Web clients send `X-Powerk-Client: web` on login/register/refresh. They receive only
`{"user":{...},"expires_in":900}` in JSON; **raw tokens are omitted from web responses** and delivered
as cookies. Cookie-based refresh selects this web response automatically. Other clients receive the
tokens in JSON and no cookies. All auth JSON responses use `Cache-Control: no-store`.

| Cookie | Path | HttpOnly | SameSite | Max-Age |
|---|---|---|---|---|
| `powerk_access` | `/` | yes | Strict | 900 |
| `powerk_refresh` | `/api/auth/` | yes | Strict | 2592000 |
| `powerk_csrf` | `/` | no | Strict | 2592000 |

All three gain `Secure` with `--secure-cookies`; enable that flag behind HTTPS. The flag is off for
local HTTP development. The CSRF value remains stable across cookie refreshes and changes on login.
Every non-GET request authenticated by an account cookie must send `X-CSRF-Token` equal to
`powerk_csrf`, including bodyless DELETEs and refreshes that use the refresh cookie. Login/register
also require it when an access cookie is present. Missing or mismatching values return
`403 {"error":"CSRF token required"}`. Bearer credentials, an explicit refresh token in the JSON
body, and the legacy shared-token mechanisms do not require CSRF. An invalid Bearer credential
never falls back to an access cookie. POST/PUT still require `Content-Type: application/json`.

### Endpoints

All times below are integer Unix seconds. A user is `{id, phone, created_at}`. Errors have the same
`{"error":"..."}` envelope as the rest of the API; validation returns `400`, never FastAPI `422`.

| Method and path | JSON request | Success | Errors |
|---|---|---|---|
| `POST /api/auth/register` | `{"phone":"01001234567","password":"a long uncommon password"}` | `201`, user + token pair (or web cookies) | `400`, `403` registration closed/CSRF, `409` duplicate phone, `415` |
| `POST /api/auth/login` | `{"phone":"+201001234567","password":"..."}` | `200`, user + token pair (or web cookies) | `400`, `401`, `403` CSRF, `415` |
| `POST /api/auth/refresh` | `{"refresh_token":"..."}`, or `{}` to use the cookie | `200`, new pair in the same family | `400`, `401` invalid/expired/replayed/revoked, `403`, `415` |
| `POST /api/auth/logout` | `{}` | `200 {"ok":true}`, revokes current family and clears cookies | `401`, `403`, `415` |
| `GET /api/auth/me` | none | `200 {"user":{...}}` | `401` |
| `POST /api/auth/password` | `{"current_password":"...","new_password":"..."}` | `200 {"ok":true}`, revokes all **other** families | `400`, `401`, `403`, `415` |
| `GET /api/auth/sessions` | none | `200 {"sessions":[{"id":"...","created_at":1800000000,"last_used_at":1800000100,"user_agent":"...","ip":"...","current":true}]}` | `401` |
| `DELETE /api/auth/sessions/{id}` | none | `200 {"ok":true}`, revokes that family; clears cookies if current | `401`, `403`, `404` |

Unknown phone and wrong password both return exactly `401 {"error":"wrong phone or password"}`.
An unknown phone still verifies against a fixed dummy Argon2id hash. Existing-phone registration
returns `409 {"error":"phone already registered"}`. Closed registration returns
`403 {"error":"registration is closed"}`.

Each registration/login creates a separate family. The session list includes only the user's active
families (with an unexpired refresh token); its `last_used_at` updates on authenticated access and
refresh. The IP uses the trusted-proxy rules below. Deleting another
user's family, a missing family, or an already revoked family returns `404`. A legacy shared token
does not identify a user, so the account-management endpoints require an account session.

## GET /api/state

```json
{
  "api_version": 2, "server_time": 1760190000, "utc_offset_seconds": 10800,
  "local_ip": "192.168.1.50", "port": 10086,
  "currency": "EGP", "price_kwh": 2.14, "budget": 500.0,
  "month_kwh": 12.3, "month_cost": 26.32,
  "unread_alerts": 2,
  "devices": [{
    "mac": "AABBCCDDEEFF", "name": "MTTL CDDEEFF", "label": "Desk", "role": "owner",
    "currency": "EGP", "price_kwh": 2.14, "budget": 500.0,
    "model": "lgutap", "fw": "0.1.54-1.0.66", "ip": "192.168.1.77",
    "online": true, "reported_at": 1760189998,
    "on": true, "power_w": 61.2, "energy_kwh": 3.21,
    "voltage": 221.7, "current_a": 0.28, "rssi": -56,
    "today_kwh": 0.42, "month_kwh": 12.3, "month_cost": 26.32,
    "alarms": ["temp_high"], "alarm": "temp_high",
    "outlets": [{
      "n": 1, "name": "Fridge", "on": true, "power_w": 61.2, "energy_kwh": 3.2,
      "temp_c": 31,
      "alarms": [], "alarm": null
    }]
  }]
}
```

- **Names.** `name` is the default strip name. `label` is the custom name, or `""` when none is set.
  Show `label` if it is set, otherwise `name`. An outlet `name` of `""` means "Outlet N".
- **`outlets`** always lists outlets 1 to 4. Find an outlet by its `n`, never by its list position.
- **Offline strips.** Strips the server has seen before stay in `devices` with `online: false` after a
  restart. Their readings are the last known values, which may be startup defaults.
  `reported_at` is `null` until the first reading.
- **Alarms.** `alarms` lists active alarms: `temp_high` (outlet temperature ≥ `temp_max_c`) and
  `power_high` (strip total ≥ `power_max_w`; device level only). The strip's own overload/overheat
  fields are protection settings, not trips, so they are not reported. Treat unknown codes as generic
  alarms.
  `alarm` is the first entry of `alarms`, or `null`.
- **Energy totals.**
  - `today_kwh` and `month_kwh` cover the server-local calendar day and month.
  - Account responses include only accessible strips; unclaimed strips are hidden. Each has a
    `role` (`owner`, `control`, `viewer`), `currency`, `price_kwh`, and `budget`.
  - When all visible strips have the same currency, top-level `month_kwh` and `month_cost` sum
    those strips, using each strip's own price. Top-level currency, price and budget use the first
    visible strip. When currencies differ, **all five top-level fields use the first visible strip**;
    no currency conversion or addition of unlike currencies is performed. Use per-strip values
    for multi-currency displays. With no accessible strips, totals are zero and defaults are returned.
  - Budget alerts compare each strip's month cost with that strip's budget, independently.
  - Legacy credentials see every known strip (including unclaimed ones), reported with `role: owner`.
  - `month_cost` is `month_kwh` × `price_kwh`. It is an estimate, not a bill.

## GET /api/ws (WebSocket upgrade)

Connect to the same server using `ws://` for local HTTP or `wss://` for HTTPS.
Supported credentials are:

- Apps: `Authorization: Bearer <access_token>` in the upgrade request. An invalid Bearer
  credential never falls back to cookies or legacy credentials.
- Browsers: `powerk_access` plus an `Origin` with the page's scheme, Host and port.
  Missing, `null`, cross-site, wrong-scheme or wrong-port Origins are rejected. Use
  `--secure-cookies` behind HTTPS/Caddy; forwarded scheme headers are not trusted.
- Legacy: the configured `--token` explicitly in `X-Token` or `?t=`. Basic and `powerk_t`
  are not accepted by this endpoint. Query credentials may appear in proxy access logs.

Authentication failure closes with **4401**. The server completes the upgrade to transmit
this close code; it sends no snapshot on rejected connections. A normal HTTP GET without
an upgrade is not a substitute for connecting a WebSocket.

Messages are UTF-8 JSON objects, one object per text frame. Ignore unknown fields/types.
The first message is the complete, account-scoped `GET /api/state` response plus `type`.
For example, a new account receives:

```json
{"type":"state","api_version":2,"server_time":1800000000,"utc_offset_seconds":10800,
 "local_ip":"192.0.2.1","port":10086,"currency":"EGP","price_kwh":2.14,"budget":null,
 "month_kwh":0,"month_cost":0,"unread_alerts":0,"devices":[]}
```

Later messages:

| Type | Contents | Client action |
|---|---|---|
| `strip` | `strip`: one complete device object, with exactly the fields used inside `/api/state.devices` | Replace/upsert by MAC, including names, outlets, readings, alarms and role; recompute display totals from visible strips using the same mixed-currency rule as `/api/state` |
| `event` | The event fields from `/api/events`, flattened into the frame, plus `unread_alerts` | Update the badge/activity view; event `id` can deduplicate HTTP results |
| `access` | No private strip identifiers | Refetch `/api/state`; access was gained or lost |
| `ping` | `server_time` and the current `unread_alerts` | Heartbeat and badge synchronization; no response required |

```json
{"type":"event","id":42,"ts":1800000000,"level":"alert","code":"temp_high",
 "mac":"AABBCCDDEEFF","outlet":2,"text":"Desk / Outlet 2: temp high 61 C",
 "params":{"temp_c":61,"watts":12,"actor":"strip"},"unread_alerts":1}
```

```json
{"type":"access"}
```

```json
{"type":"ping","server_time":1800000025,"unread_alerts":1}
```

The `strip` envelope is `{"type":"strip","strip":Device}` where `Device` is the **full**
device object in the state example above (not a partial patch). A role change emits a strip
update; gaining/losing a MAC emits `access`. Every outgoing frame rechecks current access,
including frames already queued. Removed members stop receiving that strip and its events;
unclaim removes access for everyone. Legacy connections retain their all-strip bypass.

Cached strip state is sampled every 250 ms; there are no extra device polls. A strip frame is
queued only on visible change. Power changes must reach **1 W** from the last queued reading
(at strip or outlet level); `reported_at` and derived `current_a` alone do not trigger a frame.
Other visible fields, including names, role, online state, temperature, alarms and energy totals,
are compared. Repeated pending changes to the same strip coalesce into its latest state.
Event frames remain separate and ordered by ID; they are not merged.

Frames are spaced by at least 250 ms (about four per second per socket). Each socket has a
32-message queue and a five-second send deadline. Backlog overflow or a stalled send disconnects
the consumer. A `ping` is queued every 25 seconds; clients should reconnect if no frames arrive
for about 55 seconds. This is an application heartbeat, separate from protocol-level ping/pong.
Clients may send `pong` or `{"type":"pong"}`; all commands still use HTTP.

| Close code | Meaning | Recovery |
|---|---|---|
| `4401` | Missing/invalid credentials, session-family revocation, or expiry of the **opening access token** | Refresh once through HTTP, then reconnect with the new token/cookie; failed refresh returns to login |
| `4429` | Connection attempt rate limit or simultaneous socket cap | Back off with jitter; avoid opening a socket per screen |
| `4408` | Queue full or send exceeded five seconds | Reconnect, replace state from the initial snapshot, and reload events as needed |
| `1008` | Client sent an unsupported application message | Use HTTP for writes; the feed is read-only |
| `1001` | Server shutdown | Reconnect with backoff |

Limits are **five sockets per user and per resolved client IP**, and 30 connection attempts
per IP/minute, including rejected attempts. Legacy sockets share a single user bucket. Limits
are per process. Auth mutations also invalidate open sockets from the API layer; even idle
sockets check token/family validity every 250 ms. Password changes revoke other families only,
matching the existing HTTP session contract. **Refreshing does not extend an existing socket**:
the token used to open it still expires after 15 minutes, even if newer tokens exist in that family.

Commands such as `/api/onoff` stay on HTTP; confirmed device changes and command events also
arrive over the socket. There is no durable socket replay cursor. After reconnect, use the
initial state and reload `/api/events` if history matters. FCM and sockets may both announce
the same event; deduplicate by ID. The web UI uses backoff with jitter, pauses polling only
after receiving a socket snapshot, and retains two-second polling whenever the socket is down.

`connect-src 'self'` remains unchanged: [CSP3 same-origin matching](https://www.w3.org/TR/CSP3/#match-url-to-source-expression)
permits same-host/port HTTP→WS and HTTPS→WSS. Caddy's existing proxy supports upgrades;
see the [deployment transport notes](deploy/README.md#websocket-transport).

## POST /api/onoff

Request: `{"mac":"AABBCCDDEEFF","outlet":0,"on":true}`. Outlet `0` means all four outlets.

Response: `{"ok":true,"confirmed":true}`.

- `ok: true` means the commands were sent.
- `confirmed` is `true` only when a fresh reading shows every requested outlet in the requested state.
  When `confirmed` is `false`, the outcome is unknown. Never retry an unknown outcome as a toggle.
- Errors: `400` for a bad body, `503` when the strip is offline, `502` when the command was sent but
  the outcome is unknown.
- Account users also receive `403` for a viewer or `404 {"error":"unknown strip"}` for no access.
- Allow at least 15 s before a client read timeout. The server can wait up to 10 s.

## POST /api/name

Request: `{"mac":"…","outlet":0,"name":"Desk"}`. Outlet `0` names the strip itself.

- An empty name resets to the default.
- A name can have up to 40 characters.
- The strip must be one the server knows.

Response: `{"ok":true}`.

## Rules

Rules run on the server, so they keep working while the phone is off.

### Rule object

```json
{
  "id": "r_ab12cd", "kind": "schedule", "mac": "AABBCCDDEEFF",
  "outlets": [1, 2, 3, 4], "enabled": true, "label": "",
  "next_at": 1760190000, "phase": null
}
```

The kind-specific fields follow, each with the API values allowed:

| kind | fields |
|---|---|
| `schedule` | `"at":"07:30"` (24 h), `"days":[0..6]` (0 = Monday), `"on":true` |
| `timer` | create with `"minutes":1-10080` and `"on"`. The server stores `"fire_at"` (epoch s). |
| `cycle` | `"on_min":1-1440`, `"off_min":1-1440` |
| `autooff` | `"below_w":0-3500` (W, must be more than 0), `"for_min":1-1440` |

- `outlets` is a non-empty list of numbers from 1 to 4. Sending `[0]` means all four outlets.
- `label` is optional and can have up to 40 characters.
- These fields are computed by the server and are never sent by a client:
  - `id`
  - `next_at`: the next action time as an epoch, or `null` when the rule is disabled or has none pending.
    For an autooff rule, `next_at` is the time the outlet switches off if the low draw continues.
  - `phase`: for a cycle only, the phase the server intends (`"on"` or `"off"`). It is not the observed
    relay state.

### Behavior

- **schedule:** fires once in its local minute, on the listed weekdays. If the strip is offline at that
  time, the server logs `rule_skipped` and does not replay the action later. For an overnight period,
  use two rules.
- **timer:** fires once at `fire_at`, then deletes itself.
  - If the strip is offline, the server waits up to 5 minutes, then logs `rule_skipped`.
  - The timer is consumed before the command is sent, so a crash never replays it.
  - A PUT with `minutes` sets a new deadline from now.
- **cycle:** starts with ON as soon as it is enabled, created or edited, then alternates. After a server
  restart, the cycle starts again with ON.
- **autooff:** checks each listed outlet on its own. When an outlet is ON and draws less than
  `below_w` for `for_min` minutes of fresh readings, the server switches only that outlet off and logs
  `autooff`.

### Endpoints

| Method and path | Request | Response |
|---|---|---|
| `GET /api/rules?mac=…` (`mac` optional) | none | `{"rules":[Rule…]}` |
| `POST /api/rules` | a rule without `id`, `next_at` or `phase` | `{"ok":true,"rule":Rule}`, or `400 {"error"}` |
| `PUT /api/rules/<id>` | a partial update, for example `{"enabled":false}` | `{"ok":true,"rule":Rule}`. A missing id returns `404`. |
| `DELETE /api/rules/<id>` | none | `{"ok":true}` |

- `PUT /api/rules/<id>` validates the merged rule. A rule's `kind` cannot change. Editing a rule
  restarts its runtime, so a cycle starts again with ON.
- Account rule lists are filtered by strip access. Supplying an inaccessible `mac`, or updating or
  deleting a rule on an inaccessible strip, returns `404 {"error":"unknown strip"}`. A missing rule
  also uses that response for accounts. Creation/update/deletion require owner/control (`403` for
  viewers). Changing a rule's `mac` checks control permission on **both** strips.
- Sending the same `POST` twice creates two rules. Do not retry it blindly.

## GET /api/history?mac=…&range=day|week|month|year[&outlet=1-4]

`mac` is required and must be a strip the server knows.

| range | covers | buckets |
|---|---|---|
| `day` | the last 24 hours | 24 hourly buckets |
| `week` | 7 local days, including today | daily |
| `month` | 30 local days, including today | daily |
| `year` | 12 calendar months, including this month | monthly |

```json
{"range":"week","unit":"day","currency":"EGP",
 "buckets":[{"t":1760131200,"kwh":0.42,"cost":0.9}],
 "total_kwh":3.1,"total_cost":6.63,
 "per_outlet":[{"n":1,"kwh":1.2},{"n":2,"kwh":0},{"n":3,"kwh":1.9},{"n":4,"kwh":0}]}
```

- `t` is the local start of a bucket. A bucket with no data shows `0`.
- Energy comes from deltas of the strip's own counter.
- While the strip is offline and the server retains its counter baseline, the energy it used is
  spread over the hours of the gap when it reconnects. The first reading after a server restart
  establishes a new baseline; usage during server downtime is not recovered.
- Costs use the current flat `price_kwh`.

## Settings

`GET /api/settings`:

```json
{"currency":"EGP","price_kwh":2.14,"budget":500.0,"temp_max_c":60,"power_max_w":3500,
 "ntfy_url":"https://ntfy.sh/my-topic","telegram_chat":"12345","telegram_configured":true}
```

`PUT /api/settings` takes a partial body and returns the same shape as GET.

| field | values |
|---|---|
| `currency` | 1 to 8 characters |
| `price_kwh` | 0 to 1000 |
| `budget` | a monthly amount in the currency, or `null` to switch it off |
| `temp_max_c` | 30 to 120 |
| `power_max_w` | 100 to 10000 |
| `ntfy_url` | an `http(s)` URL, or `""` |
| `telegram_chat` | text |
| `telegram_token` | write-only text: leave it out to keep the saved token, send `""` to clear it, send text to replace it |

This compatibility endpoint is **legacy-token only**. Accounts receive
`410 {"error":"use /api/strips/{mac}/settings and /api/me/notifications"}` on both GET and PUT.
Legacy strip-setting updates apply across all claimed strips and update the global defaults used by
unclaimed strips. Owners can subsequently customize individual strips. Before migration, global event
pushes remain available while `--token` is configured, independently of account preferences.
Migration records `meta.accounts_migrated` in `powerk.json`; with this marker, events use only personal
channels, preventing duplicate pushes to copied destinations. Legacy notification tests still use globals.
Unknown fields return `400`. The original global settings remain in `powerk.json` for rollback.

## Ownership and permissions

| Action | owner | control | viewer |
|---|:---:|:---:|:---:|
| State, history, events, rules list, strip settings GET | yes | yes | yes |
| Switch outlets, change names, create/update/delete rules | yes | yes | no |
| Change strip settings, view/manage access, transfer, unclaim | yes | no | no |
| Leave | no | yes | yes |

Every strip operation checks access on each request. No access yields
`404 {"error":"unknown strip"}`, whether the MAC exists or not; insufficient role yields
`403 {"error":"forbidden"}`. `/api/state`, `/api/rules`, `/api/events`, and `/api/debug` lists
are filtered rather than failing when empty. `/api/debug` returns diagnostics only for visible strips.
`GET /api/rules?mac=...`, `GET /api/events?mac=...`, and history check the explicit MAC.
The legacy token bypasses strip role checks. Account-only operations (claim/status, leave, and
`/api/me/notifications`) require an account session (`401` for legacy), as do account-management routes.
Ownership changes are atomic: exactly one owner is stored in both `strips.owner_id` and `strip_access`.
`--mac` remains an optional extra TCP allowlist; claims and roles enforce account ownership.

### Claim a strip

`POST /api/strips/claim {"code":"9B25F1A"}` takes exactly seven hexadecimal characters,
case-insensitive: the MAC suffix in the setup Wi-Fi name `TONLY_TAP_XXXXXXX` or on the strip label.
The online, unclaimed strip must be uniquely identified. Success is
`200 {"claim_id":"<opaque id>","expires_in":60}`. Only one pending claim per strip is allowed:
another attempt (including the same account) returns `409 {"error":"claim already pending"}`.
Malformed codes return `400`. Unknown, offline, already-claimed and ambiguous codes all return
`404 {"error":"no unclaimed online strip with this code"}`.

The first physical button event `up:event:onoff:<0-4>:on|off` within the 60-second window assigns
ownership. **Pressing a button switches an outlet; you can switch it back.** Command acknowledgments
and ordinary state readings do not complete a claim. Poll `GET /api/strips/claim/{claim_id}`:
`200 {"status":"pending"}`, `200 {"status":"done","mac":"..."}`, or `200 {"status":"expired"}`.
Only the claimant can read it; missing/other users' IDs return `404 {"error":"unknown claim"}`.
Pending claims and expiry survive server restarts. Unclaim expires earlier claim receipts as well.

Unclaimed strips remain connected and polled; their rules, names and energy history are kept.
Account users cannot see them. TCP port 10086 accepts at most eight simultaneous connections per
source IP, including connections that have not yet announced a MAC; excess connections are closed
and logged. Claim/share HTTP rate limits apply as listed below.

### Sharing and ownership changes

All successful changes below return `200 {"ok":true}`. Common errors are `401`, `403`, `404`,
`400` invalid fields, and `415` for POST/PUT without JSON; cookie writes also require CSRF.
Phones use the same normalization as login.

| Method and path | Body / response | Notes |
|---|---|---|
| `GET /api/strips/{mac}/access` | `{"access":[{"user_id":1,"phone":"+201001234567","role":"owner","added_at":1800000000}]}` | Owner only; includes owner |
| `POST /api/strips/{mac}/access` | `{"phone":"...","role":"control"}` or `viewer` | Grant/update an existing account; an unregistered phone does nothing and returns the identical 200 body. Sharing to the owner is also a no-op. |
| `PUT /api/strips/{mac}/access/{user_id}` | `{"role":"control"}` or `viewer` | Owner only; changing self or the owner returns 403; missing target 404 |
| `DELETE /api/strips/{mac}/access/{user_id}` | none | Owner only; removing self or the owner returns 403; missing target 404 |
| `POST /api/strips/{mac}/leave` | `{}` | Control/viewer only; owner must transfer or unclaim (403) |
| `POST /api/strips/{mac}/transfer` | `{"phone":"..."}` | Owner only; target must already have access or 404 `unknown strip`; target becomes owner and former owner becomes control; transfer to self returns 403 |
| `DELETE /api/strips/{mac}` | none | Owner only; removes ownership, every access row, strip settings and strip alert preferences. Keeps names, rules and history. Next claim starts with defaults. |

Granting `owner` via either access-write endpoint returns `400`. Access changes take effect on the
next request using the same account session; no logout/login is necessary.

### Per-strip settings

`GET /api/strips/{mac}/settings` is available to any role. `PUT` requires owner and accepts a
partial object containing only `currency`, `price_kwh`, `budget`, `temp_max_c`, and `power_max_w`.
Both return those five fields. Validation uses the ranges above; unknown keys return `400`.
New claims default to `EGP`, `2.14`, `null`, `60`, `3500`, respectively. Limits, history estimates,
state costs and budget alarms use the strip's settings. Legacy unclaimed strips use global settings
until claimed or migrated.

### Personal notifications

`GET /api/me/notifications` returns the current user's channels and preferences for accessible strips:

```json
{"ntfy_url":"https://ntfy.sh/my-topic","telegram_chat":"12345","telegram_configured":true,
 "fcm":{"enabled":true,"devices":2},
 "alerts":{"AABBCCDDEEFF":{"offline":true,"online":false,"temp_high":true,"power_high":true,
 "budget":true,"rule_fired":false,"rule_skipped":true,"rule_failed":true,"autooff":false,
 "onoff":false,"name_changed":false,"rule_created":false,"rule_updated":false,"rule_deleted":false}}}
```

`PUT` accepts partial channel fields and a partial `alerts` map, then returns the GET shape.
For example `{"alerts":{"AABBCCDDEEFF":{"online":true,"temp_high":false}}}` changes only those
two preferences. Values must be booleans and codes must be known (`400`); any inaccessible strip
returns `404` and **none** of the changes are saved. `telegram_token` stays write-only: omitted keeps,
`""` clears, nonempty text replaces it. New accounts have empty channels. Defaults enable warn/alert
codes and disable info codes; recipients are resolved from current access at event creation.
Each user's enabled channels are sent in background threads, without blocking strip commands.
`fcm` is read-only: `enabled` reports server configuration and `devices` counts the user's
registered devices with active session families. Device registration is allowed when FCM is
disabled, so the app need not special-case server configuration. FCM uses the same access and
per-code preferences as ntfy/Telegram, including default alert preferences before the user has
ever saved channel settings. Delivery/retries recheck access, preferences and registration ownership.

### Push device registration

These endpoints require an account (Bearer or cookie+CSRF), with a shared write limit of
20 attempts/user/hour. Legacy credentials receive `401`.

| Method and path | Request | Success |
|---|---|---|
| `POST /api/me/push-tokens` | `{"token":"<FCM registration token>","platform":"android","app_version":"1.0.0"}` | `200 {"ok":true}` |
| `DELETE /api/me/push-tokens/{token}` | No body; URL-encode the token as a path segment | `200 {"ok":true}`, or `404` for missing/another user's token |

Tokens must be 1–4096 ASCII letters/digits or `_`, `:`, `.`, `-`; platform must be `android`.
`app_version` is optional (default `""`), up to 64 characters. Bad fields return `400`.
POST upserts a token, updates last-seen/version and associates it with the **calling session
family**. Register after login and when Firebase rotates the device token; a normal refresh
retains the family and needs no registration write. Switching accounts reassigns that device
to the new account and stops the old account's pushes. At most ten tokens are retained per user;
registration beyond ten evicts the oldest by creation time (ties use insertion order).

Logout, explicit session revocation, password-change revocation of other families, and refresh
replay revocation delete those families' tokens. FCM rejection of a token as unregistered/invalid
also deletes it. Generic invalid-payload errors do not delete otherwise valid tokens. Explicit
registration and all deletion paths audit only a 16-character SHA-256 prefix, never the token.
The device token itself must be stored in SQLite for delivery; it is not an API access credential.

### FCM payload contract for Android

The optional server configuration is `--fcm-service-account PATH` or
`POWERK_FCM_SERVICE_ACCOUNT`. If unset, only FCM is disabled. With it, the server signs an
RS256 service-account JWT for Google's OAuth token endpoint with the
`https://www.googleapis.com/auth/firebase.messaging` scope, caches the resulting access token,
and sends [FCM HTTP v1 messages](https://firebase.google.com/docs/reference/fcm/rest/v1/projects.messages).
Credentials are never returned or logged. Example wire payload:

```json
{"message":{"token":"<device-token>",
 "notification":{"title":"powerk: temp high","body":"Desk / Outlet 2: temp high 61 C"},
 "data":{"type":"event","mac":"AABBCCDDEEFF","outlet":"2","event_id":"42","code":"temp_high"},
 "android":{"priority":"HIGH","collapse_key":"AABBCCDDEEFF:temp_high",
  "notification":{"channel_id":"alerts","tag":"AABBCCDDEEFF:temp_high"}}}}
```

All `data` values are **strings**. Android must handle:

| Field | Contract |
|---|---|
| `type` | `event` for activity/alerts, `test` for the test endpoint; ignore unknown types safely |
| `mac` | Uppercase strip MAC; empty for a test |
| `outlet` | Parse as integer 0–4; `0` means strip-level/no specific outlet |
| `event_id` | Parse as 64-bit integer; actual database event ID, or `"0"` for a test |
| `code` | Existing event code (`offline`, `temp_high`, etc.) or `test`; unknown codes use notification title/body |

Warn/alert events use `HIGH` priority and Android notification channel **`alerts`**.
Info and test messages use `NORMAL` and **`info`**. Create both channels in the Android app
before registration. The app must obtain notification permission where required and handle
both foreground FCM callbacks and the data extras from a background notification tap.
Use MAC/outlet to open the strip/activity view, then fetch current state with account auth;
push data never grants access. Handle a strip becoming unavailable since delivery.

The collapse key and Android notification tag are `mac:code`, so repeated warnings replace
the same displayed notification. FCM supports only four pending collapse keys per device;
this feed is best-effort, not event history. The server uses a two-thread worker with at most
64 outstanding recipient jobs; overload drops new jobs. HTTP 5xx/429 retries at most three
times with backoff (429 waits at least 60 seconds), rechecking authorization before each try.
Use `/api/events` for durable recent activity; a provider accepting a message does not prove
the device displayed it.

## Events (alerts and activity)

`GET /api/events?limit=50[&before_id=123][&mac=...]` returns events newest first:

```json
{"events":[{"id":42,"ts":1760190000,"level":"alert","code":"temp_high","mac":"…","outlet":4,
            "text":"Desk / Outlet 4: temp high 61 C","params":{"temp_c":61,"watts":12.0,"actor":"strip"}}],
 "unread_alerts":1}
```

- To page back, use the smallest `id` of the last page as `before_id`.
- A GET does not mark anything read.
- `POST /api/events/read` with `{"through_id":42}` marks events up to that id as read. Leave out
  `through_id` to mark every event read.
  - Response: `{"ok":true,"unread_alerts":0}`.
  - Account read positions are per user, shared by that user's sessions. The legacy token retains
    the original global pointer. Both only advance, clamped to the newest visible event ID.
- `unread_alerts` counts only unread `warn` and `alert` events.
- Lists, paging and unread counts include only currently accessible strips. An optional MAC narrows
  the list/count. No-MAC events are visible only to legacy credentials. Removing access immediately
  removes that strip's events and unread count. Older events become visible when access is granted.
- New events include `params.actor`: an integer account ID or `legacy`, `rule`, `strip`. Historical
  events written before migration/through the rollback server may omit it.
- The server keeps the latest 500 events.

| code | level | params |
|---|---|---|
| `offline` | warn | — (sent after the strip has been offline for 60 s) |
| `online` | info | — (sent only after an `offline` alert) |
| `temp_high` | alert | `temp_c`, `watts` (outlet level) |
| `power_high` | alert | `watts` (device level, `outlet` 0) |
| `budget` | warn, or alert at 90 % and above | `pct` (50, 75, 90 or 100), `cost` |
| `rule_fired` | info | `rule_id`, `on`, `outlets` |
| `rule_skipped` | warn | same as `rule_fired`; the strip was offline and nothing was sent |
| `rule_failed` | warn | same as `rule_fired`; the command was sent but not confirmed |
| `autooff` | info | `rule_id`, `watts` |
| `onoff` | info | `on`, `confirmed` for API commands (physical button events omit `confirmed`) |
| `name_changed` | info | outlet on the event |
| `rule_created`, `rule_updated`, `rule_deleted` | info | `rule_id` |

Personal pushes follow each user's preferences; default info events do not push. Compatibility global
channels (with `--token`, before migration) retain the old exclusions `rule_fired` and `online`. Clients should show
a translated message for each known `code`, and fall back to `text` for codes they do not know.

## POST /api/alerts/test

Request: `{}`. Tests the current account's configured channels. With the legacy token it tests the
global channels, even after migration. It does not test other users' channels and does not create an unread alert.

Response: `{"ok":false,"sent":["ntfy","fcm"],"failed":[{"channel":"telegram","error":"HTTP 401"}]}`.

FCM tests go only to the caller's registered devices, use `type: test`, empty MAC, outlet/event
ID `"0"`, and do not create an event. `sent` includes `fcm` when at least one device's message
was accepted; `failed` includes sanitized per-channel errors if any delivery failed, so partial
FCM delivery can appear in both arrays. `ok` is true only when at least one channel succeeded
and none failed. Disabled FCM or an account with no devices contributes neither array entry.

When no channel is configured, `ok` is `false` and the response also contains
`"error":"no push channel configured"` (status 200). A channel in `sent` only means the provider
accepted the message.

## Public files (no authentication)

- `GET /` and `/index.html` serve the UI, which shows login when unauthenticated.
- `GET /app.js` and `/app.css` serve public assets with SHA-256 ETags and
  `Cache-Control: public, max-age=0, must-revalidate`; matching `If-None-Match` returns `304`.
- `GET /fonts/*` serves the bundled fonts.
- `GET /powerk.py` downloads the standalone provisioner (`tools/provision.py`) under the old filename.
- `GET /powerk.apk` downloads the APK selected by `--apk`, or the repository debug build by
  default. A missing file returns `404`; Docker deployments must supply an APK separately.

A public page visit never exposes the configured legacy token. Only a request already carrying a
valid legacy credential receives the compatibility `powerk_t` cookie.

## Rate limits and client IP

All API routes can return `429 {"error":"too many requests"}` with `Retry-After` seconds.
Do not automatically retry writes whose earlier outcome is unknown. Limits are sliding windows
in memory, **per process**, and reset on restart. Public downloads/assets do not consume API limits.

| Scope | Limit |
|---|---|
| Login, normalized phone | 5 wrong-password failures, then 1 minute blocked; each subsequent failure after waiting doubles the delay to 2, 4, 8, then 15 minutes maximum; successful login resets |
| Login, client IP | 20 attempts / 10 minutes, including malformed attempts |
| Registration, client IP | 3 successful accounts / hour; concurrent creations reserve a slot; unsuccessful creations release it |
| Refresh, client IP | 60 attempts / 10 minutes |
| Claim start, account | 5 attempts / hour |
| Share/access POST, PUT, DELETE, account | 20 attempts / hour across all strips and all three methods |
| Push-token POST/DELETE, account | 20 attempts / hour |
| WebSocket connection attempts, client IP | 30 attempts / minute; five simultaneous sockets per user and per IP; close `4429` on excess |
| Every other `/api` request, account (or client IP without an account) | 120 / minute |

The fifth wrong password returns `401` and starts the first wait; requests during that wait
return `429` without password verification. Unknown phones use the same normalized key, dummy
Argon2 check and backoff as registered phones. Phone penalties expire after 24 idle hours.
Legacy shared credentials use the IP bucket. Attempts without a session at protected routes use
the anonymous IP bucket, including denied/unknown routes. Polling every 2 seconds uses 30 of
the 120 requests per minute. The bounded key store evicts idle entries; when full it rejects new
keys for 60 seconds instead of evicting active penalties. Constants live in `ratelimit.py`.

By default the client IP is the TCP peer; forwarding headers are ignored. Configure repeatable
or comma-separated `--trusted-proxy CIDR` values for the immediate proxy's networks only.
For trusted peers, a valid single `X-Real-IP` takes precedence. Otherwise X-Forwarded-For is
walked right-to-left, skipping trusted hops and selecting the first untrusted IP. Invalid hops
stop traversal and fall back to the peer; an entirely trusted/absent chain also falls back to
the peer. The app does not consume `CF-Connecting-IP`: Caddy validates Cloudflare and forwards
`X-Real-IP`. This resolved address is used for rate limits, session creation, and audit rows.
The supplied runner disables uvicorn's independent forwarding-header handling.

## Security headers

Every app response (HTML, JSON, assets, downloads and errors) has:

```text
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
```

There are no inline script/style exceptions. Chart dimensions use finite numeric CSSOM property
writes; colors and all fixed styles are in CSS. No `Server` header is sent. Uvicorn may send its
standard `Date` header; the app no longer synthesizes one. Production Caddy adds HSTS,
X-Frame-Options and Permissions-Policy. JSON request bodies remain limited to **16 KiB**, including
streamed bodies; oversize/malformed bodies return `400 {"error":"bad request"}`.

## GET /api/me/security-log

Requires an account session (legacy credentials receive `401`). Returns only rows attributed to
that account, newest first, with `Cache-Control: no-store`. Query parameters: `limit` (default 50,
clamped to 1–100), optional `before_id` (exclusive, positive signed 64-bit integer);
invalid values return `400`.

```json
{"events":[{"id":42,"ts":1800000000,"user_id":1,"ip":"198.51.100.2",
            "action":"login_success","target":"","detail":{}}],"next_before_id":null}
```

Use `next_before_id` for the next page; it is the final ID on a full page, otherwise `null`
(the following page can be empty). `target` is a strip MAC, claim ID, session family ID, limiter
name or empty string, according to the action. `detail` is the parsed stored `detail_json` object.

Actions: `register`, `login_success`, `login_failure`, `logout`, `refresh_reuse`, `password_change`,
`refresh_grace`, `session_revoked`, `claim_started`, `claim_completed`, `claim_expired`, `share`, `role_change`,
`remove_access`, `leave`, `transfer`, `unclaim`, `strip_settings_change`, `rate_limit`,
`push_token_register`, `push_token_delete` (target is a short token hash; detail includes deletion reason).
`refresh_grace` records a successful one-time recovery of a consumed refresh token; its target
is the session family ID. Claim completion/expiry uses the claim initiator's IP. Known-account
login failures are attributed to that user; unknown phones have no user ID and store only a SHA-256 hash of the normalized phone.
Share attempts use the same hash/detail shape for registered and unknown phones. Anonymous and
legacy actions have no user ID and are not exposed by this endpoint. Credentials and password
hashes are never recorded. Rate-limit events are sampled to at most one per limiter key per minute.

Audit rows older than 180 days are deleted daily. Hourly housekeeping deletes expired access tokens,
expired unused refresh tokens, and revoked families older than 30 days with their credentials.
Consumed refresh rows and their child links are kept for the full 60-second grace window, even
if their original expiry passes; afterward they are replaced by replay markers.
Minimal consumed-refresh hash/family markers remain while the family has live credentials, so
cleanup cannot disable replay detection; they are removed when no usable credentials remain or
the old revoked family is deleted. Cleanup runs in a worker thread, starting at server startup.
