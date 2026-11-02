# mobile/CLAUDE.md: PA Tracker (Android app)

Native Android app (Kotlin, Jetpack Compose, no other UI/chart libraries) that collects app usage,
website visits and location and syncs them to the assistant server. **Android only** (the user has
no iPhone). It is deliberately NOT connected to the AI agents; it shows charts + raw data.

## Layout (`app/src/main/java/com/aidan/pa/`)
- `collect/UsageLogic.kt`: usage events -> sessions (pure, unit-tested)
- `collect/UsageCollector.kt`: reads `UsageStatsManager` since a cursor, stores sessions
- `collect/WebAccessibilityService.kt`: reads ONLY browser address bars (`BROWSERS` map of view ids)
- `collect/UrlParse.kt`: address-bar text -> url/domain (pure, tested)
- `collect/CollectorService.kt`: foreground location service; every 5 min: location, usage, sync
- `collect/SyncWorker.kt`: WorkManager fallback every 15 min; `BootReceiver`: restart after reboot
- `data/Db.kt` (plain SQLite, no Room/KSP), `data/Prefs.kt`, `data/Models.kt`
- `sync/Payload.kt`: **wire format; must match `assistant/mobile.py`** (+ `PayloadTest`)
- `sync/Sync.kt`: HTTP sync with `HttpURLConnection` (no OkHttp/Retrofit)
- `analytics/Analytics.kt`: all chart math (pure, tested); `ui/`: Dashboard, RawData, Settings, Charts

## Commands
```bash
cd mobile
./gradlew testReleaseUnitTest      # JVM unit tests (fast)
./gradlew assembleRelease          # APK -> app/build/outputs/apk/release/
```
Needs JDK 17+ and the Android SDK (`ANDROID_HOME` or `local.properties` with `sdk.dir=`). The
assistant's Docker sandbox has neither; if you can't build locally, push and check the `android`
job in `.github/workflows/tests.yml` (it also publishes the `mobile-latest` release).

## Rules
- Keep logic in pure Kotlin (`analytics/`, `UsageLogic`, `UrlParse`, `Payload`) and unit-test it.
- Changing the sync format? Update `Payload.kt`, `PayloadTest`, `assistant/mobile.py` and
  `tests/test_mobile.py` together; uids are content-based so re-sends never duplicate.
- Dependency versions are pinned together (AGP 8.7.3 / Kotlin 2.0.21 / Gradle 8.11.1 / Compose
  BOM 2024.12.01). Bump them as a set and make sure CI still builds.
- Never add analytics/crash SDKs or any network destination other than the user's server.
- The web tracker must only read address bars; never log other on-screen text.
