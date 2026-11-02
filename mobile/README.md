# PA Tracker (Android)

Collects your phone data and syncs it to your own server (the desktop assistant). Not hooked to
the AI agents: on the phone you get charts and raw data; on the desktop, Mother can query it.

| Tracks | How | Needs |
|---|---|---|
| Which apps are open, and when | Android's usage stats | *Usage access* |
| Which websites are open, and when | Reads only the browser's address bar | *Accessibility* (PA Tracker: websites) |
| Location every 5 minutes | Foreground location service | Location, "Allow all the time" |

Supported browsers: Chrome, Brave, Edge, Firefox (+Focus), Samsung Internet, Opera, DuckDuckGo,
Kiwi, Vivaldi. Others can be added in `WebAccessibilityService.BROWSERS`.

**Screens:** *Dashboard* (screen time, sessions, top apps, usage by hour, daily trend, session
lengths, top websites, places, location trail, for today / 7 / 30 days), *Raw data* (every
session, visit and location point by day, CSV export), *Settings* (server, toggles, permission
checklist, sync status).

## Install

1. GitHub → **Releases** → **mobile-latest** → download `pa-tracker-N.apk` on the phone and open it.
   (Allow "install unknown apps" for your browser when asked.) Every build is also attached to its
   Actions run as an artifact. New builds install over the old one and keep your data.
2. Open **Settings** in the app:
   - Server URL: your server over Tailscale (`http://m7:8000`; while testing on the PC,
     `http://desktop:8000` with the server's `host: 0.0.0.0`). Token: `ASSISTANT_API_TOKEN`.
     Tap **Test connection**.
   - Work through **Permissions** (each has a *Fix* button). For *Accessibility* on Android 13+,
     sideloaded apps are blocked at first: Settings → Apps → PA Tracker → ⋮ → **Allow restricted
     settings**, then turn the service on.
   - Tap **Start collecting**. A small notification stays while it runs.

Data is kept on the phone for 90 days (after it has synced) and on your server indefinitely.

## Build

CI builds it on every push, at midnight every night, and on demand (Actions → tests → Run
workflow). Locally: JDK 17+ and the Android SDK (Android Studio, or `sdkmanager
"platforms;android-35" "build-tools;35.0.0"`), then:

```bash
cd mobile
./gradlew testReleaseUnitTest assembleRelease     # APK: app/build/outputs/apk/release/app-release.apk
```

### Signing

Updates only install over the old app if they're signed with the same key. By default builds use
`app/shared.keystore` (committed, password `android`): fine for a personal sideloaded app, but
anyone with access to this repo could sign an update with it. To use your own key instead:

```bash
keytool -genkeypair -keystore my.keystore -alias pa -keyalg RSA -keysize 2048 -validity 10000
base64 -w0 my.keystore    # -> repo secret ANDROID_KEYSTORE_BASE64
```

and add secrets `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`.
Switching keys means uninstalling the old app once (unsynced data on the phone is lost).

## Server side

`POST /mobile/sync` (see `assistant/mobile.py`) stores everything as events: `phone_usage`,
`phone_web`, and `location` points. The daily and weekly reports have phone sections.
