# Private Build (v171 / v172)

How to build, install and run the private client against your own server.
Status as of 2026-08-14: builds from **v172.0.01** (default), **v172.0.00**, or **v171.x** APKs and
**boots to a fully rendered lobby on redroid**; Guest and web-Google login both work.

```bash
# v172.0.01 (default)
SHARE_HOST=127.0.0.1 ADB_SERIAL=localhost:5555 python3 server/builders/build_private.py

# v172.0.00
KGC_APK_SRC=xapk_extracted_v1720 SHARE_HOST=127.0.0.1 ADB_SERIAL=localhost:5555 \
  python3 server/builders/build_private.py

# v171.1.00
KGC_APK_SRC=xapk_extracted_v1711 SHARE_HOST=127.0.0.1 ADB_SERIAL=localhost:5555 \
  python3 server/builders/build_private.py
```

One script covers both because the v171.1.00 packer is the **same binary** as v171.0.01's:
4 bytes differ across 3.3 MB of code and all 12 NEO patch sites sit at identical file offsets
(verified byte-for-byte). `KGC_APK_SRC` picks the extracted XAPK; `WORK` follows it, so the two
builds do not overwrite each other's output.

## v171.1.00: why a stock, unmodified client crash-loops on redroid

Symptom: the process dies ~100 ms after start, over and over, `System.exit called, status: 1`,
**no tombstone, no native crash, and no linker error anywhere in logcat**. It looks exactly like
an anti-tamper trap reacting to the repack. It is not - **stock v171.1.00, installed straight
from the XAPK with nothing touched, does the same thing.** Confirm that first on any new client
version; it stops you bisecting your own patches for hours.

The chain:

1. The packer's Java stub (`GenesisApp.java`) is the app's `Application` class. Its static
   initialiser is `try { System.loadLibrary("<packer>"); } catch (UnsatisfiedLinkError) { System.exit(1); }`.
2. The packer's `JNI_OnLoad` calls `bytehook_init`, which returns **3** = `INITERR_SYM`: it cannot
   resolve its symbols through `ndk_translation`. The one logcat line worth grepping is
   `bytehook_tag: ... return: 3` immediately before the exit.
3. A failed `JNI_OnLoad` becomes an `UnsatisfiedLinkError`, the catch fires, process gone.

`patchers/patch_genesis.py` strips that `System.exit`, and the 12 NEO NOPs let `JNI_OnLoad`
report success so the lib actually loads and its native `woriouss()` entry points still resolve.

**The stub's class names rotate every build** - `edu/ngrinesi/dichalanga` +
`org/canesiss/ustintisic` in v171.0.01, `edu/ongesste/ratererisi` + `io/yssicata/ngenengrat` in
v171.1.00. `patch_genesis.py` used to hardcode the v171.0.01 pair, so on v171.1.00 it printed
"not found", patched nothing, and the crash-loop came back looking like a brand-new bug. It now
finds the file by content (a `System.exit` inside a `loadLibrary` catch) - the same rule as
matching the packer `.so` by its SONAME instead of its rotating filename.

This is the private-server path only — the client talks to `127.0.0.1` and nothing else.
For why the stock v171 cannot run on an emulator against the *official* server, and why no
mod should try, see [emulator-note.md](emulator-note.md).

## What makes v171 different from v170

v170 shipped `lib/arm64-v8a/libil2cpp.so` in the APK, so the whole toolchain just patched it in
place. v171 switched to **XIGNCODE NEO**: the game code is gone from disk, packed and encrypted
inside the packer `.so`, and unpacked into memory at launch via `bytehook`.

**The packer's filename rotates every build** - `libaledatic.so` (25 MB) in v171.0.00,
`librolineng.so` (114 MB) in v171.0.01, `libxenerene.so` (114 MB) in v171.1.00. Never match on
the filename. All carry
`SONAME = libappsign4a.so`, and that is what the build script greps for
(`NEO_SONAME` in the first 64 KB of each `.so` in `config.arm64_v8a.apk`).

So the v171 build has to do three extra things before the familiar patches even apply:

1. **NOP the NEO unpack path** in the packer (12 sites: 8 fixed signature-check branches +
   4 pattern-matched validation bail-outs). Offsets are per-packer-build - table in
   [../AGENTS.md](../AGENTS.md). A mismatch is a hard `SystemExit`, never a silent skip.
2. **Inject a real `libil2cpp.so`**, unpacked out of the packer itself by
   `patchers/unpack_neo.py` (offline, automatic). For a v171.1.00 source that is
   `il2cpp/v171.1.00/libil2cpp_v17110_ssl.so` — the build's **own** game code.
   Recovery recipe: [mftl-extraction.md](mftl-extraction.md).
3. **Nothing else, on the native path.** The injected lib and the metadata the APK ships
   are from the same build, so their string-literal indices already agree.

   The older fallback (`KGC_FORCE_V17100=1`, or any pre-v171.1.00 source) injects the
   v171.0.00 lib instead and DOES need step 3: `patchers/patch_metadata_swap.py` splices
   v171.0.00's `global-metadata.dat` in, because that lib's compiled indices only match
   that metadata - see below.

Everything downstream (host rebinding, package rename, XIGNCODE stub, signing) is the same shape as
`rebuild_arm64_mod.py`, just driven by `server/builders/build_private.py`.

## Building on v171.0.01 APKs (current input)

`apk/xapk_extracted_v171/` holds the **v171.0.01** APKs, and that is what the build reads. v171.0.01
is an anti-cheat-only repack - zero gameplay content change - so the v171.0.00 il2cpp we recovered
is still the correct game code. What is *not* interchangeable is the metadata.

v171.0.01 **inserted** one string literal (`/auth/xcdSeed?version=`) at index 1545 of 25730. An
insert shifts every index above it, so ~94% of the literal indices the v171.0.00 lib was compiled
against resolve to the wrong string - the client comes up but every URL, key and scene name is
garbage. Fix: ship v171.0.00's `global-metadata.dat`.

`patch_metadata_swap.py` splices it into the STORED (uncompressed) entry in `base_assets.apk`,
zero-pads to the original stored size and fixes the CRC-32 in both the local header and the central
directory. It must run **before** `patch_hosts.py` / `patch_metadata_http.py`, since those edit
whatever metadata is in the APK and we want them editing the one we ship.

The v171.0.01-only endpoint `/auth/xcdSeed?version=` needs no server change: FastAPI ignores the
query string and `/auth/*` has a catch-all.

## Build and run

```bash
# 1. Servers (see deploy-and-run.md for the detached form)
#    GLOGIN_DEV=1 = dev account picker for the Google-login button, no real Google needed.
cd server
GLOGIN_DEV=1 uvicorn server:app --host 0.0.0.0 --port 8080 &
GLOGIN_DEV=1 uvicorn server:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem &

# 2. Build + sign + install "King Bug Castle" (com.nowl.castle, side-by-side with the real app)
SHARE_HOST=127.0.0.1 ADB_SERIAL=localhost:5555 python3 server/builders/build_private.py

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
GET  /patch/<patchFolder>/ANDROID/ANDROID        <- CDN handshake
GET  /patch/<patchFolder>/ANDROID/PatchVersion.txt
GET  /patch/<patchFolder>/ANDROID/AssetHash.txt
GET  /patch/<patchFolder>/ANDROID/xml            <- Strings + fonts; if this is missing the UI garbles
POST /auth/register → /auth/xcdSeed?version=171001 → /auth/auth?id=…&version=171001 → POST /auth/login
GET  /player, /mission, /shop, /clan, /colosseum, …   (~51 requests = lobby data)
```

`<patchFolder>` is whatever `data/response_config.json` currently advertises. The CDN is served by
bare filename, so the folder name in the path is cosmetic - the same real bundles satisfy any folder.
The client sends `version=171001` (the APK's own version), which is independent of the server's
`serverVersion` / `CONTENT_GATE`.

Then check `adb logcat -s XignCodeStub` for the hook install lines - see the hook gotcha below.

First launch stops at the **"Agreement of Terms and Condition"** consent dialog — tap both checkboxes
and consent. Fresh installs always show it since the package is uninstalled each build.

## Login

Both paths work and land on the same lobby:

- **Guest** - client self-generates a `Guest_<random>` id, no Google involved.
- **Google** - the button is dead in a repacked build (GPGS needs the Play-Console signing cert), so
  the XIGNCODE stub hooks `Scene_Login.OnClickGoogleLogin` and redirects it to a web flow:
  `Application.OpenURL` → `GET /glogin` → `/glogin/go?id=` → the stub's `Scene_Login.Update` hook
  polls `/glogin/pending` → `Scene_Login.Auth(<account id>)`. redroid has
  `org.chromium.webview_shell`, so `OpenURL` resolves.
  `/glogin` returns **503** unless `GLOGIN_DEV=1` or the real
  `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + `GLOGIN_PUBLIC_URL` are set.
  Details: [multi-account-login.md](multi-account-login.md).

## Patches

Full offset table with original bytes and purpose: **[../AGENTS.md](../AGENTS.md)** →
*ARM64 Patch Inventory - v171 private build*. Short version:

- 12 NEO NOPs in the packer `.so` (see above).
- 3 SSL bypasses, baked into `libil2cpp_v171_ssl.so` (raw file offsets).
- `GameManager.CheckFirebase` → `ret` (FCM init is fatal in the v171 login coroutine and wants Play
  Services, which redroid does not have).
- 10 lobby-NRE stubs, a direct port of the v170 set — every prologue is byte-identical, only offsets
  moved.

All are idempotent and guarded: a prologue that does not match raises `SystemExit` instead of writing
into the wrong place.

Two patch sets exist but are **off by default**, behind env flags:

| Flag | What it does | Default |
|------|--------------|---------|
| `KGC_APPLY_LDR=1` | 65 `ldr x0,[xR]` → `mov x0,xR` klass rewrites | **off - they cause the black lobby** |
| `KGC_LOBBY_DIAG=1` | NOPs every null-check branch in `Scene_Lobby.Init` | off (diagnostic only) |

## Gotchas

**Keep `libil2cpp_v171_ssl.so` pristine** — plain `libil2cpp_v171.so` plus *exactly* the 3 SSL
patches, nothing else. Never hand-patch it in place:

```bash
python3 server/patchers/make_ssl_so.py --check   # validate (exit 1 if rotted)
python3 server/patchers/make_ssl_so.py           # regenerate from pristine
```

It accumulated 21 stray bytes over several sessions, one of which overwrote `mov w8,#-2` with a
`b 0x3503ba8` inside `Scene_Login.<CheckUseAssetBundle>d__79.MoveNext`. That produced an infinite
UniTask recursion and a stack-overflow SIGSEGV on "Loading resources" that looked exactly like an
engine bug. **If the client crashes there, run `--check` before theorising about UniTask.**

**Never set `KGC_ASSETBYPASS=1`** outside of debugging. It skips `usePatch`/`getPatchFolder`, the CDN
`xml` bundle never downloads, and every string in the game renders as garbled or mirrored glyphs.

**Resolve crash frames via `script.json`.** Tombstone `pc` values are RVAs and match
`ScriptMethod[].Address` directly. Parsing `dump.cs` `Offset` fields for this is error-prone.

**Never re-enable the `ldr → mov` klass patches.** They were added on the theory that
`ndk_translation` skips the TypeInfo klass self-pointer fixup. That theory is wrong, and the patch is
what *produces* the black lobby: `ldr x0,[x23]` loads `Il2CppClass*` out of its GOT slot, so
`mov x0,x23` leaves x0 = the slot address, `klass->static_fields` (`+0xb8`) reads garbage and
`GameManager._singleton` comes back null → NRE inside `Scene_Lobby.Init`. Full annotated disassembly
and the proving tombstone: [../AGENTS.md](../AGENTS.md).

**If a hook "does nothing", first prove it was installed.** The stub logs one line per hook. Three
separate ways it silently installed nothing, all hit in one session:
`#if 0` left over from a diagnostic; `dlopen("libil2cpp.so", RTLD_NOLOAD)` returning the **NEO
packer's** handle (the dex loader loads the packer long before Unity loads libil2cpp - tell-tale:
`poll took 0s`, a healthy poll takes 1s+; the fix is to require the handle to export
`il2cpp_domain_get`); and a `/proc/self/maps` fallback that required an `r-xp` mapping, which
**never exists under ndk_translation** - guest ARM64 pages are `r--p` and the translator executes
them, so use `dl_iterate_phdr` for the load bias.

**Two backend URLs hide from `patch_hosts.py`.** It only walks the stringLiteral table;
`patch_leftover_hosts.py` catches the two field-default copies - but that call is currently
active in `build_private.py`'s `main()`. Harmless while `SHARE_HOST=127.0.0.1` and
the device has no route to the real backend; if the client ever reaches a real backend IP, re-enable
it first.

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
stay gated - that is future content this client cannot render.

**Array fields must never fall through to a bare `ResponseModel`.** An unhandled path returns the
generic model, so any array the client iterates unconditionally arrives null and NREs. Hit this with
`GET /shop/load-custom-pickups` (Summon panel): `CustomPickupsResponseModel.customPickups` is an
`int[]`, and the empty-model fallback crashed `RestAPI.LoadCustomPickups`. Fixed with a
`DYNAMIC_OVERRIDES` entry returning `[]`. Watch the log for `[UNKNOWN PATH]` — each one is a latent
NRE of this shape.

## Known issues

- **redroid Choreographer crash** at ~70s is an emulator defect (destroyed-mutex FORTIFY abort via
  `ndk_translation`), not a client problem — it will not happen on a real ARM device.
