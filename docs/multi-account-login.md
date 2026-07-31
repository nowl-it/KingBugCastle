# Multiple accounts, multiple devices, and Google login

## What "one account only" was

The server keyed every request on the *active* save unless `KGC_MULTIPLAYER=1`
was set, and that env var was off by default. So two devices, or two logins on
one device, both landed on the same save. The machinery to give each login its
own save existed - it was just switched off.

## What changed

`KGC_MULTIPLAYER` now defaults **on**. Each login id gets its own save, and the
same id restores the same save on any device. Set `KGC_MULTIPLAYER=0` to force
the old single-shared-save behaviour.

### How a login maps to a save

`/auth/register` sends `{ type, id, userName, ... }`; `/auth/auth?id=` re-presents
the same id; `/auth/login` re-presents a session token, not an id. The server
resolves, in order:

1. **Known account id** -> its save (`accounts` table, `login_id -> uid`).
2. **A presented session token** -> the save that token was bound to at login
   (`sessions` table, 7-day TTL).
3. **First-login adoption** -> if the server has been single-player until now
   (exactly one save, zero bound accounts), the first login *adopts* that save
   instead of getting a fresh empty one. This is the migration path: your one
   existing save becomes account #1 rather than being orphaned. It fires once.
4. **A fresh per-account save** -> `uid = "p-" + sha1(id)[:12]`, seeded from
   `default_player.json`. Capped at `KGC_MAX_PLAYERS` (default 200), because the
   id is client-supplied and unauthenticated.

5. **No resolvable identity at all** (no token, an expired one, a forged one) -> a
   **throwaway save** that `save_state()` discards. It deliberately does NOT fall back
   to the active save: that fallback meant anyone who could reach the port read and
   wrote whichever player the dashboard had selected, with no credential (fixed
   2026-07-31; regression test in `tests/test_public_hardening.py`). Single-player
   mode (`KGC_MULTIPLAYER=0`) keeps the fallback - there is one save and nobody to
   impersonate.

`Constants.AccountType` (from the client): `0` Test, `1` Google, `2` GameCenter,
`3` AppleID, `4` Guest. The register `type` is stored on the save so
`PlayerDataResponseModel.accountType` reports the right badge.

## Google login

The value of a Google (or Apple) login over a Guest login is a **stable id**: a
Guest id is generated locally and regenerated when the app is reinstalled with a
cleared cache, so a Guest save is effectively device-local and lost on reinstall.
A Google id is the same account forever, so the same Google login on a new device
restores the same save. The server treats it exactly like any other id - once the
client hands over a Google account id, cross-device restore just works.

### The client-side catch (be honest about this)

Real Google Play Games sign-in only authenticates an app whose **package name and
signing certificate are registered in the Google Play Console** under an OAuth
client. Our repackaged build (`com.nowl.castle`, signed with the debug keystore)
is not registered, so the in-game **Google button fails inside the Google SDK,
before any request reaches this server.** There is no server-side fix for that -
it is Google refusing to vouch for an app it doesn't recognise.

So on a repacked private build, real Google sign-in is not available. It works:

- on the genuine app, or
- on a build you registered yourself in a Google Play Console project (your own
  package id + your keystore's SHA-1 + an OAuth client, and the GPGS app id baked
  into the APK).

## Google login via a web flow (works around the cert wall)

A **web** OAuth client has none of the package/cert requirement a native GPGS
sign-in does - it authenticates a browser, not the APK. So instead of the dead
native button, the client's Google button is repointed to open our own web login
page, which does the Google OAuth in the browser and hands the account back to the
app. `server/google_login.py` is the server half, `jni/stub.cpp` the client half:

```
client Google button --OpenURL--> GET /glogin            (stub detours OnClickGoogleLogin)
   -> 302 to Google consent (our web client_id, HMAC-signed state)
Google -> GET /glogin/callback?code&state
   -> exchange code for id_token (server-side, over TLS -> trusted)
   -> read stable `sub`
   -> park account id `google_<sub>` for the poller, show a return page
app native poller -> GET /glogin/pending  -> "google_<sub>"
   -> Scene_Login.Auth("google_<sub>")  (main thread, via the Scene_Login.Update hook)
   -> full login handshake -> that account's own save
```

The **deep link back into the app is not the live path**. `patch_deeplink.py` still installs the
`kingbugcastle://` intent-filter, but the app cannot reliably read the return URL, so the picked
account id is parked server-side and a native poller in the XIGNCODE stub fetches it. Handing it to
`Scene_Login.Auth` (rather than `RestAPI.Auth`) is what makes the login scene actually transition.

`google_<sub>` is stable per Google account, so cross-device restore is automatic
(the multi-account machinery above keys the save on it). **This half is built and
tested** (`server/tests/test_google_login.py`; real Google is stubbed).

### Google Cloud setup (once, by whoever runs the server)

1. Google Cloud Console -> APIs & Services -> Credentials -> Create OAuth client
   -> **Web application** (NOT Android - that path is the one that needs the cert).
2. Authorised redirect URI: `<public base>/glogin/callback`.
3. Download the client JSON and drop it, unedited, at:
   ```
   server/secrets/google_oauth.json        # gitignored; see server/secrets/README.md
   chmod 600 server/secrets/google_oauth.json
   ./run.sh                                # or serve_public.sh
   ```
   `google_login.py` reads the id, the secret, **and** the public base URL out of it -
   the base is derived from whichever `redirect_uris` entry ends in `/glogin/callback`,
   so the value sent to Google always byte-matches the one it holds. That match is
   otherwise the easiest thing in this whole flow to get wrong.

   Environment variables still win where set, for anyone who prefers them:
   ```
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com \
   GOOGLE_CLIENT_SECRET=... \
   GLOGIN_PUBLIC_URL=https://kgc.example.com \
   ./run.sh
   ```
   Prefer the file: a secret on a command line is in `~/.zsh_history` and in the
   process list, readable by any other user on the box.

   Nothing configured -> `/glogin` returns a clear 503 instead of a broken redirect.

> **The redirect URI has to be reachable from the device's browser, not from your
> desktop.** On an emulator the browser reaches the server through the same
> `adb reverse` the game uses, and `run.sh` only maps `:80 -> :8080` and
> `:443 -> :8443`. So register `http://localhost/glogin/callback` (port 80) and it
> works as-is; register `http://localhost:8080/...` and you must also run
> `adb reverse tcp:8080 tcp:8080` after every emulator restart.

**No Google at all: `GLOGIN_DEV=1`.** `/glogin` then serves a dev account picker
instead of redirecting to Google - buttons that hit `/glogin/go?id=<account>`
directly, which is the same code path from there on. This is how the whole client
loop is exercised without a Cloud project. Never leave it on for a public server:
it hands out a session for any account id you can name.

### Client half - status: DONE, verified on device (2026-07-28)

Three client-side pieces, all working on the v171 private build:

- **Deep-link scheme (static):** `patchers/patch_deeplink.py` adds a
  `kingbugcastle://` VIEW intent-filter to the launcher activity, wired into
  `build_v171_private.py`'s manifest step. Installed but not on the live path (see
  above) - kept because it costs nothing and the return page still fires it.
- **Google button -> OpenURL:** `jni/stub.cpp` inline-detours
  `Scene_Login.OnClickGoogleLogin` (v171 recovered-lib RVA `0x34FBC00`) and calls
  `UnityEngine.Application::OpenURL(KGC_GLOGIN_URL)`, resolved by name. The GPGS
  original is deliberately **not** chained - that path is what we replace. redroid
  has `org.chromium.webview_shell`, so `OpenURL` resolves to a browser.
- **Return bridge:** a background thread does a raw-socket
  `GET /glogin/pending` against `127.0.0.1:80` (adb-reverse / host-rebind), and the
  `Scene_Login.Update` hook applies the result on the **main thread** by invoking
  `Scene_Login.Auth(<account id>)` - the full handshake including the scene
  transition, which `RestAPI.Auth` alone does not do.

Log lines for a good run (`adb logcat -s XignCodeStub`):

```
Hooked Scene_Login.OnClickGoogleLogin -> web login!
Hooked Scene_Login.Update + started login poller (web-login bridge)!
Google button -> opening web login
login poll: got account id 'google_devA'
web login: Scene_Login.Auth("google_devA") - full handshake
```

If those hook lines are missing, the hooks never installed - see the hook gotcha in
[v171-private-build.md](v171-private-build.md) before debugging the login itself.

### What works cross-device on the repacked build today

- **Guest per device** - each device generates its own Guest id and gets its own
  save. Good for "several independent players", not for "the same player on two
  devices" (Guest ids differ per device).
- **Account transfer code** - the same-player-across-devices path that needs no
  Google. Device A calls `/transfer/issue` to mint a short code (24 h TTL); device
  B enters it via the in-game transfer UI (`/transfer/redeem`), which binds B's
  login to A's save. This is implemented and is the recommended cross-device flow
  for private builds.

## Tests

- `server/tests/test_multi_login.py` - adoption, per-account isolation, same-id
  cross-device restore, type capture, and the `KGC_MULTIPLAYER=0` override.
- `server/tests/test_multi_account.py` - boards/matchmaking/other-player across
  accounts.
- `server/tests/test_identity_routing.py` - the token -> uid request routing.
