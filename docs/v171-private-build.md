# v171 Private Build

How to build, install and run the **v171.0.00** client against your own server.
Status as of 2026-07-19: **boots to a fully rendered lobby on redroid.**

This is the private-server path only — the client talks to `127.0.0.1` and nothing else.
For why the stock v171 cannot run on an emulator against the *official* server, and why no
mod should try, see [v171-emulator-note.md](v171-emulator-note.md).

## What makes v171 different from v170

v170 shipped `lib/arm64-v8a/libil2cpp.so` in the APK, so the whole toolchain just patched it in
place. v171 switched to **XIGNCODE NEO**: the game code is gone from disk, packed and encrypted
inside `libaledatic.so`, and unpacked into memory at launch via `bytehook`.

So the v171 build has to do two extra things before the familiar patches even apply:

1. **NOP the NEO unpack path** in `libaledatic.so` (12 signature checks).
2. **Inject a real `libil2cpp.so`** — the offline-recovered
   `il2cpp/v171.0.00/libil2cpp_v171_ssl.so`. Recovery recipe: [mftl-extraction.md](mftl-extraction.md).

Everything downstream (host rebinding, package rename, XIGNCODE stub, signing) is the same shape as
`rebuild_arm64_mod.py`, just driven by `server/build_v171_private.py`.

## Build and run

```bash
# 1. Servers (see deploy-and-run.md for the detached form)
cd server
uvicorn server:app --host 0.0.0.0 --port 8080 &
uvicorn server:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem &

# 2. Build + sign + install "King Bug Castle" (com.nowl.castle, side-by-side with the real app)
SHARE_HOST=127.0.0.1 ADB_SERIAL=localhost:5555 python3 server/build_v171_private.py

# 3. Route the device back to your server (per-connection — re-run after any reconnect)
adb reverse tcp:80 tcp:8080
adb reverse tcp:443 tcp:8443
adb shell settings put global http_proxy :0     # clear any leftover proxy

# 4. Launch
adb shell am start -n com.nowl.castle/co.ab180.airbridge.unity.AirbridgeActivity
```

The launcher activity is **`co.ab180.airbridge.unity.AirbridgeActivity`**, not the `MainActivity` used
for v170 — `monkey -c LAUNCHER` resolves to an obfuscated class and fails.

## v171 uses plain HTTP, not TLS

The il2cpp SSL patches only cover C# `HttpClient`. Unity's own **UnityTls** (`UnityWebRequest`, inside
`libunity.so`) validates against the app's baked CA bundle and cannot be patched from il2cpp — a
self-signed cert gets rejected with `Curl error 60: UnityTls error code 7`.

The build works around it by rewriting the backend URLs `https://` → `http://` in
`global-metadata.dat` (`patch_metadata_http.py`) and adding `android:usesCleartextTraffic="true"`.
That is why step 3 above needs the `:80 → :8080` reverse as well as `:443`.

## Healthy boot

Watch `/tmp/kgc_server.log` (:8080) and `/tmp/kgc_server_tls.log` (:8443). A good boot is:

```
GET  /auth/usePatch                              (8080 + 8443)
POST /auth/getPatchFolder
GET  /patch/2026_07_14/ANDROID/ANDROID           <- CDN handshake
GET  /patch/2026_07_14/ANDROID/PatchVersion.txt
GET  /patch/2026_07_14/ANDROID/AssetHash.txt
GET  /patch/2026_07_14/ANDROID/xml               <- Strings + fonts; if this is missing the UI garbles
POST /auth/register → /auth/xcdSeed → /auth/auth?id=…&version=171.0.00 → POST /auth/login
GET  /player, /mission, /shop, /clan, /colosseum, …   (~51 requests = lobby data)
```

First launch stops at the **"Agreement of Terms and Condition"** consent dialog — tap both checkboxes
and consent. Fresh installs always show it since the package is uninstalled each build.

## Patches

Full offset table with original bytes and purpose: **[../AGENTS.md](../AGENTS.md)** →
*ARM64 Patch Inventory — v171.0.00 private build*. Short version:

- 3 SSL bypasses, baked into `libil2cpp_v171_ssl.so` (raw file offsets).
- `GameManager.CheckFirebase` → `ret` (FCM init is fatal in the v171 login coroutine and wants Play
  Services, which redroid does not have).
- 10 lobby-NRE stubs, a direct port of the v170 set — every prologue is byte-identical, only offsets
  moved.

All are idempotent and guarded: a prologue that does not match raises `SystemExit` instead of writing
into the wrong place.

## Gotchas

**Keep `libil2cpp_v171_ssl.so` pristine** — plain `libil2cpp_v171.so` plus *exactly* the 3 SSL
patches, nothing else. Never hand-patch it in place:

```bash
python3 server/patchers/make_v171_ssl_so.py --check   # validate (exit 1 if rotted)
python3 server/patchers/make_v171_ssl_so.py           # regenerate from pristine
```

It accumulated 21 stray bytes over several sessions, one of which overwrote `mov w8,#-2` with a
`b 0x3503ba8` inside `Scene_Login.<CheckUseAssetBundle>d__79.MoveNext`. That produced an infinite
UniTask recursion and a stack-overflow SIGSEGV on "Loading resources" that looked exactly like an
engine bug. **If the client crashes there, run `--check` before theorising about UniTask.**

**Never set `KGC_ASSETBYPASS=1`** outside of debugging. It skips `usePatch`/`getPatchFolder`, the CDN
`xml` bundle never downloads, and every string in the game renders as garbled or mirrored glyphs.

**Resolve crash frames via `script.json`.** Tombstone `pc` values are RVAs and match
`ScriptMethod[].Address` directly. Parsing `dump.cs` `Offset` fields for this is error-prone.

**Two backend URLs hide from `patch_hosts.py`.** It only walks the stringLiteral table;
`patch_leftover_hosts.py` catches the two field-default copies. Both run in the build. If the client
ever reaches a real backend IP, check that first.

**`tomorrow` must never come from stored player state.** `Scene_Lobby.Update` polls
`if (now >= playerData.tomorrow_) FetchNextDay()` once a second, and `FetchNextDay` re-runs the whole
login + lobby fetch chain. A stored `tomorrow` is frozen at account-creation time, so the next day the
check is permanently true and the client re-logins at 1 Hz (~17 requests/second) forever. The server
derives it (`next_reset_iso()`); regression test `server/tests/test_daily_reset.py`.

**First launch after clearing `UnityCache` hangs on "Loading resources".** All 51 requests complete,
the `xml` bundle downloads, no exception is logged — the scene just never transitions. Launch a
second time and it reaches the lobby. Only the *first* launch against a cold cache is affected, so
budget one throwaway launch after any `rm -rf .../files/UnityCache`. This is easy to misattribute to
whatever you changed just before; A/B the same change against a warm cache before blaming it.

## Content gating

`CONTENT_GATE` is derived from `serverVersion` (`"171.0.00"` → `171000`) and filters master-data
entries whose `MinVersion` is above it out of the hero / artifact / treasure listings. It used to be
three hardcoded `> 170100` literals that went stale when the client moved to v171, hiding all v171
content. Override for testing with `KGC_CONTENT_GATE=<int>`.

At `171000` versus `170100` the only listing that actually changes is heroes, 71 → 72 (unit `10790`,
Ophelia "Iron Lady"); artifacts stay 184 and treasures 58. Entries at `171100` / `172000` / `999999`
stay gated — that is future content the v171.0.00 client cannot render.

**Array fields must never fall through to a bare `ResponseModel`.** An unhandled path returns the
generic model, so any array the client iterates unconditionally arrives null and NREs. Hit this with
`GET /shop/load-custom-pickups` (Summon panel): `CustomPickupsResponseModel.customPickups` is an
`int[]`, and the empty-model fallback crashed `RestAPI.LoadCustomPickups`. Fixed with a
`DYNAMIC_OVERRIDES` entry returning `[]`. Watch the log for `[UNKNOWN PATH]` — each one is a latent
NRE of this shape.

## Known issues

- **redroid Choreographer crash** at ~70s is an emulator defect (destroyed-mutex FORTIFY abort via
  `ndk_translation`), not a client problem — it will not happen on a real ARM device.
