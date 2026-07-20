# Session Summary

> Maintained by opencode. Append new findings at the bottom. Keep all entries.

## 2026-07-18: v171 real-server emulator — game reaches login screen

### What we did
- Built `build_v171_emulator.py` for connecting to real official KGC server (no private server, no adb reverse)
- Patches applied: libaledatic signature checks (12 NOPs), il2cpp SSL (return true), xigncode bytehook callbacks (2 BLR→MOV), AwesomePrefs.SetString null-check, RogueLikeDataSet null-check, TripleDES.Decrypt empty-string fix, LoadStoryModeDataFromServer null-gameDataList fix
- `disable_firebase` added: disables FirebaseInitProvider, AppMeasurement, Analytics services; adds Firebase-analytics-deactivated metadata (needed to prevent Scene_Login:Awake() from hanging)
- `patch_prestrings.py` added before apktool rebuild (but v171 doesn't use legacy PreStrings GUID files — Addressables instead, so patch is a no-op)

### Key Findings
- **Scene_Login:Awake() hangs without disable_firebase**: Firebase Analytics initialization blocks the async state machine. Disabling FirebaseInitProvider + Analytics services fixes it.
- **AutoLogin crashes with `TripleDES.Decrypt("")`**: Fresh install has no cached credentials. `AwesomePrefs.GetString(key)` returns `""`, which is passed to `TripleDES.Decrypt`. The `SymmetricTransform.FinalDecrypt` throws `CryptographicException: Bad PKCS7 padding. Invalid length 0.`
- **TripleDES.Decrypt fix**: Replaced prologue at file offset `0x36EC830` with `ret` (`c0035fd6`). Makes Decrypt return input unchanged. Empty → empty (no crash). Encrypted → still encrypted (login fails, but falls through to login screen gracefully).
- **v171 uses Unity Addressables for strings**: Strings are in `base_assets.apk` under `assets/aa/Android/localization-string-tables-*.bundle`, not as legacy PreStrings GUID files. `patch_prestrings.py` is a no-op.
- **apktool rebuild preserves `assets/usinisse.wio`**: Already compress_type=8 (deflated) in original APK; apktool doesn't change it.
- **Game reaches fully rendered login screen**: 1080x1920, 100% non-black, 327,939 colors. No login buttons tested yet (no Google Play Services on redroid).

### Patches added this session
| Patch | Offset | Purpose |
|---|---|---|
| disable_firebase | AndroidManifest | Disable FirebaseInitProvider + Analytics + services + meta-data |
| TripleDES.Decrypt early-return | 0x36EC830 | `ret` to skip decryption entirely (input→unchanged) |
| patch_prestrings | N/A (no-op v171) | No PreStrings GUID files found in v171 base APK |

### Patches applied but with 0 count (need re-derivation)
| Patch | Offset | Status |
|---|---|---|
| patch_storymode_null | 0x3095E0C | 0 applied — bytes don't match expected; possibly already patched in decrypted il2cpp or wrong offset for v171 |

## 2026-07-19: v171 private build reaches a fully rendered lobby

Playbook: [docs/v171-private-build.md](docs/v171-private-build.md). Offsets:
[AGENTS.md](AGENTS.md) → *ARM64 Patch Inventory — v171.0.00 private build*.

### What we did
- `build_v171_private.py` now boots v171 end-to-end against the private server: CDN handshake →
  `register` → `xcdSeed` → `auth` → `login` → ~51 lobby requests → lobby renders with correct
  Strings, fonts and player data.
- Ported the v170 lobby-NRE stub set (10 patches) to v171. RVAs from `script.json`
  `ScriptMethod[].Address`; **every prologue came back byte-identical to v170**, which is what
  confirms the mapping. `WorldPanel.IsKGMarbleAvailable` has no v171 counterpart — dropped.
- Added `server/patchers/patch_leftover_hosts.py` and wired it into the build.

### Key findings
- **The "infinite UniTask recursion" was never a client bug.** `libil2cpp_v171_ssl.so` had rotted
  across sessions — 21 stray bytes, one of them a `b 0x3503ba8` overwriting `mov w8,#-2` inside
  `Scene_Login.<CheckUseAssetBundle>d__79.MoveNext` @ RVA `0x3503b7c`, jumping back into the state-1
  await setup. It was also missing all 3 real SSL patches. Two sessions were spent theorising about
  IL2CPP async internals for what a diff against the plain `.so` would have shown immediately.
  **Lesson: diff the binary before theorising about the engine.**
- **The `CheckUseAssetBundle` bypass was a wrong fix that caused the garbled UI.** It skips
  `usePatch`/`getPatchFolder`, so the CDN `xml` bundle (Strings + fonts) never downloads. Now opt-in
  behind `KGC_ASSETBYPASS=1`, debug only.
- **`patch_hosts.py` cannot see field-default strings.** It walks only the il2cpp stringLiteral
  table; `https://castle-infra-server-…run.app` and `https://kgc-cdn-1.awesomepiece.com/patch/` are
  stored as field/parameter defaults and stayed pointed at the real backend.
- **Two offset conventions coexist.** The 3 SSL patches use raw file offsets; everything else is
  `RVA - 0x4000`. Tombstone `pc` is an RVA — resolve crash frames via `script.json`, not `dump.cs`.
- **Android per-app mount namespace isolation**: a root `mount --bind` over `/system/etc/hosts` is
  invisible to an already-running app. Host-file redirection is a dead end here.

### Re-login loop — SOLVED same day
The lobby re-ran the full login + lobby fetch chain at **exactly 1.00 s** intervals (17 req/s), with
zero logcat output. The constant period was the tell: a fixed timer, not a retry-on-error.

`Scene_Lobby.Update` polls `if (now >= playerData.tomorrow_) FetchNextDay()`, and
`Scene_Base.FetchNextDay` calls `RestAPI.Login` + re-fetches everything. `server.py` served
`tomorrow` from the player save, where it was frozen at account creation (`2026-07-03` for an account
made on 2026-07-02) — permanently in the past, so the day-rollover fired every tick forever.

Fix: derive it. `next_reset_iso()` returns the next UTC-midnight boundary (`+7d` for `nextWeek`), and
the `/player` builder no longer reads the stored value. Loop → 0 req idle, lobby unaffected. Test:
`server/tests/test_daily_reset.py`.

**Technique worth reusing**: to find what drives a request, resolve the endpoint's C# method RVA from
`script.json`, then raw-scan the `.so` for `BL` instructions targeting it (`(w>>26)==0x25`,
sign-extend `imm26`, `target = site + imm*4`) and map each hit back to its enclosing method via a
sorted `ScriptMethod` address list. `POST /auth/login` → `Scene_Lobby.Update` took two hops.

### Content gate bumped to 171000
`serverVersion` → `171.0.00`, and the three hardcoded `> 170100` literals replaced by `CONTENT_GATE`,
derived from `serverVersion` so they cannot drift again (`KGC_CONTENT_GATE` overrides for testing).
Net effect on listings: heroes 71 → 72 (unit `10790` Ophelia); artifacts 184 and treasures 58
unchanged. `serverVersion` itself is inert for the client — only `/auth/checkPatchVersion` (never
called this boot) and the admin API read it — so the gate is the whole behavioural change.

**Near-miss worth recording**: the first launch after the bump hung on "Loading resources", and the
first A/B seemed to confirm the bump caused it. It did not — the hung run was the first launch after
`rm -rf UnityCache`, and the "control" run was a warm-cache second launch. Re-running gate 171000
against a warm cache reached the lobby normally. **A cold `UnityCache` costs one throwaway launch;
always match cache state across both sides of an A/B, or the confound reads as a real regression.**

## 2026-07-19: player state moved to SQLite; the JSON store was losing writes

### The defect
`state/player.json` + `state/players/*.json` were read and written by **both** uvicorn processes
(`:8080` and `:8443`) plus `dashboard.py`, guarded only by a `threading.Lock` — which locks nothing
between processes. `Path.write_text()` is also not atomic. So a concurrent save either clobbered the
other side's update or left a partial file. This is the most likely explanation for a 96-entry
accessory list reverting to the 4 generated defaults mid-session.

### The fix
`server/playerdb.py` — SQLite, WAL mode, one row per `uid`, JSON blob unchanged so no game logic
moved. `load_state()` / `save_state()` kept their signatures, so all ~40 call sites were untouched.
`migrate_from_json()` imports the old files once (idempotent); they now sit dead in
`state/pre-sqlite-backup/`.

### A transaction per save is NOT enough
The concurrency test caught this immediately: with two processes doing
`load → mutate → save` in a loop, process A's save wrote back a dict that predated B's — B's update
vanished (`b=54` instead of `59`) with no corruption anywhere. Atomicity of each write says nothing
about the read-modify-write around it.

Fix: an HTTP middleware in both apps holds `playerdb.write_lock()` (flock, cross-process) for the
**whole request**. Order matters — `asyncio.Lock` is acquired FIRST, because flock blocks the thread:
a second request in the same process would block the event loop while the lock holder is still
awaiting `call_next`, deadlocking both. `/patch/` (CDN, no state) skips the lock.
Test: `server/tests/test_playerdb_concurrent.py`.

### Still single-identity
`load_state()` serves the admin-selected **active uid**. The client never echoes back the
`accessToken` `r_login` mints, so there is no per-request identity to route on yet. Real multiplayer
needs that mapping; `load_state()` is the one function that changes when it lands.

### Also this session
- `_XML_LIVE` pointed at `scratchpad/xml_live`, deleted during cleanup → server died on import.
  Now `server/xml_live`, which is what the docs said all along.
- `server/run.sh`: both uvicorns with `--reload`. With `watchfiles` installed (now in
  `requirements.txt`) edits to `server.py`, `data/*.json` and `xml_live/*.xml` all reload live;
  `state/` is excluded so the server's own saves cannot cause a restart loop — verified: an xml edit
  and a json edit each reload, a `/player/building/save` does not. Without `watchfiles` uvicorn
  silently falls back to StatReload, watches only `.py`, and ignores `--reload-include`.
  `--reload` is a dev-only tool: `serve_public.sh` deliberately does not use it, since a reload drops
  in-flight requests.
- **`next_reset_iso()` and `tests/test_daily_reset.py` had gone missing from the working tree** — the
  1 Hz re-login fix from earlier the same day was not actually on disk (`"tomorrow": st.get(...)` was
  back). Restored both. Worth re-checking after any cleanup pass.

### Per-request identity (same day)
The client *does* echo its token: `Web.Get<T>(uri, accessToken)` / `Web.Post<T>(...)` take it on every
call and `Web.HandleWebHeader` (RVA `0x2CBBADC`) attaches it as the **`accesstoken`** header — the
name is confirmed by the old real-backend capture (`api/config.py:113`), not guessed.

So `load_state()` now resolves identity per request: middleware → `playerdb.uid_for_token(header)` →
`CURRENT_UID` ContextVar → `load_state()`. Set the ContextVar *before* `call_next`, so the task it
spawns inherits it. No token → active player, which keeps the whole pre-login boot and the admin UI
working unchanged.

`accounts` maps the client's account id (`?id=` on `/auth/auth`, `body.id` on `/auth/register`) to a
uid; `sessions` maps minted token → uid with a 7-day TTL.

**Bug worth remembering**: the first cut called `bind_login()` unconditionally in `r_login`. In
single-player mode `_uid_for_login` falls back to the *active* save, so every account id that ever
logged in got recorded as owning it — and those rows survived turning multiplayer on, which is why
two distinct device ids both resolved to `dev-0001` afterwards. Only the branch that actually owns
the account may write the mapping.

`KGC_MULTIPLAYER=1` gates auto-creating a save for an unknown account id; default off so a reinstall
on a single-player setup cannot mint an empty save that reads as lost progress.
Verified over real HTTP (AES bodies, real routes): two account ids → two uids, a `/player/building/save`
from A left B and the active save untouched, re-login returned A's save, a bogus token fell back to
active. Test: `server/tests/test_identity_routing.py`.

### Security pass on the multi-player path
Making the server multi-player surfaced a hole that predates it: **26 `/admin` routes had no auth at
all**, and `serve_public.sh` binds `0.0.0.0` so remote players could reach them — rewrite or delete
any save, grant themselves anything. Same for the whole dashboard on `:8081`.

Gate: `KGC_ADMIN_TOKEN` set → required from everyone (`x-admin-token` header or `?admin_token=`);
unset → loopback only. `serve_public.sh` refuses to start without it — behind a Cloudflare Tunnel or
any reverse proxy, **every request arrives from loopback**, so the loopback fallback alone is
worthless there. `/ws` needs its own copy of the check: Starlette HTTP middleware never sees
websocket scope.

Also: `KGC_MAX_PLAYERS` (default 200) caps auto-created saves, since the account id is
client-supplied and unauthenticated; and account ids are logged as an 8-char fingerprint rather than
verbatim, because they are bearer credentials and `admin_log` renders into the dashboard log view.

Test: `server/tests/test_admin_guard.py`. Gotcha — `TestClient`'s default peer address is the literal
string `"testclient"`, which is not loopback; without passing `client=(ip, port)` the guard test
"passes" while asserting nothing real.

## 2026-07-19: accessory sub-stat tier was a server flag, not bad data

Sub-stats rendered with no tier badge. Root cause: `AccessorySubStatGrade.Set(float score)`
(v171 RVA `0x3361904`) opens with `GameManager.GetKeyValueInt("AccessoryRenewal")` and, on anything
but `1`, takes a `SetActive(false)` branch that hides the badge entirely. The flag rides in
`PlayerData.keyValues` — the `/player` response — and the server never sent it. One line fixed it.

**Only one function in the whole binary reads that flag** (verified by resolving the relocation for
every `.data` slot pointing at the literal, then scanning all `adrp`+`ldr` pairs into those slots),
so enabling it turns on the badge and nothing else — no hidden dependency on endpoints we do not
implement.

The tier value is `Utility.LowerBound(ResourceAccessoryConstant.AccessorySubStatScoreRange, score)`,
and that range is parsed from **AccessoryConstants.xml** (`1, 4.5, 8.5, 13.5, 18.5, 22.5, 26.5`) —
data we control. The served scores (4.0–9.5) land on tiers 1–3.

### Technique: resolving an il2cpp string literal without a stringliteral dump
The literal is not referenced directly. `adrp x8, page; ldr x8, [x8, #off]` loads a `.data` slot, and
that slot is filled by an `R_AARCH64_RELATIVE` relocation whose **addend is the real literal-slot
address**. Parse `.rela.dyn`, look up the addend, then map it through Il2CppDumper's
`script.json` → `ScriptString`. Il2CppDumper runs headless via
`dotnet Il2CppDumper.dll <so> <global-metadata.dat> <outdir>` (it throws on the final "press any key"
prompt — output is already written by then, ignore it).

Test: `server/tests/test_accessory_grade.py`.
