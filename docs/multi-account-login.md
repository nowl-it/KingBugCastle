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
app through the deep link. `server/google_login.py` implements the server half:

```
client Google button --OpenURL--> GET /glogin
   -> 302 to Google consent (our web client_id, HMAC-signed state)
Google -> GET /glogin/callback?code&state
   -> exchange code for id_token (server-side, over TLS -> trusted)
   -> read stable `sub`
   -> HTML that navigates to  kingbugcastle://auth?id=google_<sub>
app deep-link bridge -> RestAPI.Auth("google_<sub>") -> that account's own save
```

`google_<sub>` is stable per Google account, so cross-device restore is automatic
(the multi-account machinery above keys the save on it). **This half is built and
tested** (`server/tests/test_google_login.py`; real Google is stubbed).

### Google Cloud setup (once, by whoever runs the server)

1. Google Cloud Console -> APIs & Services -> Credentials -> Create OAuth client
   -> **Web application** (NOT Android - that path is the one that needs the cert).
2. Authorised redirect URI: `<GLOGIN_PUBLIC_URL>/glogin/callback`.
3. Run the server with:
   ```
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com \
   GOOGLE_CLIENT_SECRET=... \
   GLOGIN_PUBLIC_URL=https://kgc.example.com \
   ./run.sh          # or serve_public.sh
   ```
   Unset -> `/glogin` returns a clear 503 instead of a broken redirect.

### Client half - status (NOT yet verified on device)

Three client-side pieces are needed; only the manifest one is done:

- **Deep-link scheme (DONE, static):** `patchers/patch_deeplink.py` adds a
  `kingbugcastle://` VIEW intent-filter to the launcher activity. Wired into
  `build_v171_private.py`'s manifest step. Unit-tested.
- **Google button -> OpenURL (TODO, native, needs device):** inline-detour
  `Scene_Login.OnClickGoogleLogin` (v171 recovered-lib RVA `0x34FBC00`) in
  `jni/stub.cpp` so pressing it calls `UnityEngine.Application::OpenURL(<glogin
  url>)` instead of GPGS. Resolve `Application`/`OpenURL` by name like the existing
  hooks. Risk: the prologue may be PC-relative, which `install_inline_hook` refuses
  - a methodPointer swap is the fallback but only fires if the UnityEvent invokes
  through `MethodInfo->methodPointer` (uncertain for a uGUI onClick registered
  before the hook). This is the piece that needs on-device iteration.
- **Deep-link -> login bridge (TODO, native, needs device):** a poller reading
  `Application::get_absoluteURL()`; on `kingbugcastle://auth?id=X` call
  `RestAPI.Auth(X)` (static, RVA `0x2C44198`) and set `RestAPI.accessToken`
  (static field, TypeDefIndex 6647). Open problem: making the login scene progress
  to the lobby from native - `RestAPI.Auth` only does the HTTP; the AuthResponse
  handling + scene transition live in `Scene_Login`. Likeliest fix is invoking
  `Scene_Login.AccountTransferConfirm(code, accountType)` (RVA `0x34FE150`), a
  complete login-and-transition flow, with a login code minted by the web callback
  - but that needs the live `Scene_Login` instance, so it has to be worked out on
  device.

Until the two native pieces are done and verified, the working cross-device path
on the repacked build is the one below.

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
