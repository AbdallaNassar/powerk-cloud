# powerk Android

Kotlin / Compose Material 3, minSdk 26. Build and performance instructions are in
[PERFORMANCE.md](PERFORMANCE.md); the wire contract is in [API.md](../API.md).

## Connecting

The default server comes from `powerk.serverUrl` in `android/local.properties`
(`https://powerk.example.com` when unset). Settings accepts an HTTPS
origin (optionally a port), or HTTP on a private IP, loopback, or `.local` host.
Local HTTP displays an encryption warning. Paths, user info, queries and fragments
are rejected. The app follows no HTTP redirects with credentials.

Sign in or register using an Egyptian mobile number (`01XXXXXXXXX`) or an
international number with `+`. Accounts have their own strips and notification
settings. Owners can claim a strip with its seven-character setup code, then press
a physical button within 60 seconds. **The button switches an outlet.** Owners can
share control/viewer access, transfer ownership to an existing member, or unclaim
by typing the strip name. Members can leave. Viewers cannot switch, rename or edit
rules. All roles can read strip settings; only owners can save them.

For older servers, enable **Advanced: legacy shared token** in Server settings.
This retains `X-Token` and the old global settings UI. Account screens are hidden.
Existing valid LAN host/port settings are migrated once; plaintext token preferences
are replaced with encrypted storage. Rejected old public HTTP addresses require
reconfiguration. Their tokens are never copied to the default server.

## Authentication and background surfaces

`AuthClient` owns the process-wide `SessionClient`. Activity requests, widgets and
the Quick Settings tile share its refresh mutex. Requests capture a shared attempt
before sending, so concurrent and late 401s share its success or failure. A request
rejected with 401 waits for that refresh or uses an already rotated pair, and retries its
original method/body once. No `X-Powerk-Client: web` header or browser cookie mode
is used. Other failures do not replay commands. HTTP 429 applies a shared cooldown
using `Retry-After` (seconds or HTTP date); the UI shows a localized short message.

Access and refresh tokens are kept in a single AES-GCM ciphertext in private
preferences, using a non-exportable 256-bit Android Keystore key, random IVs and
authenticated metadata. The legacy token is encrypted too. No crypto dependency
was added. Before refresh IO, the token remains encrypted alongside an uncertainty
timestamp and a reserved-use marker; the rotated pair is committed before releasing
the mutex. Refresh is not canceled when its initiating screen disappears. DNS,
connection, pre-body TLS and cooldown failures restore the previous credentials.
Timeouts, IO after sending and 5xx retain the uncertain token, allowing one reuse
within 50 seconds of the first attempt under the server's 60-second reuse grace.
Both the deadline and spent retry survive process restart; a crash during IO is
conservatively treated as uncertain delivery. Expiry, clock rollback or an exhausted
retry signs out on the next 401. Definite refresh rejection or a different user ID
wipes immediately. Transient failures show the localized connection/try-again message.
Sign-out also wipes locally when server revocation fails. Backup remains disabled.

Account/server changes increment `ServerConnection.revision`, discard screen state
and cached widget data, and clear saved targets. Refresh rotation does not increment
the revision. One process-wide `LiveFeed` connects while a signed-in (or legacy)
activity is STARTED. A socket becomes healthy only after its first `state` snapshot.
Healthy sockets use a 60-second HTTP safety poll; disconnected sockets retain the
two-second poll. Backgrounding, sign-out and server/account changes cancel the feed
and its polling. Claims have a separate lifecycle-aware
one-second status poll and monotonic countdown. Control targets exclude viewers;
lost access is reported by widgets/tile before any command is sent. Re-select targets
after changing accounts or servers.

The socket uses Bearer authorization (or `X-Token` in legacy mode), never query
credentials or redirects. Its 4401 recovery shares the exact AuthClient refresh
attempt used by REST/widgets/tile. A second rejection before receiving a snapshot
signs out. Other failures retry with a 1/2/4/8/16/30-second base and ±20% jitter,
capped at 30 seconds; 4429 waits 30–45 seconds. No frame for 55 seconds reconnects.
`access` immediately drops the old snapshot and refetches state. Reconnect/access
also reload visible Alerts, with HTTP/socket events deduplicated by 64-bit ID.

## Firebase device push

Put the local Firebase Android config at **`android/app/google-services.json`**
(project `smart-f527e`, Android package `com.powerk.app`). This exact path is
gitignored; do not commit the file. The Google services plugin is applied only
when it exists. Without it, Gradle logs that push is disabled and builds a working
REST/WebSocket app; Notifications explains that device push is unavailable. The
Messaging library remains on the compile classpath, but `BuildConfig.FCM_ENABLED`
guards all Firebase calls. No Analytics dependency is added.

Versions: OkHttp **4.12.0** (socket only), Firebase BoM **34.0.0** (Messaging
**25.0.0**, main artifact, no KTX artifact), Google services plugin **4.4.4**.
Tests add `kotlinx-coroutines-test` **1.10.2** for deterministic socket/poll timers.
See the [Firebase release notes](https://firebase.google.com/support/release-notes/android)
and [OkHttp 4.12.0 source](https://github.com/square/okhttp/tree/parent-4.12.0).
Firebase and OkHttp supply consumer R8 rules; no broad keep rules were added.

Channels are created at application start with localized Arabic/English names:
`alerts` is HIGH importance and `info` is DEFAULT. On the first signed-in visit on
Android 13+, an in-app explanation offers the system notification prompt. Choosing
Later or denying permission does not repeatedly prompt; Notifications links to
system settings and refreshes permission state on return. Legacy-token mode cannot
register a device and says so in Notifications.

`PushTokenClient` serializes startup, login/registration and token-rotation upserts.
Within a process the same connection/token is registered once; normal auth refresh
does not re-register. Sign-out, current-session deletion and server changes attempt
the URL-encoded push-token DELETE before Firebase `deleteToken()` and credential
removal. Offline server deletion is best effort; revocation also removes the server
row. A failed Firebase deletion is persisted and retried before a subsequent token
registration, including after process restart. Firebase auto-init is off while
signed out. Registration failures can be retried by reopening the app or refreshing
Notifications. Tokens and credentials are never logged.

`PowerkMessagingService` displays foreground notification/data messages and data-only
messages on either lifecycle state. Firebase displays notification/data payloads in
the background; both tap paths open Alerts and fetch using current account auth.
An old notification never supplies strip access. Warning/alert codes use `alerts`;
info and `type: test` use `info`; unknown types are ignored and unknown codes use
the supplied title/body and channel. Tags use `mac:code` to replace repeated alerts.
Already queued background notification payloads are controlled by Firebase, so
offline cleanup cannot guarantee immediate withdrawal of an in-flight notification.

To test on a Google Play enabled phone/emulator:

1. Build with the JSON file, sign in, and allow notifications. Open Settings →
   My notifications → Notification settings, refresh, and check “Push enabled on
   this device”. This combines `/api/me/notifications.fcm`, local registration and
   system permission. The server must have its FCM service account configured.
2. Press **Test notification** (POST `/api/alerts/test`). Expect channel `info`,
   `type: test`, and no new unread alert. The result's `sent: fcm` only means that
   Google accepted delivery. Try once while foregrounded, then background the app
   and test from another signed-in client; tapping either should open Alerts.
3. Exercise a real subscribed warn/alert to check `alerts`, then test a data-only
   HTTP v1 message with string data: `type=test`, `mac=`, `outlet=0`, `event_id=0`,
   `code=test` and Android priority NORMAL. Omit the `notification` object for this
   case. Also check a cold process start, permission denial/re-enable, channel
   blocking, offline logout, account/server switching and removed strip access.

## Validation and screenshots

Run with JDK 17+ and the Android SDK:

```powershell
.\gradlew.bat :app:assembleDebug :app:assembleRelease :app:testDebugUnitTest
.\gradlew.bat :app:recordRoborazziDebug
.\gradlew.bat :app:verifyRoborazziDebug
```

`AuthClientTest` exercises 32 concurrent 401s, shared transient failures including
late 401s, retry-once, failure classification, the one-use 50-second recovery window,
restart recovery, cancellation during rotation, account changes during refresh and
rate-limit cooldowns. `TokenStoreTest` exercises the actual AES-GCM codec with an injected JVM
key (round-trip, recovery metadata, random IV, wrong key/tamper and wipe). Hardware Keystore behavior
still needs a device smoke test. `AccountModelsTest` covers URLs, roles, claims,
notification bodies, account isolation and new JSON shapes. Existing wire tests use
explicit legacy `ServerConnection` values. `AccountUiTest` verifies the target picker,
read-only strip settings, registration form validation, disabled viewer/offline switch
semantics and taps, and unclipped role/Online labels at 360 dp in English and Arabic.
The role badge keeps its own row below the title/status row, beside Manage strip.

`AccountScreenshotTest` adds 28 captures: `account_{screen}_{en|ar}_{kraft|night}`,
where screen is `login`, `register`, `empty`, `claim`, `people`, `settings`, or `viewer`.
The People capture uses the real bottom sheet; viewer captures assert that only the
Manage action is enabled. Fixtures are synthetic, with no network or live timers.

Intentional existing screenshot changes: `home_ar_kraft`, `home_ar_clean_light`,
`home_ar_clean_dark`, `home_ar_night`, and `home_en_kraft` gain the role badge on its
own row below the title/status row. The four `account_viewer_*` captures retain that
badge placement and show disabled switches. Enabled outlet switches retain their existing appearance.
The settings connection form changes below the existing initial viewport; inspect
`settings_ar_kraft` when recording. Existing widget appearance is intended to remain
unchanged. `VisualFixtures.kt` now explicitly includes owner/currency/price/budget.
No screenshot bitmaps were generated in the implementation sandbox.

Live/push tests add deterministic message reduction, row identity/mixed-currency
totals, heartbeats, backoff bounds, 4401 recovery, shared REST/socket refresh,
polling transitions, stale HTTP/socket isolation, token registration/deletion with
fake APIs (including failed deletion/restart), and notification channel/tap mapping.
The four new `account_notifications_{en|ar}_{kraft|night}` captures are synthetic;
no screenshot bitmaps were generated for this step, and existing captures were not
changed. Record/review only these intentional Notifications additions.

Reviewer gates: debug and R8 release builds both with and without the local JSON,
JVM/Robolectric suite, record/review Notifications captures, then Roborazzi verification. On a
device, also check Keystore persistence after process restart, logout/offline logout,
concurrent app/widget/tile refresh, LAN validation, physical claim completion and
expiry, owner/control/viewer operations, access removal, and notification delivery.
