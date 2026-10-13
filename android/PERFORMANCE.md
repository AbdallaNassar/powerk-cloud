# Android performance

Release now uses R8 optimization and resource shrinking; debug is unchanged. JSON
model/list parsing and foreground-triggered widget rendering run on IO. A process-wide
WebSocket receives foreground changes; fallback polling calls the same HTTP API
every two seconds, retains the last good response,
and only replaces snapshot state when structural equality detects a change.
All fields (including timestamps) remain intact. Screen boundaries take only their
inputs, unchanged collections retain their identity, immutable models permit
Compose skipping, and keyed items retain identity. Grouping, chart maxima and theme
objects are cached without changing layout, strings, themes or animation specs.
Event's raw `JSONObject` stays unannotated; alert cards receive immutable strings.

Account support keeps the equality guard and the two-second disconnected polling interval.
The signed-in UI is keyed by `ServerConnection` (server, legacy mode, account and
revision), so sign-out/server/account changes dispose all editors/loaders immediately.
There is no polling composition while signed out. Access/refresh rotation does not
change that key or clear the last good snapshot. Account API parsing, login and
refresh crypto/persistence run on IO; all process clients share one refresh mutex.
New account models are immutable snapshots; people/session/strip lists use stable
IDs. Claim countdown reads are isolated from the outlets screen, with status polls
only while the activity is started. Existing chart/theme/animation tokens are unchanged.

## Socket and polling

`LiveFeed` owns one OkHttp client/socket for all STARTED main activities in the
process. It stops the socket and HTTP polling when the last activity stops or the
identity changes. No service, widget or tile opens another socket. REST remains on
HttpURLConnection. Only receipt of a complete socket `state` enables the 60-second
safety poll; disconnects immediately restore the two-second loop. Missing frames
for 55 seconds, malformed frames or a full 32-frame consumer queue force reconnect.
Backoff uses 1/2/4/8/16/30 seconds with bounded jitter; connection limits wait longer.

Socket JSON parsing and snapshot reduction run on IO. Strip frames replace/upsert
by MAC and reuse every unchanged strip; equal snapshots do not write snapshot state.
Full snapshots also reuse equal rows and the old strip collection when possible.
Totals follow the server's mixed-currency rule. Connection revision and an in-flight
snapshot version guard prevent stale HTTP replies from overwriting newer socket or
access changes. Access invalidation clears the snapshot before an immediate refetch.
Scaffold reads stay derived/narrow, and existing keyed strip/outlet lists are retained.

The visible Alerts screen merges events by ID and reloads history on reconnect or
access change. Its read acknowledgments are coalesced at two seconds. Widget work
is also conflated at two seconds on IO, so a burst of strip frames cannot trigger
unbounded RemoteViews/binder rendering. Push registration, Firebase tasks and token
storage run on IO; registration/deletion is serialized and token refresh does not
write to the server again for an already registered connection/token.

No measured frame-time or battery improvement is claimed. Compare healthy sockets,
disconnected polling and reconnect bursts on the same device. The fake-socket tests
use a virtual clock to check the 2/60-second polling transitions and heartbeat timeout.

## Release APK

Run from `android/` with JDK 17+ and the SDK in `local.properties`:

```powershell
.\gradlew.bat :app:assembleRelease
adb install -r app/build/outputs/apk/release/app-release.apk
```

If `android/keystore.properties` exists, it must contain `storeFile`,
`storePassword`, `keyAlias`, and `keyPassword`. Relative `storeFile` paths resolve
from `android/`; use forward slashes in Windows paths. The file is ignored. No
keystore is created by this change. Without it, release uses the existing Gradle
debug signing configuration, so the APK is installable. Replacing an installed APK
requires the same signing key. There are no extra R8 keep rules: JSON uses explicit
`org.json` keys, manifest components are retained by AGP, and RemoteViews only calls
framework setters. Smoke-test widgets and the Quick Settings tile on release.

## Generate a Baseline Profile

ProfileInstaller 1.4.0 and AndroidX Test JUnit 1.3.0 reuse locally cached versions.
Benchmark/Baseline Profile 1.5.0 supports AGP 9's new DSL; UI Automator is 2.4.0
([release notes](https://developer.android.com/jetpack/androidx/releases/benchmark)).
The first dependency resolution requires network access if these are not cached.
No application profile has been generated yet; normal release builds do not need
a device. They consume the generated sources after the following one-time setup.

1. Connect and unlock an Android 13/API 33+ phone with USB debugging enabled;
   verify `adb devices`. Older devices need root (minimum API 28 for this module).
2. Run `.\gradlew.bat :app:installNonMinifiedRelease`. Open POWERK, select English,
   and configure a reachable test server with a strip, rules, energy history and
   events. Use enough entries to scroll. Keep animations enabled. The generator
   uses the current English labels, including **Plugs** for Outlets and the
   **Open settings** toolbar action. Opening Alerts marks events read as usual.
3. Run `.\gradlew.bat :app:generateReleaseBaselineProfile`. The generator records
   startup separately, then visits and scrolls Outlets, Rules, Energy, Alerts and
   Settings. It waits for loaded content and fails if the setup is incomplete.
4. Review and commit the generated files under
   `app/src/release/generated/baselineProfiles/` (including `baseline-prof.txt`
   and `startup-prof.txt`), then rebuild/install release. Regenerate after major
   UI changes. See the [generation guide](https://developer.android.com/topic/performance/baselineprofiles/create-baselineprofile).

To compile/package the generator without a phone, run
`.\gradlew.bat :baselineprofile:assembleNonMinifiedRelease`.

## Measure jank

Use a physical phone and the release APK, without a debugger. Keep device, refresh
rate, thermal conditions, theme, language and server data the same between runs.
After a warm-up, reset counters, repeat the same scrolling/tab changes/outlet taps
(on a test outlet), and inspect the result:

```powershell
adb shell dumpsys gfxinfo com.powerk.app reset
# Exercise the app for 30-60 seconds, including several two-second polls.
adb shell dumpsys gfxinfo com.powerk.app
adb shell dumpsys gfxinfo com.powerk.app framestats
```

Compare janky-frame percentages and frame-time percentiles across several runs;
these changes do not claim a measured improvement yet. Android Studio System Trace
can attribute slow frames to composition, layout, drawing or main-thread work.
JankStats is another option for per-screen frame reporting in a future measurement
build; it is deliberately not added as an app dependency here.
