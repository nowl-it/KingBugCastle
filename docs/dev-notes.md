# Dev Notes - Personal Reverse-Engineering Knowledge Base

> Maintained by opencode for opencode. **Task workflow (user-mandated 2026-08-18):**
> 1. Before any task: check this file first (then AGENTS.md, KNOWLEDGE.md, docs/).
> 2. Already covered → follow it. Not covered → do the work, then update this file.
> 3. Docs wrong → investigate first; only update this file once certain.
>
> Companion files: `KNOWLEDGE.md` = chronological session diary (append at bottom);
> `AGENTS.md` = binary-patch inventory + internals; `docs/` = operator playbooks.

---

## 0. Tooling & conventions (read before anything)

- **Binaries**: `apk/xapk_extracted_*/` (APKs), `il2cpp/<ver>/libil2cpp_*.so` (decrypted),
  `il2cpp/<ver>/script.json` (`ScriptMethod[].Address` = **RVA**, decimal), dumps at
  `/tmp/opencode/kgc_*dump*/out/dump.cs` (may not survive reboots - regenerate with
  Il2CppDumper if missing).
- **RVA vs file offset (ARM64)**: file offset = `RVA - 0x4000`. The 3 SSL patch rows in
  AGENTS.md are **raw file offsets** - everything else is RVA. Never mix.
- **dump.cs `Offset:`** field = `RVA - 0x4000` = raw file offset - matches `patch_apk()`
  conventions 1:1. Method name resolution = grep dump.cs for the class, read the method's
  `RVA: 0x...` line.
- **Tombstone `pc` values are RVAs** - resolve via `script.json`, never dump.cs offsets.
- **Disassembly**: capstone off the raw `.so` at file offset (`so[addr-0x4000:]`).
- **Find callers of a method**: raw-scan for `BL` targeting its RVA: `(w>>26)==0x25`,
  sign-extend `imm26`, `target = site + imm*4`. (How `Scene_Lobby.Update` was found from
  `POST /auth/login` in two hops.)
- **Frida is BLOCKED on redroid** (ndk_translation - `Process.enumerateModules()` never shows
  libil2cpp). Static Ghidra/capstone + logcat/screenshots only. Don't re-attempt.
- **Static-cctor guard pattern** (ignore while reading logic): `ldr w8,[x,#0xe0]; cbnz w8,skip;
  bl #0x2ad08a8` - runtime helper cluster: `0x2ad0774` (ensure static ctor), `0x2ad08a8`,
  `0x2ad09bc`, `0x2ad09c4`, `0x2ad09cc`. The `[x,#0x310]` bools are per-method cctor guards too.
- **Division magics**: unsigned `/5` = `umull x,w,0xCCCCCCCD; lsr #0x22`; signed `/10` =
  `smull x,w,0x66666667; lsr #0x3f; asr #0x21; add` (same magic, shift 33 vs 34 - check the
  shift to tell /10 from /5).
- **`List<T>.Find` in compiled code**: display class allocated via a `bl` helper, captures
  stored at `[disp,#0x10]/[disp,#0x14]`, then `Find(list, disp, null)` - the predicate thunk
  near `0x308xxxx` (v172) reads `[x1,#0x10]`/`[x1,#0x14]` (this.captures) vs `[x0,#0x18...]`.
  `Find` = `0x43cfcb8` (v172.0.01) / `0x43c49ec` (v171.0.00).
- **`List<T>` layout**: `_items` @+0x8, `_size` (`Count`) @+0xc, `_version` @+0x10 (relative to
  the List object pointer - dereference the containing field first).
- **Deck-length invariant**: server deck must be exactly 6 elements
  (`DECK_SLOTS`) - see AGENTS.md "Deck-length invariant".
- **String literals**: `script.json` `ScriptString[].Address` = literal VMAs; methods carry no
  literal refs - find the using method by decompiling, not string search.
- **Offsets move between versions** (v170.0.03 → v171 → v172: every prologue byte-identical,
  offsets shifted). Re-derive per version; never reuse across libs.

---

## 1. Invasion rewards - COMPLETE decode (2026-08-18)

User client is **v171.1.00** (no dump exists; v171.0.00 dump + v172.0.01 dump/binary are the
proxies - panel absent in v171.0.00, added by v171.1.00; GameManager API identical).

### Client contract

- `InvasionRewardDatasResponseModel{RewardData rewardDatas}`;
  `RewardData{int index@0x10, int pass@0x14, long rewardState@0x18}`.
  Rewards themselves come from CDN `InvasionRewards.xml` (flat IDs, `divmod(rid,100)`,
  200 rows: themes 1-20, 51-70 × 5 difficulties) - the response carries **only claim state**.
- **`ThemeIdToPassIndex(theme)`** (v172 `0x33ECF4C`, v171.0.00 `0x33E3460`):
  `theme<=50 → 2*((theme-1)//10)`; `theme>50 → 1+2*((theme-51)//10)`.
  10 themes share one index: 1-10→0, 11-20→2, 51-60→1, 61-70→3.
- **Panel pass per theme** (`GetStartEndThemesByPassIndex`, v172 `0x33ECDF4`):
  pass 0=[1,5], 2=[6,10], 4=[11,15], 6=[16,20], 1=[51,55], 3=[56,60], 5=[61,65], 7=[66,70].
  Formula: `t<=50 → 2*((t-1)//5)`; `t>50 → 1+2*((t-51)//5)`. `ThemePerPass = 5`;
  `GetPassCount` = `ceil(r0/5)+ceil((r1-50)/5)` → 6 tabs with 11/61 records.
- **`GetInvasionRewardData(theme, pass)`** probe (v171.0.00 `0x304ED40`): finds the FIRST entry
  with `entry.index == ThemeIdToPassIndex(theme) && entry.pass == pass`.
- **`InvasionRewardReceived(theme, difficulty, pass)`** (v171.0.00 `0x304EC74`, v172 `0x3055F6C`):
  probe entry, then bit `(difficulty-1) + 5*((theme-1)%10)` of `entry.rewardState` (bit test via
  `RewardData` method `0x3716560` v172). **Bit layout is 5 bits per theme inside the entry.**
- **`HandleInvasionRewardReceived(theme, pass, rewardState)`** (v172 `0x305612C`): probe, then
  `entry.rewardState = rewardState` (wholesale overwrite - sibling themes transiently wrong until
  re-fetch; that's the real game's behavior too).
- **`GetInvasionRewardDatasByPassIndex(pass)`** (v171.0.00 `0x304EE50`): entries with
  `entry.pass == pass` (b__0 v172 `0x308A978`).
- **`HasInvasionPass(passIndex, pass)`** (v171.0.00 `0x304EB98`, v172 `0x3055E90`):
  `Find(entry.index == passIndex && entry.pass == pass)` (b__0 v172 `0x308A8F0`).
- **`GetReceivableRewardCount(passIndex)`** (v172 `0x33EDB40`; the panel tab badge):
  - 25 rows: `theme = base + r/5`, `difficulty = r%5`, `base = (odd?51:0) + 5*(pass//2)`
    (v172.0.01 base is 0-based → theme 0 for pass 0 - its own quirk; v171.1.00 counts 1-based).
  - gate: skip row unless `GetInvasionClearedDifficulty(theme) > difficulty`
    (`0x30568B8` v172 = `records.First(t.theme==theme).difficulty` via Find, null → 0).
  - then: `entry.pass == 0` → count (pass-0 shortcut) **or** `HasInvasionPass(P, entry.pass)`
    → count - the count needs an entry `{index: P, pass: P}` for every pass P ≥ 2!
  - count only if NOT `InvasionRewardReceived(theme, difficulty, entry.pass)` (bit clear).
  - **Symptom of wrong shape**: all entries deserialize `{0,0,0}` → only pass 0 counts
    (25 on Part 1, 0 everywhere else) - exactly the user's report.

### Server response (the fix, shipped 7b84fc5, `server/routes/challenge_routes.py`)

`GET /invasion/reward` (no `theme` in body) returns 16 entries, normal-first, markers last:
1. **8 group entries** `{index: TI(t), pass: P(t), rewardState}` - one per (TI, pass) group,
   mask = OR over the group's 5 themes of `st_mask[t] << (5*((t-1)%10))`.
2. **2 pass-1 entries** `{index: 0|2, pass: 1}` for themes 1-20 (pass-reward display/claim).
3. **6 markers** `{index: p, pass: p, rewardState: 0}` for p = 2..7 - make
   `HasInvasionPass` true. Passes 0 and 1 need none (shortcut / own group entry).
   Do NOT add {0,0}/{1,1} markers - they'd shadow the real entries (same probe key).

Claim POST (`theme` present): `{rewardListData, rewardState: st_mask[theme] << (5*((theme-1)%10))}` -
the offset matters, the client bit-tests at `(d-1)+5*((theme-1)%10)`.

Server helpers: `_invasion_pass_index`, `_invasion_pass_of`, `_invasion_entry_mask`.
State key: `st["invasionRewardState"][str(theme)]` = per-theme 5-bit mask (bit `d-1`), set by
`_invasion_claim` regardless of `pass` (normal + pass claims share one bit - deliberate
simplification). Tests: `server/tests/test_invasion_reward.py` (run with `python3
tests/test_invasion_reward.py` - the `check_*` functions are not pytest-collected).

---

## 2. Weekly ranking / eliteRankingScore (2026-08-14/18)

- Score submission = `eliteRankingScore` (long, field offset 0xC8) inside `POST /game/complete` -
  **no separate score POST**. `RestAPI.AddRanking` only fires from a debug button
  (`SettingsPanel.<OnClickTestRanking>`). The ranking-stage battle ("Measure Combat Power")
  computes `GetRankingScore` (v171 `0x2d70230`) → stored → complete request carries it.
- `r_game_complete` stores best in `st["eliteRankingScore"]`; `r_ranking` prefers it, falls back
  to `bestClearedTheme*100+bestClearedStage`. Test: `check_elite_score_flows_through_game_complete`.
- No `ranking*` string literals in v171/v172 `.so` - API paths are static fields; **the TLS log
  (`/tmp/kgc_pub_tls.log`) is the source of truth for what the client calls**.
- `GetRankingServerEndPoint()` patched (v172.0.01 file `0x2CBB2C4`) to return `Web._endPoint`
  (127.0.0.1) instead of the cloud-run URL.
- Leaderboard roster safety in `roster.py`: `deck_units` (6, pad with
  `[10000,10010,10020,10030,10040,10050]`), `rank_row` (never-null names), `playerRank` always
  populated for the caller. Empty fallback model → `RankingPanel` NRE - routes must return
  populated rows.

### Original-server seasonal boards (verified 2026-08-24)

- Production ranking host: `https://kgc-ranking-1.awesomepiece.com` (not the main
  `kgc-k8s-1` API, which returns 404 for `/ranking/*`). Direct unauthenticated requests with
  header `version: 172.0.01` reach its auth layer and return `401 WrongTokenError`; stale
  `169.1.05` returns `403 NotLatestVersion`. The same applies to `172.0.00`.
- Current season must be read with the same account session: `GET /pvp/info` for Arena and
  `GET /colosseum` for Strife. Use their `season` field respectively in:
  `GET /ranking/pvp-ranking?season=<n>&useCache=true` and
  `GET /ranking/colosseum-ranking?season=<n>&useCache=true`.
- Auth is the client header `accesstoken`, not `Authorization: Bearer`; preserve a current
  client `version` header. `api/ranking/fetch_seasonal.py` reads both season values and fetches
  both boards with `KGC_TOKEN=<accesstoken>`; set `KGC_VERSION` only when using a different APK.
- Infra discovery `GET https://castle-infra-server-65408603887.asia-northeast3.run.app/api/cloud-run/default-ranking?location=asia-northeast3&useReplica=false`
  currently returns a `qa-ranking-default` Cloud Run URL. It produced HTTP 500 for direct board
  reads in this check, so do not substitute it for the verified production ranking host.

### Guest token automation vs XIGNCODE gate (verified live 2026-08-24)

Probed against production `kgc-k8s-1` (main API has no version WAF - old `170.1.00` /
`169.1.05` headers are still accepted there, unlike the ranking host):

- `POST /auth/register` `{type:4, id:"", userName, castleName, kingPostfix:1, castlePostfix:1,
  version:172001}` works unauthenticated and returns the account's `loginId`
  (server-assigned, shape `Guest_` + 10 uppercase alnum). **Arbitrary names are rejected**
  (`code:400 WrongKingName`, e.g. "Guest1234"); random 8-char uppercase+digits passes.
  The v170-era "register returns accessToken" behavior is **gone** - v172 always answers
  `accessToken: null`, regardless of client version headers.
- Every token-issuing endpoint requires a valid XIGNCODE cookie and answers
  `401 WrongTokenError` without one: `/auth/auth?id=<loginId>&version=…&cookie=` (alias
  `/auth` → `code:410 Fail` for these ids), `/auth/xcd?cookie=`, `/auth/login`. Fake cookies
  fail identically. `/auth/xcdSeed?version=` works unauthenticated and returns the seed for
  the native SDK. Conclusion: tokens cannot be minted outside the genuine client.
- Working pipeline: harvest a token from a real session with the passive addon
  `api/auth/token_harvester.py` (`mitmdump -s api/auth/token_harvester.py`, tap Guest login
  once in the stock client → writes repo-root `captured_token.txt` + `captured_guest.json`)
  → `api/ranking/fetch_seasonal.py` auto-loads it. `api/auth/guest_login.py` scripts
  register / id-reuse / seed fetch but stops at the XIGNCODE gate by design. Two probe
  accounts (`Guest_D27R24JK8S`, `Guest_2HWUF68893`) remain registered on official from these
  tests - there is no delete endpoint without auth.

## 3. Daily reset (2026-07-31)

`tomorrow` must be **derived** (`next_reset_iso()` - next UTC midnight, `+7d` for `nextWeek`),
never stored: `Scene_Lobby.Update` (RVA `0x34EA5F0`+) re-runs the whole login chain at 1 Hz when
`now >= tomorrow_` (`PlayerDataResponseModel.tomorrow` @ 0xD0). A past value = constant
re-login loop, 17 req/s, NO exceptions. Test: `server/tests/test_daily_reset.py`.
Fixed-period loops with no exception = client timer, not retry.

## 3a. Discord CDN monitor (2026-08-24)

- `scripts/check_cdn_update.sh` owns update detection; it invokes
  `server/discord_notify.sh` only for a new CDN folder, an in-place XML republish, or a newly
  observed store APK version. No-change and local-staleness results must stay quiet.
- The notifier posts with the existing Discord bot to channel `1541439188686213221`. Its bearer
  token is a single line in ignored `server/secrets/discord_bot_token` (or `DISCORD_BOT_TOKEN`),
  never a tracked config value.
- `systemd/kgc-cdn-monitor.service` runs `scripts/run_cdn_watcher.sh` as a user service. The
  wrapper posts one online message on start, checks immediately, then sleeps 1800 seconds.
- **2026-08-25 format fix:** Bash does not turn `\n` inside ordinary double quotes into line
  breaks. Build the Discord content with `printf`, so it contains real newlines; normalize both
  folder dates from `YYYY_MM_DD` to `YYYY-MM-DD` before sending.
- CDN `2026_08_25` was refreshed with `refresh_master_data.py`: 22 local files were rebased,
  all five `local_mods` replayed without warnings, and `response_config.json` now advertises
  that patch folder. The rebuilt XML hash is `ef2d0d9c2c26a5a1cb8a3bfc5d001266_4031397`.
- Pristine `2026_08_13 → 2026_08_25` delta is six files: new v173.1-gated Mystic treasure
  `30043` (Vitacorde, for unit `10060`), its buffs/visual skill, a guard-duration metadata fix
  for accessory synergy `10082`, `Unit10390AI` assigned to Rie (`10390`), and KR-only upcoming
  Pick-and-Pick mode text. Pristine `30043` has `MinVersion=173100`; local_mods lowers it to
  `172001` for the deployed v172.0.01 client.
- `FetchComplete` is a deliberate private-server loading-text override: "Ready to bug! Starting
  the fix now!" and 12 locale equivalents. The `2026_08_25` refresh reset it to the official
  text; `_apply_fetch_complete` in `server/local_mods` restores all 13 versions idempotently.

### Reference-derived Frieren idle sheet (2026-08-24)

- `server/assets/frieren/frieren/idle_2x2/` contains a standalone four-frame (`2x2`) pixel-art
  idle loop derived from `Illustration_1040.png`. It is an auxiliary generated asset, not the
  production `Unit_10570_03` atlas or a replacement for `rebuild_frieren_sprites.py`.
- Strict processing passed: no source/output edge contact, empty or clamped frames; body-scale CV
  `0.0103` and anchor-Y std-dev `0.0332` (limits `0.08` / `0.05`).

### Pixelorama Frieren single-sprite refinement (2026-08-25)

- Source: `server/assets/frieren/frieren/Frieren KGC Sprite.pxo` is a Pixelorama `60x76` one-frame,
  one-layer draft based on `Illustration_1040.png`. The `.pxo` stores raw RGBA at
  `image_data/frames/1/layer_1` (`60*76*4` bytes) plus an 8x `preview.png`.
- `server/assets/frieren/frieren/refine_frieren_sprite.py` is deliberately conservative after the
  first over-processed attempt looked muddy: it preserves every source color/pixel cluster and only
  clears edge-connected near-black background to alpha. It writes both the legacy refined filenames
  and explicit `alpha_clean` filenames, including `Frieren KGC Sprite alpha clean.pxo`. It does
  **not** replace the original `.pxo`.
- The optional `Frieren KGC Sprite color pass.pxo` is a separate, localized material pass: opaque
  dark fill clusters (not only pure black) become dark violet (clothing/collar), cold lavender
  (hair), warm brown (staff metal), warm skin shadow, or boot shadow. It raises only lavender,
  gold, and red chroma; the white robe, skin, eyes, original canvas size, and hard alpha remain
  intact. The only pure-black pixels left are the eye/eyelash cluster. It is a revision candidate,
  never a replacement for the original draft.
- For subsequent user-directed edits, start directly from `Frieren KGC Sprite.pxo`, not an alpha or
  colour pass. Do not infer staff-head mechanics from the low-resolution draft: two automated
  attempts at ruby braces were rejected and deleted. Require a user-marked three-bar overlay or
  explicit pixel endpoints before altering that assembly.

## 4. Auth & sessions (2026-08-18)

- `_uid_for_login`: id-less logins refused in multiplayer (never fall back to the active save -
  that minted dev-0001 sessions every ~5-20 min). Single-player fallback only.
- `GET /auth?id=...` (native Google sign-in) MUST mint a token (`direct_routes.py` →
  `mint_session_token`) - an empty model means a fresh client never gets `accessToken` and every
  later request hits the throwaway template save ("KingBug"). Diagnosis: zero new session rows
  at login time = the login body carried no id.
- **v172.1.00 post-logout login fixes (2026-09-06):**
  - Google browser callbacks arrive through Cloudflare while the native poller may reach origin as
    `127.0.0.1`; IP-only parking makes `/glogin/pending` poll forever. The stub now persists a
    random 128-bit device handoff key, sends it to both `/glogin?device=` and
    `/glogin/pending?device=`, and the server signs it into OAuth state before parking the result.
    Do not use a shared loopback alias: concurrent users could overwrite or consume each other's
    handoffs. Clients without a device key retain the legacy IP-bound flow.
  - Guest `AutoRegister` POSTs `/auth/register`, then GETs `/auth` with the same id. The direct
    handler requires a one-use native grant, so successful type-4 registration must call
    `_grant_native_auth`; otherwise `/auth` returns `success:false`, missing date strings make
    `Scene_Login.HandleAuthResponse` throw `ArgumentNullException`, and UI stays Authenticating.
  - The native hook must locate `<AutoRegister>g__AutoRegisterImpl` by stable prefix: its compiler
    suffix changed from `|134_0` to `|137_0` in v172.1.00. Exact lookup silently skipped the hook.
    Regression: `tests/test_multi_login.py::check_guest_register_grants_its_followup_native_auth`.
- Template uid is `""`; every key fallback is `st.get("uid") or "dev-0001"` - never persist a
  `""` or `guest-0001` row. Full write-up: `docs/multi-account-login.md`.
- `dev-0001` = NightOwL since 2026-08-18 (uid `p-410890b421a5`, merged; old KingBug save
  deleted, backup in `server/state/backups/players.db.bak-uidmerge-*`).

### Official-token harvesting - Firebase Test Lab verdict (2026-08-24, DEAD END)

Goal was a real official `accesstoken` for the ranking API. Ran the **stock v172.0.01 client**
on Test Lab physical Pixel 8a (`model=akita,version=34`, project `kgc-harvest-43937`) with a
custom instrumentation APK that dumped `shared_prefs` every few seconds and auto-tapped dialogs:

- Stock xapk → single APK via APKEditor, then **re-sign** (zipalign + apksigner debug key) or
  Test Lab rejects with `NO_SIGNATURE`. Harness: plain JUnit4 `@Test` +
  `InstrumentationRegistry.getInstrumentation()` + UiAutomator; **no** `android.test.*`
  (removed in API 34 → `NoClassDefFoundError`). `targetPackage=com.awesomepiece.castle`
  means instrumentation runs inside the game process.
- Game installs/launches fine and writes prefs (Unity Screenmanager keys, airbridge,
  tapjoy…), but the process dies at **T+75s on every run**: clean `exit(0)` normally, or
  `FORTIFY: pthread_mutex_lock called on a destroyed mutex` when our UI-poking races the
  teardown. Right before death its threads scan `/proc/net/tcp|unix`, `/dev/configfs`,
  `/system`, and read `Settings.Global adb_enabled` (always on for Test Lab). The GPGS
  "Create a Play Games profile" dialog is NOT the cause (tapping Cancel only delays it).
- Verdict: **XIGNCODE environment-kill ~75s after launch, before any server login** - no
  `loginId`/`accesstoken` is ever written. No amount of UI automation fixes this; don't burn
  more matrices on this route.
- Re-confirmed §2 above: `/auth?id=` needs `version` in the **query string** (header alone →
  `403 최신 버전이 아닙니다 (Version)`); with query version ≥172.0.01 the check passes and an
  unknown id gives `404 존재하지 않는 계정입니다` (the old iOS guest id is gone/not visible to
  Android-platform lookups). Registering fresh guests still works but token issuance stays
  behind the XIGNCODE cookie gate.

### QEMU ARM64 emulator verdict (2026-08-24, blocked)

- Host is x86_64. The normal Android Emulator launcher refuses the API 33 Google APIs ARM64
  image with `AVD's CPU Architecture 'arm64' is not supported by the QEMU2 emulator on x86_64`.
- Calling the bundled `qemu-system-aarch64` frontend directly with `-avd-arch arm64` bypasses that
  check. Its `ranchu` machine then always appends `-soundhw virtio-snd-pci`, which fails because
  the ARM64 ranchu machine has no PCI bus, even with `-no-audio` and `hw.audioOutput=no`.
- Adding `-qemu -M virt` avoids the PCI error. The correct AVD `userdata-qemu.img` (8 GiB virtual
  size) is required; the stock `userdata.img` is only 1 MiB. With that fix Android API 33 mounts
  system/vendor/data and reaches the vendor HAL start sequence, but the bundled QEMU frontend
  segfaults around the graphics/USB HAL startup before `adbd` becomes online. `-gpu off` does not
  change the result. No APK login or token was reached; XIGNCODE was not patched.
- Do not spend more time on this direct-emulator variant unless switching to a compatible
  Cuttlefish/full-system image or a different emulator build. Redroid remains the only bootable
  ARM64 path tested here, but its stock client dies around T+75s before login.
- Follow-up: Android CI build `16102939` on `aosp-android-latest-release` provides matching
  ARM64 Cuttlefish images, but the ARM host package cannot execute on this x86_64 host. The
  x86_64 host package rejects both `qemu_cli` and `crosvm` here, and cannot run the ARM64 guest.
  The matching x86_64 Cuttlefish image is not useful for this APK: the stock ARM64 APK fails
  with `INSTALL_FAILED_NO_MATCHING_ABIS` on both Google APIs and Google Play x86_64 AVDs;
  both report `ro.dalvik.vm.native.bridge=0`. The remaining viable route is a real ARM64
  device/runner, or an emulator/runtime that explicitly supplies ARM64 translation.


### Official iOS iCloud-password prompt - investigation boundary (2026-08-29)

- Reported symptom: the unmodified official iOS client repeatedly presents an iCloud-account
  password prompt despite an already-signed-in Apple account.
- Repository evidence: there is no IPA/XCArchive, entitlement, provisioning profile, iOS device
  log, crash report, or iOS-native source here; the server has no CloudKit, StoreKit, GameKit, or
  Sign in with Apple implementation. It only records the client-supplied account type (`2`
  GameCenter, `3` AppleID) after login. Therefore no private-server response is evidenced as the
  direct source of this OS-owned prompt.
- Do not attribute the prompt to a particular Apple service without its exact text and device log.
  The discriminating evidence is the presenting framework/caller in Console/sysdiagnose, plus the
  official IPA's entitlements. Candidate owners to distinguish are Game Center authentication,
  iCloud Keychain/CloudKit, and StoreKit receipt/restore; they require different fixes.
- App Store lookup on 2026-08-30 confirms official iOS `172.1.00` (released 2026-08-26) declares
  Game Center support. `scripts/capture_ios_auth_logs.sh` captures and redacts the relevant
  device log services over USB, so the presenting Apple framework can be identified before an
  IPA patch is considered.
- **Cause confirmed from the on-device v172.1.00 capture (2026-08-30): this is StoreKit, not
  Game Center/iCloud.** At `07:51:31` `storekitd`, proxied by
  `com.awesomepiece.castle`, requests the IAP catalog and transaction/entitlement caches. At
  `07:51:32.300` it starts `TransactionHistoryRequest` with
  `AccountRequirement.forceAuthentication(useBiometrics: false)` for the KGC production client;
  `appstored` then faults that an interactive authentication was requested by a background daemon
  (it should use silent-preferred) and at `07:51:33.935` presents the Apple Account password UI.
  The client must not launch that force-auth transaction sync during boot: defer a user-initiated
  restore/purchase refresh until the shop action, and use a non-interactive entitlement/cache
  read for launch. This cannot be corrected by the game server; it requires an official iOS source
  change or a legally supplied, inspectable IPA. The log has one prompt event in this run.
- A first revision of the capture script did not redact quoted `storekitd.CacheAccount(token: ...)`
  values. The stored `.log` files are already ignored by Git, but treat that original capture as
  sensitive and do not upload it. The script now redacts quoted token, GUID, credentials and email
  values before writing new captures.

## 5. Reward vocabulary (2026-08-09/18)

- Wire types are CLIENT strings (`InventoryItem`, `Key`, `Gold`, `Cash`, `Heart`, `UnitSoul`,
  `CardSoul`, `Artifact`, `Treasure_*`, `Skin`, ...) - there is **no `"Item"`**; an unmatched
  type renders a wrong icon + nonsense count. Internal state keys translate at the wire boundary
  in `_wire_rewards()` (`_reward_list_data()`); state keys never move.
  Test: `server/tests/test_reward_vocabulary.py`.
- **`Key` = ShopItem id**, not inventory id: `<Reward Type="Key" ID="370">` → ShopItem 370,
  `<KeyItem>` names the inventory row (370→380, 70000→70005). `missions.key_item_for()`.
- Safe way to gift artifacts/treasures/accessories: send a **reward box** (Item reward), the
  player opens it. Direct Artifact/Accessory injection can trip panel invariants
  (ArtifactOptionUI crash - see AGENTS.md).
- Dashboard catalog: `GET /api/catalog` (173 items / 73 units / 318 artifacts / 60 treasures /
  108 accessories, names from `Strings_EN_US`).

## 6. Dimension gacha & cards (2026-08-09)

- Dimension heroes (e.g. D.Ophelia 10790) use `overcome` (0-5), NOT `soul`; first pull sets
  `overcome=1`, duplicates increment. Never delete the card to "reset" - set `overcome`.
- Both buy paths (`server/shop_routes.py`): `_grant_reward()` return → `pull["upgrade"]`,
  `rg["type"]="DimensionOvercome"`, and **`newUnitIds` + `cardExpResults` are mandatory** -
  without them the client's card state is stale until restart.
- `card_to_dict()` REQUIRES `unitId` in the card dict (server.py:340) - missing it crashes
  `/card/all` → all heroes show "Not Owned".
- Gacha `<KeyItem>` ≠ Shop `<KeyItem>` (8001→70000, shop 70000→70005) - prefer the gacha's.

## 7. Awakening / potentialTier (2026-08-01)

- `potentialTier`: 0 = not awakened, 1 = max. Seed MUST be 0 (`default_player.json` had 1 →
  every fresh hero showed "Thức tỉnh 1"). Client enables only at `level==16 && tier==0`.
- Upgrade endpoint exists and is correct: `POST /card/upgradePotentialTier` (client gates).
- Slot selection: `POST /deck/setPotential` `{presetIdx, idx, unitId, potential}`.
- ObscuredInt fields read as 20-byte pairs via thunk RVA `0x2B84070` (v171.0.00) - static
  analysis without Ghidra: capstone straight off the .so, file = RVA-0x4000.

## 8. CDN / master data (2026-07-05)

- `docs/cdn-master-data.md` - bundle rebuild, Strings gotchas (no XML comments in
  Strings_*.xml - breaks the whole locale's Localizer), Skill/Unit key-redirect trick.
- Tools: `server/builders/rebuild_xml_bundle.py`, `server/builders/refresh_master_data.py`; pristine backup
  `server/real_cdn/xml.bak` (md5 `779193a15d1377a7b8c2e6edfbe94095`).
- **Host rebinding needs two passes**: `patch_hosts.py` (stringLiteral table) +
  `patch_leftover_hosts.py` (field/parameter defaults - `castle-infra-server…run.app`,
  `kgc-cdn-1.awesomepiece.com/patch/`). Verify 0 real hosts remain after.

### 8a. Adding a distinct skin asset set (Frieren/Farael, 2026-08-20)

- Never point a new skin row at an existing skin's `<Prefab>` / `<Sprite>` names and then replace
  that Texture2D. `1057002` owns `Unit_10570_02`, `Unit_10570_02_0..18`, prefab
  `Unit_10570_02`, and `Unit_Illust_10570_02`; overwriting either texture changes the original
  Morning Star skin too.
- Frieren `1057003` uses the independent namespace `Unit_10570_03`:
  `server/cli/inject_skin.py` restores pristine `base_assets.apk`, clones the sprite Texture2D plus
  all 19 Sprite sub-assets, clones the prefab hierarchy/components plus its 10 AnimationClips and
  AnimatorController while sharing materials/VFX/MonoScripts, remaps its 20 external sprite PPtrs,
  and clones the illustration Texture2D/Sprite as `Unit_Illust_10570_03`. Every cloned Sprite gets a
  deterministic render GUID distinct from `02`; retaining `m_RenderDataKey` can make Unity resolve
  the source Sprite or render the cloned portrait empty. It also adds matching AssetBundle
  container/preload rows; cloning serialized objects without those rows does not make them loadable
  by name.
- `Unit_10570_02` is a **650x560 atlas of 19 fixed 130x140 frames** (5 columns, then four
  frames in the final row); every Sprite uses pivot `(0.5, 0.235)`. Its serialized
  `SpriteSheetData.sheets` gives the runtime order: Front = `0,1,2,3,4,18`, Side =
  `5,6,7,8,9,5`, Back = `10,11,12,13,14,10`; `15..17` are magic silhouettes. This mapping is
  authoritative - frame 18 is the front-facing prefab/thumbnail idle, not a side/run frame.
  `Unit_10570_02_reference.png` is the unmodified 650x560 Texture2D extracted from the v172
  `base_assets.apk` sprites bundle; it is a **geometry-only** input and never a character-design
  reference. `server/cli/rebuild_frieren_sprites.py` rebuilds a direct 5x4 Frieren design board:
  cells 0..18 map one-to-one to runtime frames and cell 19 remains transparent. It fits each
  generated pose into the original frame envelope at integer coordinates with NEAREST only, locks
  the final atlas to a shared 20-colour no-dither palette, and normalizes frames 15..17 to a
  white/cyan magic silhouette. The design board (`Frieren_source_design.png`) must be created from
  Frieren-only design reference; never reuse the `02` character's face, hair, costume, palette, or
  staff. Reproducible inputs/outputs live under `server/assets/frieren/`:
  `Frieren_source_design.png`, `Unit_10570_02_reference.png`, `Unit_10570_03.png`, and
  `Unit_10570_03_comparison.png`.
- `inject_skin.py` consumes those repository assets directly (no `/tmp/farael_assets` dependency).
  Run the atlas rebuild first, inspect `Unit_10570_03_comparison.png`, then run the injector. The
  original `Unit_10570_02` hash check is the guard against ever modifying Morning Star again.
- AssetBundle container rows are still insufficient: Addressables resolves the XML names through
  `assets/aa/catalog.json`. A missing catalog key produces exactly this symptom: the skin XML row and
  name render, but the thumbnail/pixel prefab are blank and the large portrait falls back to the
  unit's default illustration. The injector therefore clones five compact locations from `02`:
  `Unit_10570_03` (Texture2D + Sprite), `Character_Unit_10570_03` (GameObject), and
  `Unit_Illust_10570_03` (Texture2D + Sprite). The first illusts-bundle clone passed offline checks
  but rendered blank at runtime. The target portrait is now stored in the sprites bundle and its
  catalog locations clone the proven sprite-bundle dependency; provider/resource type remain.
  It appends 3 internal IDs, 3 ASCII keys/buckets, and 5 seven-int entry records without changing
  any existing key/index.
- The private v172.0.01 build disables bundle CRC at runtime:
  `AssetBundleRequestOptions.get_Crc` file `0x5FC5F10` returns zero, and direct CRC argument reads at
  `0x5FC8484`, `0x5FC639C`, `0x5FC648C` are replaced with `mov wN,wzr`. Editing catalog ExtraData is
  unnecessary and error-prone; changing the key/bucket/entry tables is required and independent of
  CRC bypass.
- Verification: injector reloads all three bundles, proves the `02` texture/portrait hashes are
  unchanged, checks `Unit_10570_03_18` points at the cloned texture with a distinct render GUID,
  and proves every cloned frame renders through `Sprite.image` as a 130x140 full rectangle. This
  last check is essential: `Sprite.m_Rect` alone does not control rendering. Source `02` stores a
  silhouette-specific `m_RD.textureRect`, `textureRectOffset`, `uvTransform`, tight polygon
  `m_VertexData`, and `m_IndexBuffer`; retaining them crops a wider Frieren pose and Unity then
  magnifies that crop. `_set_full_rect_sprite` replaces all 19 target render records with a
  four-vertex quad covering the declared cell while preserving pivot `(0.5, 0.235)` and PPU 1.
  The illustration Sprite has the same trap: cloning `Unit_Illust_10570_02`'s 908x912 tight mesh
  over Frieren's 1024x1024 portrait cuts the face/body into holes even though the Texture2D and
  catalog key are correct. The injector now applies the full-rectangle quad to
  `Unit_Illust_10570_03` too and verifies `Sprite.image == (1024,1024)` plus its cloned texture PPtr.
  The XML row explicitly sets `<IllustSprite>Unit_Illust_10570_03</IllustSprite>`; this matches the
  client's inferred default but removes inheritance/format ambiguity during diagnosis.
  Frame semantics still matter after the geometry is fixed: `Unit_10570_03_18` is both the prefab's
  default Sprite and the `<Sprite>` used by the skin thumbnail. A running pose in cell 18 therefore
  makes both UI surfaces look wrong even when every PPtr/UV is valid. The production atlas maps
  frame 18 to the board's calm **front-facing** standing pose with a complete vertical staff. `--frame18`
  remains available only as an explicit optional override; the obsolete side-facing v2 override
  is no longer the default. Runtime confirmation of the new sprites-bundle portrait placement is
  still pending user inspection; do not mark it solved solely from UnityPy verification.
  The verifier also confirms both prefabs coexist with disjoint 10-clip/controller dependencies,
  and checks all five new catalog locations resolve to the three new asset paths. Rebuild
  `server/real_cdn/xml`
  afterward so skin `1057003` points at `Unit_10570_03` / `Unit_10570_03_18`.

### 8b. Unit_10570 animation clip semantics (2026-08-20)

The 19 atlas cells are selected by `SpriteSheetData.SetSheet` + `SetSpriteIndex`; they are
not played as one linear 0→18 animation. In the v172.0.01 `characters_assets_all` bundle,
`AnimatorController Unit_10570` has ten clips: `Idle_10570`, `Run_10570`,
`Attack_{Front,Side,Back}_10570`, `Shoot_{Front,Side,Back}_10570`, `Skill_10570`, and
`End_10570`. The directional sheet arrays are:

```
Front:  index 0,1,2,3,4,5 -> atlas frames 0,1,2,3,4,18
Side:   index 0,1,2,3,4,5 -> atlas frames 5,6,7,8,9,5
Back:   index 0,1,2,3,4,5 -> atlas frames 10,11,12,13,14,10
```

Clip event timelines (60 Hz clips, seconds):

| clip | events / visual role |
|---|---|
| `Idle_10570` | `SetSpriteIndex(5)` at 0.0 → Front idle frame 18 (prefab/thumbnail pose) |
| `Run_10570` | `SetSpriteIndex(0)` → directional frame 0/5/10; locomotion base |
| `Attack_Front` | frame 1 at 0.0 (wind-up), `ShootSkill` + frame 2 at 0.333 s (release), end 0.667 s |
| `Attack_Side` | same timing using Side frames 6→7 |
| `Attack_Back` | same timing using Back frames 11→12 |
| `Skill` | frame 3 at 0.0 (cast/wind-up), `ShootSkill` + frame 4 at 0.333 s (active cast), `SkillEnd` at 2.667 s |
| `Shoot_Front/Side/Back` | one-shot projectile pose: directional index 4 → frame 4/9/14 |
| `End` | index 0 at 0.0, `SkillEnd` at 0.333 s; returns from skill/action |

The facing sheet is selected by the unit's direction blend/state (`Dir_Blend`); clips reuse the
same index meanings across Front/Side/Back. Therefore frame 0 specifically means the first
directional locomotion/base pose (front-facing when the active sheet is Front), not the idle pose
and not a generic thumbnail. Frame 1 is front attack wind-up, frame 2 the front attack release,
frame 3 skill wind-up, and frame 4 the front shoot/active pose. Frame 18 must remain the calm
front idle because the prefab default Sprite and skin thumbnail point to it. A reskin must preserve
these action roles and staff/hand anchors per frame.

## 9. Content-unlock gates (2026-07-11)

- Accessory/treasure/rift-weapon unlock keys off **invasion cleared difficulty**
  (`ResourceChallengeSeason.Constants`: Treasure=1, **Accessory=6**, RiftWeapon=11, Max=25;
  invasion II-1 = diff 6). `[Corruption]` tag is a red herring.
- `data/response_config.json` `invasionUnlockedDifficulty` = 6 (≥11 unlocks rift-weapon too).
- `r_player()` emits per-theme records with `"difficulty": unlocked` - it previously used the
  loop var `d` (1..unlocked) so `.First().difficulty` returned 1 and 6/11 stayed locked
  (masked by treasure=1 working). The `d`-loop still pads list length for
  `ProfilePanel.ReloadChallenge`.
- Accessories: `load_corruption_accessories()` builds the 4 real Invasion II-1 rewards from
  `FixedAccessoryPresets.xml` IDs 2000-2003 (valid stat keys - `mainStat="ATK"` was garbage).

### 9a. Accessory change-sub-stat - duplicate-tier decode (2026-08-18, d843ed5)

**Client models (v172.0.01)**: `AccessoryChangeSubStatRequestModel{accessoryId, targetSubStat,
itemId}` - `targetSubStat` is the **OLD** stat (confirm panel `_targetSubStatName` =
`beforeStatNames[targetIndex]`). Response `AccessoryResultResponseModel{accessories,
deletedAccessories, playerGold, playerCash, inventories, addedExpItems}` - exactly what
`_make_result_response` sends; the client's `AccessoryModel.data.subStats` = `List<{key,value}>`
objects (NOT strings - the parallel `subStats: List<string>`/`subStatScores: List<float>` are a
second, deduped view).

**Client apply path**: `<OnClickConfirm>d__17.MoveNext` (RVA 0x334FF70) → success → `GameManager`
@ RVA 0x305B060: for each response accessory, find by id in the owned list then
**`CopyFrom` (RVA 0x2CCCAC0 = shallow field copy, no merge)** - list entries are never replaced,
only field-copied; not-found → append; then remove `deletedAccessories`, apply gold/cash.

**Root cause of "chosen stat applied + extra lower-tier stats"**: `FixedAccessoryPresets.xml`
tier lines are additive duplicates of the same key (e.g. 6× `BaseDefDen 4.0` + 1× `2.0`), and
`make_fixed_accessory` kept every line as its own `data.subStats` entry (only the parallel lists
were deduped). The client renders `data.subStats`, so seeded accessories showed 7-8 stat lines;
the change handler replaced only the FIRST copy, leaving the rest as "extras" (and handing the
full summed score to the new stat while the leftover copies kept their own - inflated pool).

**Fix (server-side only)**: `make_fixed_accessory` (both copies: `routes/accessory.py` +
`routes/rewardbox.py`) builds `data.subStats` from the deduped `scores` dict (one entry per key,
value = score × unit); `ensure_accessory_state` merges duplicates in existing saves (heal -
38/38 live players fixed at deploy); `r_accessory_change_sub_stat` removes ALL `target_stat`
entries and inserts one `new_stat` entry with the summed score at the first removed index.
Regression: `test_accessory_merge_duplicate_substats` in `server/tests/test_accessory.py`.
Verified live: dev-0001 acc 62 `[AtkPer 26.0, BaseDef 80.0]` after manual remnant cleanup
(the old handler had given AtkPer the full 26 pool while leaving BaseDefDen 22 behind).

## 10. Post/mail system (2026-07-11)

- Inbox = "Post": direct handlers `GET /post`, `POST /post/receive`, `POST /admin/sendmail`
  (registered before the ROUTE_MODELS loop - generated models lack `posts`).
- `title`/`text` are localization KEYS (fallback `Post_Title_Default`); `@raw:` prefix bypasses
  the Localizer via the native `PostListItem.Set` hook (strip at write, re-add at read -
  `_process_posts`).
- `RewardResponseData.type` = client vocabulary (see §5). Test:
  `server/tests/test_rename_and_mail.py`.

## 11. il2cpp hook techniques (stub.cpp)

- **methodPointer swap**: only Unity-engine-invoked methods (Update/Awake/...). Invisible to
  C#→C# calls.
- **inline detour** (16-byte absolute jump + trampoline): ALL callers incl. direct compiled
  calls. Guard aborts on PC-relative prologue instructions.
- Debug checklist: wrong dlopen handle (`libil2cpp.so is loaded (poll took 0s)` = bug; 1s+
  = right), `r-xp` never matches under ndk_translation (use `dl_iterate_phdr` + `dlpi_addr`),
  `#if 0` left behind.
- Each hook logs exactly one line; a silent failure means the hook wasn't installed.

## 12. Open questions / to verify

- `[GAME/COMPLETE] body=` debug print in `r_game_complete` - confirm from a real battle, then
  remove.
- v172.0.01 `GetReceivableRewardCount` uses a 0-based theme base (theme 0 for pass 0, gate
  fails → 20 not 25) - its own quirk; not our bug, not fixable server-side. Verify against a
  real v172 client if one ever appears.
- One-time `WorldPanel.Reload()` NRE at IL offset 0x00000 - non-blocking, unpinned.
- `deck-reload`/`deck-reload2` v170 patches still disabled (root-cause investigation 2026-07-02,
  never re-enabled - re-derive v171+ offsets if ever needed).

## 13. Strife Battlefield (Colosseum PvP)

### Season display
- `ColosseumSettings.xml`: `CurrentSeasonTheme` = "1,2,6,7,8,10,11,12,13,14,15" matches
  `SeasonTheme Season="72"`. `SeasonThemes` has Season="71" and Season="72".
- Client logic in `HandleSemiSeasonChanged` → `LeagueContentRankBox.Set<Tier>`: the format
  string (`ColosseumBetaSeason` vs `ColosseumSeasonFormat`) is chosen by comparing
  `season` (field offset 0x2C in `PlayerColosseumInfoResponseModel`) against **0x25 = 37**.
  `csel` at RVA 0x3252e18: if season > 37 → uses `ColosseumSeasonFormat` ("Strife Battlefield
  Season {0}"), else → `ColosseumBetaSeason` ("Strife Battlefield Beta Season").
- **Two-step season source (critical)**: the format string selection does NOT read from the
  colosseum response model. Assembly chain: `Il2CppClass → static_fields → _singleton →
  pvpData (offset 0x220) → season (offset 0x2C)`. `GameManager.pvpData` is populated by
  `/pvp/info` (Arena endpoint), NOT `/colosseum`. So both endpoints must return season > 37.
- **Fix (commit 14dc59b)**: `response_config.json` colosseum season `1` → `72`. Outer panel
  gate card showed "Season 72" but inner panel still showed "Beta Season".
- **Fix (commit b4cf13a)**: `response_config.json` pvpInfo season `1` → `72` (and
  pvpInfoDirect `1` → `72`). Inner panel reads `GameManager.pvpData.season`, which comes
  from `/pvp/info`. Old value 1 was <=37, still triggering ColosseumBetaSeason.
- `LeagueContentRankBox.Set<Tier>` signature (RVA 0x3b247d0, file offset 0x3b207d0):
  `Set<Tier>(string seasonFormat, int season, int curSemiSeason, List<LeagueContentScoreData>
  scoreDatas, DateTime seasonUntilAt, DateTime thisSemiSeasonStartAt, DateTime
  nextSemiSeasonStartAt, Func<int, int, Tier> getResTierFunc)`. Does
  `Localizer.Get(seasonFormat)` then `string.Format(result, season)` → `_seasonText.text`.

### Pre-season popup fix
- `_isColosseumPreSeason()` (RVA 0x324fba4): calls `GetSeasonStartAt(colosseumData, 0)` →
  `nextSeasonStartAtDates[max(0, 0-1)]` = `nextSeasonStartAtDates[0]` (clamped). Then checks:
  `nextSeasonStartAtDates[0] > UtcNow` → if TRUE, returns true (pre-season), popup shown.
- `_isSemiSeasonBreakTime()` (RVA 0x324fcf0): calls `GetCurrentSeasonUntilAt()` →
  `seasonUntilAtDates[semiSeason-1]`. Then checks: `seasonUntilAt <= UtcNow` → break time.
- `CheckColosseumEnabled` (RVA 0x32513b4) calls both; if either returns true, shows popup
  and returns false (game start blocked). The popup format is `SeasonEndTimeFormat` with a
  countdown timer using `nextSeasonStartAtDates[0]` (stored at ColosseumPanel field 0xD8).
- **Root cause**: `nextSeasonDayOffsets[0]` was `+16` (future). With semiSeason=2, this meant
  semi-season 1's start date was in the future → pre-season = true → popup.
- **Fix (commit 8753945)**: `nextSeasonDayOffsets[0]` changed to negative values so
  `nextSeasonStartAtDates[0]` is in the past:
  - colosseum (semiSeason=2): `[-30,-15,15]` - semi 1 started 30d ago, semi 2 started 15d ago
  - pvpInfo (semiSeason=1): `[-15,16,31]` - semi 1 started 15d ago
  - `seasonDayOffsets` adjusted: colosseum `[-15,15]` (semi 1 ended 15d ago, semi 2 ends in 15d)
- **Index mapping**:
  - `GetCurrentSeasonUntilAt()` → `seasonUntilAtDates[semiSeason-1]` (end of current semi)
  - `GetNextSeasonStartAt()` → `nextSeasonStartAtDates[semiSeason]` (next global season)
  - `GetSeasonStartAt(semiSeason)` → `nextSeasonStartAtDates[semiSeason-1]` (start of semi)

### Battle flow
- `OnClickStartColosseum` (RVA 0x3250fb8) → checks level gate, opens confirm dialog →
  `GameManager.StartColosseumMatchmaking` (RVA 0x3071578).
- `StartColosseumMatchmaking` → `RestAPI.RequestColosseumMatchmaking` → `POST /colosseum/match`
  → `ColosseumMatchResponseModel{gameId, serverAddress}`.
- Empty `serverAddress` = client falls through to local bot stage (single-player colosseum).
- Battle runs locally → `POST /colosseum/complete-round-data` on completion
  → `r_colosseum_complete_round` handles score update.
- `POST /colosseum/round-data` = round-in-progress snapshot (ack only, no persistence needed).

### Key RestAPI endpoints (all from script.json)
| Method | Endpoint | Response model |
|---|---|---|
| `RequestColosseumMatchmaking` | `/colosseum/match` | `ColosseumMatchResponseModel` |
| `PingColosseumMatchingResult` | `/colosseum/match/ping` | polling for match result |
| `CancelColosseumMatching` | `/colosseum/match/cancel` | ack |
| `FetchPlayerColosseum` | `/colosseum` | `PlayerColosseumInfoResponseModel` |
| `FetchColosseumPlayersData` | `/colosseum/fetch-players-data` | opponent list |
| `FetchColosseumAddressByGameID` | `/colosseum/server-address` | game server addr |
| `SaveColosseumRoundData` | `/colosseum/round-data` | ack |
| `SaveCompleteColosseumRoundData` | `/colosseum/complete-round-data` | score update |
| `ColosseumGetReward` | `/colosseum/get-reward` | tier rewards |
| `ColosseumReceiveAllRewards` | `/colosseum/all-tier-rewards` | bulk claim |
| `GetColosseumRanking` | ranking path | leaderboard |
| `GetColosseumLeagueRanking` | ranking path | league board |
| `GetColosseumHallOfFame` | ranking path | hall of fame |
| `TestColosseumSinglePlay` | `/colosseum/test-single-play` | same as /match |
| `TestColosseumFreeMatching` | `/colosseum/test-free-match` | same as /match |
| `CreateColosseumCustomMatch` | `/colosseum/create-custom-match` | custom lobby |
| `JoinColosseumCustomMatch` | `/colosseum/join-custom-match` | custom join |
| `ColosseumReenterTried` | `/colosseum/reenter-tried` | ack |
| `ColosseumReenterSucceed` | `/colosseum/reenter-succeed` | ack |
| `CheckColosseumReenterEndGame` | `/colosseum/check-end` | ack |
| `ColosseumRecordMinimumRank` | `/colosseum/record-minimum-rank` | ack |
| `GetColosseumOpenMissionReward` | `/colosseum/open-mission-reward` | reward list |

### Key model offsets (v172.0.01)
- `PlayerColosseumInfoResponseModel.season` = field offset 0x2C
- `PlayerColosseumInfoResponseModel.semiSeason` = field offset 0x54
- `ColosseumPanel._leagueContentRankBox` = offset 0x28
- `ColosseumPanel._matchStartButton` = offset 0x50
- `ColosseumPanel._colosseumEnabled` check via `CheckColosseumEnabled` (RVA 0x32513b4)

### All routes registered
All 33 colosseum routes are in `routes/pvp.py` → `handlers()`. The `r_colosseum_match` returns
empty `serverAddress` to trigger local bot battle. `r_colosseum_complete_round` handles score
delta + tier update. `r_colosseum_round_data` is a no-op ack (client replays own rounds).

### Friendly Battle (custom match) - implemented 2026-08-19
The Friendly Battle ("Trận Giao Hữu") lets players create a private room, share a 6-char code,
and play a colosseum match that **does not affect tier, score, or missions**.

**Client flow:**
1. Host taps "Create Friendly Battle" → `POST /colosseum/create-custom-match` (no args)
   → server returns `{lobbyId: "A3WGBF", endPoint: ""}`. Client copies the code.
2. Guest taps "Join Friendly Battle" → enters the code → `POST /colosseum/join-custom-match`
   with `{matchId: "A3WGBF"}` → server validates, returns `{lobbyId, endPoint}`.
3. Both players call `POST /colosseum/fetch-players-data` with `{isCustomMatch: true}`
   → server returns actual lobby members (not random opponents).
4. Host starts the match → `POST /colosseum/match` → `{gameId, serverAddress: ""}`.
   Empty serverAddress = local bot play (same as regular colosseum).
5. After battle: `POST /colosseum/complete-round-data` - same handler as regular, but
   friendly matches are NOT supposed to affect score. (Currently they still do because the
   client sends the same `win` flag - a `gameType` field would be needed to differentiate.)

**Server implementation:**
- Lobby state stored in SQLite `lobbies` table (migration v5 in `playerdb.py`):
  `code TEXT PK, host_uid TEXT, members TEXT (JSON array), created_at REAL`.
- `lobby_create/code`, `lobby_get/code`, `lobby_join/code/uid`, `lobby_leave/code/uid`,
  `lobby_leave_by_uid/uid`, `lobby_members/code`, `lobby_get_by_uid/uid`.
- Host leaving → lobby deleted. Non-host leaving → member removed, lobby stays.
- Max 4 members per lobby.
- Lobby code: 6-char uppercase alphanumeric, no ambiguous chars (0/O, 1/I/L).
- `_gen_lobby_code()` retries up to 100 times to avoid collisions.
- `_colosseum_custom_players(st)` loads each member's state and returns their
  `ColosseumPlayerData` (deck, buildings, etc.).

**New routes added:**
| Route | Handler | Purpose |
|---|---|---|
| `/colosseum/create-custom-match` | `r_colosseum_create_custom_match` | Generate lobby code |
| `/colosseum/join-custom-match` | `r_colosseum_join_custom_match` | Validate code, join lobby |
| `/colosseum/leave-custom-match` | `r_colosseum_leave_custom_match` | Leave lobby |
| `/colosseum/custom-match-start` | `r_colosseum_custom_match_start` | Start match, return gameId |
| `/colosseum/check-end` | `r_colosseum_check_end` | Reenter: return score delta |
| `/colosseum/reenter-tried` | `r_colosseum_reenter_tried` | Reenter: ack |
| `/colosseum/reenter-succeed` | `r_colosseum_reenter_succeed` | Reenter: ack |

**Key client strings (from Strings_EN_US.xml):**
- `ColosseumCustomMatch` = "Friendly Battle" / "Trận Giao Hữu"
- `ColosseumCustomMatchCreate` = "Create Friendly Battle"
- `ColosseumCustomMatchJoin` = "Join Friendly Battle"
- `InputColosseumCustomMatchCode` = "Enter Participation Code"
- `ColosseumCustomMatchDesc` = "Friendly Battles do not affect your tier, score, and missions."
- `ColosseumCustomMatchRoomFull` = "This room is full!"
- `ColosseumCustomInvalidMatchCode` = "Invalid code."
- `ColosseumCustomMatchHostExited` = "This room has been terminated."
- `ColosseumCustomMatchEmptyItem` = "Empty Slot"
- `ColosseumCustomMatchAddBot` = "Create {0} Bot"

**TODO:** A proper score-skip for friendly matches would require the client to send a
`gameType` or `isCustomMatch` flag in the `complete-round-data` body, which it currently does
not do. For now, friendly matches count toward score like regular matches.

## 14. Frieren Aseprite frame-0 review draft (2026-08-20)

- The prior `server/assets/frieren/Frieren_frame_00.aseprite` / `Frieren_frame_00.png` paths are
  stale (verified absent). The current review-only artifact is the v4 pose-matched redraw
  `server/assets/frieren/drafts/00_frieren_frame_0_v4.aseprite`, with native PNG, 1x/4x/8x
  previews, source-vs-Frieren comparison, constraint JSON, and build entry point at
  `pixel-art/frieren-frame-00/build_frieren_v4.py`.
- Frame 0 is a one-cell 130×140 transparent RGBA redraw. The original sprite is used as the
  pose/layout reference (head, hands, feet, staff diagonal); the illustration and a dedicated
  render supply Frieren identity. The result is palette-locked, nearest-neighbour reduced to the
  68×75 cell, and hard-alpha cleaned. Bbox `(46,38)-(108,109)` is close to source
  `(45,38)-(108,108)`; the illustration itself is not cropped into a sheet.
- This is pending user visual approval only; it does not replace `Unit_10570_03.png` or enter the
  injector/build path. Do not infer or draw frames 1-18 without explicit approval.

## 15. Codex pixel-art skill stack (2026-08-20)

- Codex skills live at `/home/nowl/.codex/skills`. `generate2dsprite` is a symlink to the checked
  Agent Sprite Forge source at `/home/nowl/tools/agent-sprite-forge`; its isolated `.venv` has
  Pillow and numpy. `pixel-art-studio` is a Codex-adapted copy with deterministic Pillow tools,
  Aseprite-compatible JSON export, Codex-specific iterative three-pass instructions, and no
  remaining hard-coded `.claude`/`/Users` installation paths. `pixel-sprite-reskin` enforces a
  source-sheet geometry/pose lock for skins.
- Aseprite CLI (`/usr/bin/aseprite`, v1.3.18.2-dev) and the `aseprite` MCP server are already
  configured in `/home/nowl/.codex/config.toml`; do not replace that configuration. Use
  `/home/nowl/sprite-skill-test/` for a minimal validated 32×32 transparent test asset.

## 16. Generated Frieren production reskin (2026-08-20)

- The complete production review export is now
  `server/assets/frieren/generated/frieren_sprite_sheet_650x560.png`; individual native frames
  are under `generated/frames/00.png` through `18.png`. It is a 5×4 650×560 RGBA atlas with
  130×140 cells and an intentionally transparent cell 19.
- `generated/build_frieren_sprite.py` is the reproducible build: it uses
  `Unit_10570_02_reference.png` strictly for each cell's bbox/baseline/placement and the
  independent Frieren design board strictly for character identity. It hardens every output edge
  to binary alpha and a shared 22-colour Frieren material palette; frame 15-17 use the isolated
  cyan/white silhouette palette. The large source board is retained as
  `generated/frieren_design_master.png`, with 19 high-resolution editable pose crops in
  `generated/design_frames/`; only those crops are reduced once, with NEAREST, for the game atlas.
  Do not replace this with a whole-atlas resize.
- `generated/validate_sprite.py` verifies atlas/frame dimensions and mode, binary alpha, an empty
  final cell, and byte-exact integer grid placement. The last run passed. `geometry_constraints.json`
  records the measured source envelopes and was checked against every output frame.
- Editable outputs are `generated/frieren_sprite_sheet.aseprite` (atlas) and
  `generated/frieren_animation.aseprite` (19 130×140 timeline frames). Its contiguous semantic
  tags are Front_Base 0-4, Left_Base 5-9, Back_Base 10-14, Magic 15-17, Idle 18; the non-contiguous
  runtime loops are recorded in `generated/animation_mapping.json`.
- Accessory correction pass: the staff head now uses the reference's gold ring + red gemstone
  treatment consistently across full/side/back/idle poses, preserving the original shaft angle,
  ribbon anchor, and source geometry envelopes. Rebuild and Aseprite exports were regenerated and
  visually checked after this pass.

## 17. Client UI → web UI fidelity baseline (2026-08-24)

- Do not recreate KGC screens from a screenshot with CSS. Trace the matching-version IL2CPP
  controller first, export the original Unity `Sprite` assets, then capture the actual client
  render as the initial visual baseline. Full playbook: `docs/web-ui-reconstruction.md`.
- Verified Hero Detail is `CardInfoPanel` (v172.0.01 `Show` RVA `0x31829FC`), not the
  in-battle `UnitInfoPanel`. It owns tabs Hero/Growth/Profile/Skin (`0..3`) and actions
  `OnClickToggleDotIllust`, `OnClickUnitStatistics`, `OnClickSkillButton`, `OnClickTab(int)`.
- Prototype: `server/hero-detail-prototype/`. The Farael fixture was captured from the running
  v172.0.01 client; hero art `Unit_Illust_10570` and source UI sprites (frame/tab/item/skill/
  treasure) were exported from v172.0.01 bundles. It is intentionally a visual baseline with
  mapped accessible hotspots, not a claim that the screen's state is already web-native.

## 18. Player Portal Phase 1 (2026-08-27)

- Public portal is `GET /` (with `/player` retained as a compatibility route), served from its own
  `playerportal_server:app` process on internal `:8082` (default public hostname
  `https://player.kingbugcastle.id.vn`), from
  `server/webui-next/out/player.html`; static Next assets are mounted at `/_next`. Game API stays
  `kingbugcastle.id.vn → :8080`; admin stays `admin.kingbugcastle.id.vn → :8081`. Build with
  `cd server/webui-next && ./node_modules/.bin/next build --webpack`. The host needs
  `experimental.cpus=1`: default worker fan-out can exhaust its process limit.
- **Identity invariant:** portal never creates a game account/save. Existing `accounts.login_id →
  uid` is authoritative. `google_<sub>` can obtain portal cookie `kgc_player` only after that
  mapping exists; Guest access can be issued only for an existing `Guest_*` mapping by the admin
  dashboard. Guest credential password rotation revokes portal sessions; database stores SHA-256
  token hashes, not browser tokens.
- `google_login.make_state(target)` signs `game|portal`. Target `game` preserves native poller
  handoff and only `server:app` registers `/glogin/callback`. Target `portal` is accepted only by
  `playerportal_server:app` at `/portal/api/auth/google/callback`, then redirects to `/`
  after issuing only the portal cookie. `playerportal_server:app` calls `playerdb.init()` at startup:
  this matters because it can run without the game API, and portal session tables first appear in
  migration v6. Set `PLAYER_PORTAL_PUBLIC_URL` to that hostname and register
  both its callback and the game callback in Google OAuth. Do not route portal sign-in through
  `/glogin/pending` or change the APK stub.
- `SiteShell` portal branch must test `pathname === "/player" ||
  pathname.startsWith("/player/")`. A bare `startsWith("/player")` also matches admin
  `/players`, omits `PlayerProvider`, and makes `/players` prerender fail with
  `usePlayerSelection must be used within PlayerProvider`.
- Phase 2 uses **Google Ad Manager Rewarded Ads for Web**. `ticket_wallets`,
  `ticket_provider_sessions`, `ticket_provider_events` and `ticket_log` were added in migration
  v7. `POST /portal/api/ticket/video/start` creates an opaque `gam` session after local caps;
  the Next portal loads GPT and only shows the video after `rewardedSlotReady`. Its browser-side
  `rewardedSlotGranted` event calls `POST /portal/api/ticket/video/complete`, which consumes that
  session id as its idempotent event id. Cooldown is 5 minutes, wallet cap 10, daily UTC cap 20.
  This is intentionally weaker than a provider server callback: it is accepted for video-only UX,
  so keep ticket value/caps conservative. Config: `GAM_REWARDED_AD_UNIT_PATH` is an absolute GAM
  ad-unit path such as `/123456789/kgc_player_rewarded`.
- Phase 3 self-grant lives in `playerdb.ticket_redeem_grant()`, not in a route:
  it holds `write_lock` and changes the ticket wallet, audit log, player save and derived
  projections in one DB transaction. The portal only exposes the small fixed catalog in
  `playerportal._GRANT_CATALOG` (Gold 50,000; Heart 10; Item 100×20; Item 150×10). It does
  not expose Cash, heroes, treasures, artifacts or accessories. Mail text is stored without
  `@raw:`; `routes.inbox._process_posts()` adds that prefix only on the game wire. Focused proof:
  `python3 server/tests/test_grant_self.py` verifies mail/ticket atomicity, concurrent spending,
  and that a stale login mapping cannot consume a ticket.

### Public portal deployment (2026-08-28)

- Public state is a distinct SQLite file on OCI (`/home/ubuntu/kgc/server/state/players.db`), not
  the workspace DB. The Player Dashboard must run on the OCI host to share its game account,
  ticket and mailbox transactions. It is enabled as `kgc-playerportal.service`, bound only to
  `127.0.0.1:8082`; its first start migrated the live database from schema v5 to v8 after the
  normal automatic backup.
- Caddy owns public `80/443` and proxies `kingbugcastle.id.vn → :8443`,
  `admin.kingbugcastle.id.vn → :8081`, and `player.kingbugcastle.id.vn → :8082`. Its tracked
  sources are `systemd/caddy.service` and `systemd/kgc-public.Caddyfile`; it runs unprivileged
  with only `CAP_NET_BIND_SERVICE` and reads a root-owned copy of the existing self-signed origin
  key. Cloudflared is instead a Docker container (`cloudflare/cloudflared`, bridge networking,
  restart `always`), whose remotely managed Zero Trust ingress currently owns the public hostnames.
  The portal must remain loopback-only: do **not** point its tunnel service at
  `http://213.35.110.245:8082`, because Docker cannot reach that listener. Route it via Caddy
  (`https://213.35.110.245:443` with origin TLS verification disabled for the self-signed
  certificate) while retaining the `player.kingbugcastle.id.vn` Host header. The external hostname
  must also have the Cloudflare Tunnel CNAME/DNS route; a tunnel ingress rule alone does not publish
  DNS. Origin Caddy health returned HTTP 200 for the player host header.

### Player Portal Phase 4-5 (2026-08-28)

- Requests: `grant_requests` (v8) records the resolved game uid at submit time. Submit debits one
  ticket and writes `ticket_log(request)` in the same transaction; approval mails the admin-selected
  reward, denial refunds exactly one ticket and mails the reason. `resolve_grant_request()` owns its
  flock, so dashboard's generic write middleware must skip `/api/requests/*` to avoid a nested
  `flock` deadlock. UI: portal request panel + admin `/requests`. Proof:
  `test_requests.py` and `test_requests_api.py`.
- Donations: v9 adds `donations`, including `credited_at`, `credited_by` and `credited_tickets`.
  A portal note is only an acknowledgement - it cannot credit tickets. `admin_credit_tickets()` is
  the sole credit path, logs `admin_topup`, and atomically marks a donation credited so retries fail.
  The player form is available both on the dashboard and `/player/donate`; admin UI is `/donations`.
  `PLAYER_DONATE_INSTRUCTIONS` comes from optional `/etc/kgc/playerportal.env`, deliberately blank
  until an operator supplies payment instructions. Proof: `server/tests/test_donate.py`.

## 19. Project audit - release blockers (2026-08-28)

- **Route coverage now defaults to v172.0.01** and accepts
  `KGC_IL2CPP_SCRIPT_JSON` for an extracted artifact elsewhere. The verified v172.0.01 artifact is
  at `il2cpp/v172.0.01/script.json` locally (SHA-256
  `27349c11aafdae1632719de6d017d0409456be927dfff7044075892204a33445`); it is intentionally
  untracked because it is generated from the proprietary client. It contains 261333 methods and
  25742 strings; the v172.0.01 anchors `GetRankingServerEndPoint` (`0x2CBF2C4`),
  `RegisterHackDetectionCallback` (`0x34E4EDC`), and `CheckFirebase` (`0x30479B8`) match. Keep
  this exact artifact alongside the deployed server, or set `KGC_IL2CPP_SCRIPT_JSON` to its
  absolute location. Do not substitute the known-stale generated route list.
- **OAuth state secret hard-code removed.** Public/portal scripts and the portal systemd unit now
  require `GLOGIN_STATE_SECRET` from deployment configuration; preflight fails if real Google OAuth
  is enabled without it. The old tracked value must be treated as leaked and rotated on the host.
- **Direct request readers share the streaming cap.** `security.read_capped_body()` is used by the
  generic dispatcher, direct accessory/post routes and admin mail; an oversized chunked request
  receives 413 before it is buffered. Proof: `server/tests/test_body_limit.py`.
- **Sensitive debug logs removed from served routes.** Dashboard no longer prints request headers;
  game/auth/shop/rift/artifact routes no longer write whole request bodies or cookie fragments.
  `r_card_use_candy` must not create `scroll_debug.txt`: that untracked runtime file dirties the
  production checkout and makes the guarded deploy hook refuse every later rollout.
- **Public deployment configuration is externalized.** `serve_public.sh` and `deploy_hook.sh` load
  `/etc/kgc/server.env` (override `KGC_ENV_FILE`) before preflight; on a personal machine with no
  `/etc/kgc`, they fall back to ignored, mode-600 `server/secrets/server.env`. Stand-alone
  `preflight.py` reads the same simple `NAME=value` configuration without executing it as shell
  code. This makes the OAuth state key, v172 `script.json` location, and proxy/loopback pairing
  survive non-interactive deploys. `deploy_hook.sh` now refuses a dirty checkout and
  dependency-install failure instead of stashing, swallowing errors, and potentially reloading an
  inconsistent tree.
- **Public OAuth origin respects deployment configuration.** `serve_public.sh` now treats
  `https://kingbugcastle.id.vn` as its fallback only; an operator-provided `GLOGIN_PUBLIC_URL` from
  `/etc/kgc/server.env` is no longer overwritten after that file is loaded. Proof:
  `server/tests/test_deploy_config.py`.
- **Public XAPKs can now use either the Cloudflare hostname or the origin IP.** The CI workflow
  accepts `glogin_poll_port` (public default `80`), and `build_private.py` patches that value into
  the native raw poller; local builds keep their `:8080` default. `kgc-public.Caddyfile` proxies
  both `kingbugcastle.id.vn` and `213.35.110.245` to the loopback TLS game service. The direct-IP
  routes strip client-supplied Cloudflare/forwarded-IP headers and replace `X-Forwarded-For` with
  Caddy's peer address; the domain route accepts only Cloudflared's private Docker bridge before
  preserving `CF-Connecting-IP`. This retains the source-address invariant of the Google native
  handoff while allowing either baked `share_host`. Regression proof:
  `test_public_caddy_serves_the_game_through_domain_and_origin_ip_safely` and
  `test_native_poll_port_is_patched_relative_to_the_browser_host_buffer`. The Caddy binary is not
  installed in this workspace, so validate and reload `/etc/caddy/Caddyfile` on the origin before
  releasing the XAPK.
- **Preflight refuses the dev Google-login bypass.** `GLOGIN_DEV=1` can create an authenticated
  session without real OAuth and is valid only for a local development command. It is now a FAIL,
  not a WARN, so `serve_public.sh` cannot expose it accidentally. Proof:
  `test_preflight_refuses_the_google_dev_login_bypass`.
- **GAM rewarded-video completion is browser-asserted, not provider-verified.** The portal now
  rejects both browser start/complete calls with 503 even if an ad-unit path is configured; tickets
  stay protected until a provider-verifiable server callback calls the existing accounting helper.
- **Standalone portal gets the same public request boundary.** `CappedBodyMiddleware` limits bytes
  at the ASGI receive layer before FastAPI can buffer a chunked `body: dict`; checking only
  `Content-Length` or guarding route readers leaves that bypass. `security.register_portal()`
  installs this cap and the shared per-IP rate limiter for `playerportal_server:app`, without taking
  the game-save lock (portal ticket/grant transactions retain their own DB lock). Proof:
  `server/tests/test_portal_body_limit.py`. It buffers no more than the cap and replays with
  Starlette's own `_CachedRequest` receive bridge, preserving nested middleware's response-disconnect
  lifecycle rather than fabricating a disconnect itself.
- **Dashboard uses the public boundary too.** `dashboard.py` owns its own cross-process transaction
  lock, but its `body: dict` administration endpoints were otherwise outside the game middleware.
  It now installs `security.register_public()` in the enforced order: body cap → rate limit → admin
  guard → Dashboard write lock. This prevents oversized or unauthorized writes from occupying the
  lock while retaining Dashboard's atomic edits.
- **Dashboard mutations have a server-side CSRF check.** When a browser sends `Origin`, it must
  match the dashboard host (using `X-Forwarded-Proto` only under trusted-proxy mode); a foreign
  origin receives 403 before the admin/session logic. Origin-less local operator calls remain
  supported. Proof: `server/tests/test_dashboard_origin.py`.
- **Dashboard admin cookies are HTTPS-only when the browser is HTTPS.** Local direct HTTP remains
  available for development, while a trusted public proxy's `X-Forwarded-Proto: https` now sets the
  `Secure` cookie attribute. This prevents the authenticated cookie from being sent over a later
  cleartext request to the same dashboard host. Proof: `test_dashboard_cookie_is_secure_only_for_the_browser_facing_https_scheme`.
- **Dashboard static fallback stays inside its export root.** Route paths are resolved before every
  `FileResponse` and must remain under `webui-next/out`; a `..` traversal can no longer read Python
  source, secrets, or arbitrary sibling files from the dashboard origin. Proof:
  `test_dashboard_static_fallback_cannot_escape_the_export_root`.
- **Manual portal launch matches systemd.** `serve_playerportal.sh` now loads
  `/etc/kgc/playerportal.env` (override `KGC_ENV_FILE`), binds `127.0.0.1` by default, and rejects
  `KGC_TRUST_PROXY=1` on a non-loopback bind. This prevents its old `0.0.0.0` default from exposing
  a service intended to live behind Caddy/Tunnel. `bash -n` and the invalid trust/bind combination
  were checked.
- **The development stack is a cross-platform Python TUI and loopback-only by default.**
  `server/run.py` supervises game HTTP/TLS, admin, and Next.js on Linux/macOS with POSIX sessions
  and on Windows with native process groups plus `CTRL_BREAK_EVENT`/`taskkill` fallback. It finds
  both `.venv/bin` and `.venv/Scripts`, stores logs in the platform temp directory, and gets curses
  from the conditional `windows-curses` dependency on Windows. Enter/a/x/r control processes,
  `d` wires ADB, and `q` stops the owned groups. All services bind to `127.0.0.1`; LAN testing remains
  an explicit `KGC_DEV_BIND_HOST=0.0.0.0` opt-in. Proof:
  `test_development_launcher_binds_loopback_unless_lan_access_is_explicit` and
  `test_development_launcher_stops_the_process_group_it_started`, plus the simulated Windows
  process-group/configuration checks in `server/tests/test_deploy_config.py`.
- **Google pending handoff is address-bound.** The old fallback consumed the newest pending entry
  for *any* source address (and, in local split-brain mode, fetched an entry from a different
  server). Because the result is a Google account id accepted by `/auth`, that was an account
  takeover path. `_get_and_clear_pending()` now reads only its hashed source-address slot and
  `_client_ip()` delegates to `security.client_ip()`, so forwarded headers are trusted only under
  the existing loopback-bound proxy invariant. Runtime `.glogin_pending_*` handoff files are ignored
  by git. Proof: `server/tests/test_google_pending_security.py`.
- **Google pending handoff is atomically published and claimed.** The OAuth callback now writes a
  temporary same-directory file and atomically replaces the address-bound slot. Pollers atomically
  move that slot into a unique claim file before reading it, so they cannot see an empty partial write
  or return the same account id twice during an overlapping native-poller transition. Proof:
  `test_pending_google_account_is_published_and_consumed_once`.
- **Native `/auth` cannot mint a session for an arbitrary Google ID.** The endpoint previously
  treated query parameter `id=google_<sub>` as proof of Google authentication, which permitted a
  caller who knew an ID to obtain that account's bearer token. Retrieving `/glogin/pending` now issues
  a 60-second, one-time, address-and-account-bound native-auth grant; `/auth` consumes that grant
  before it can mint a session. The grant is atomically claimed and rejects different IDs, addresses,
  replays, and expiry. Proof: `test_native_google_auth_grant_is_address_bound_fresh_and_single_use`;
  the full native-route test now proves a direct request is denied before the poller handoff.
- **Runtime maintenance is UTC-aware and lifecycle-owned.** `common.now_iso()` and
  `next_reset_iso()` now use `datetime.timezone.utc`, preserving the client wire format while
  avoiding deprecated naive UTC APIs on supported Python versions. The backup worker is owned by
  FastAPI's lifespan context and is cancelled on shutdown rather than escaping as an orphan task.
  A direct lifespan check confirms exactly one worker starts and none remains afterward.
- **Save reads repair malformed card/deck shape before handlers see it.** A raw-save edit with a
  non-numeric card key, non-dict card/deck, or malformed deck slot previously raised inside
  `playerdb.load()` and made the entire account unloadable. The persistence layer now drops invalid
  cards/entries, normalizes card identity/level, and returns exactly six valid-or-empty deck slots
  plus six non-negative potential slots. Proof: `test_load_repairs_malformed_cards_and_decks_before_routes_use_them`.
- **Account lookups reject non-string credential values.** `/auth/login` may carry its prior token
  in decoded JSON; a dict/list was previously passed to SQLite as a bind parameter and raised
  instead of simply being treated as an unknown token. `uid_for_token()` and `uid_for_login()` now
  enforce their string contract at the shared persistence boundary. Proof:
  `test_identity_lookups_reject_non_string_values_before_sqlite_binding`.
- **External login IDs are bounded database keys.** Identity is now a non-empty string of at most
  256 characters before it can reach the `accounts` index. Auth treats malformed IDs as absent while
  preserving a valid token-refresh path; `bind_login()` rejects them at the persistence boundary so a
  future caller cannot retain an arbitrary request blob. Proof:
  `test_login_identity_is_a_bounded_string_before_persistence` and
  `test_auth_rejects_a_malformed_new_identity_but_allows_session_refresh`.
- **`accountId` is immutable through generic/raw admin saves.** It is the player's unique targetId
  for rankings and profile lookups; a malformed value used to make a leaderboard's integer conversion
  fail, and a pasted duplicate broke identity. `backfill_account_ids()` now treats unparsable IDs as
  missing, while both generic and raw admin writes preserve the row's existing uid/accountId. Proof:
  `test_backfill_repairs_malformed_account_ids_as_missing_identity` and
  `test_dashboard_raw_save_preserves_the_player_account_identity`.
- **Dashboard macro `legacy_max` parses artifact XML correctly.** It referenced `ET.parse()` without
  importing ElementTree, so the macro always failed before granting relics/treasures. The XML parser
  is now imported at the module boundary; a direct macro test executes the branch and verifies maxed
  artifacts plus level-30/overcome-10 treasures.
- **The WebUI standard is pnpm 11.3.0.** `package.json`, development launcher, portal guidance and
  operator docs invoke `pnpm run ...`; existing installed binaries still validate TypeScript and
  ESLint in the restricted environment. pnpm 11 defaults `verifyDepsBeforeRun` to `install`, so the
  launcher passes `--config.verify-deps-before-run=false`; otherwise starting Next.js tries to
  migrate/install the legacy npm-only graph and fails on ignored build scripts. Do not manufacture
  `pnpm-lock.yaml`; migrate it deliberately on a networked development host.
- **Static WebUI export has no production Next proxy.** The `/api/*` rewrite is declared only for
  `next dev`; dashboard and portal serve the exported files themselves in production, so a rewrite
  declaration there is both inert and makes Next warn. `outputFileTracingRoot` is pinned to the
  repository root so an unrelated parent-directory pnpm lockfile cannot expand tracing. A full
  webpack export now builds all 16 static pages without warnings.
- **Runtime dependencies have one authoritative file.** Root `requirements.txt` is the tested
  server runtime contract; `server/requirements.txt` includes it for compatibility and adds
  UnityPy for asset/build flows plus cryptography for setup's cross-platform TLS certificate
  fallback. CI installs the runtime contract plus pytest (not the unused
  `httpx2` package), and CI/deploy path filters include root dependency changes so a dependency
  update cannot silently skip validation or rollout. Workflow YAML parses and the current focused
  test selection passes.
- **Verification drift:** CI currently collects 69 pytest tests; many route-contract checks are standalone
  `check_*` functions and are absent from CI. The WebUI TypeScript and ESLint gates now pass cleanly:
  raw endpoint payloads are narrowed into page-level response types, polling/state synchronization is
  documented at the exact effects that own it, and static image usage uses `next/image` unoptimized
  for the export. Use `pnpm` for future frontend operations; the current tree still has only the
  npm lockfile, and an attempted pnpm import cannot complete in the restricted environment because
  the registry is unavailable. Perform that lockfile migration deliberately on a networked host.
  `pytest.ini` pins pytest-asyncio's pending default to a function-scoped loop. On this Python 3.14
  environment, both Starlette `TestClient` and `httpx.ASGITransport` block before returning from a
  synchronous FastAPI endpoint (reproduces with an empty app); this is a framework/runtime harness
  defect, not evidence of a server deadlock. Use focused async-transport tests here or a compatible
  runtime/real Uvicorn listener for the legacy synchronous-route tests.
  There is also a large dirty worktree (225 entries on audit), including tracked generated frontend
  output; establish an owner/clean-build policy before merging unrelated work.
- **APK bundle extraction never invokes a shell.** The editing and art-export CLIs share
  `server/cli/bundle_extract.py`, which validates the APK path and invokes `unzip` with literal
  argument-list semantics. A pathname containing shell metacharacters is therefore data, not code;
  missing APKs fail before extraction. Proof: `server/tests/test_bundle_extract.py`.

### Blacksmith and legacy Dominion recovery (2026-08-30)

- `/artifact/crafting`, `/artifact/merge`, and `/artifact/polish` must mutate the saved
  `ArtifactModel` rows; returning the correct response model with empty `results` only makes the
  Blacksmith UI appear to succeed. Crafting charges 25/50/100 dust for Normal/King/God, merging
  consumes three matching relics into the next tier within the XML `Root` family, and polishing
  consumes Artifact ids 901/902/903 using their `AddPolishPoint` before increasing one option level.
  `ensure_artifact_state()` seeds those three client-renderable polishing stones at 99,999 while
  keeping incompatible synthesis stones excluded. Proof: `python3 server/tests/test_artifact_blacksmith.py`.
- Tutorial #40 needs a server-side snapshot containing Chamber `10001` at `posIndex=1` and Inn
  `10101` at `posIndex=0`; it hides and reveals those rows locally. `_terr()` repairs an empty
  persisted plot to that snapshot. Proof: `python3 server/tests/test_territory.py`.

### Official v172.0.01 XAPK → AssetRipper Unity project (2026-08-30)

- The official source is `apk/com.awesomepiece.castle@172.0.01.xapk` (package
  `com.awesomepiece.castle`, SHA-256
  `c34c717620216121b11f031c5783c99afdc279c2c496810595f69d01f33a42ac`). Do not use the
  root `KingBugCastle_172.0.01.xapk`: its manifest identifies it as the private
  `com.nowl.castle` build.
- AssetRipper 1.3.3 needs an Android directory containing the official
  `assets/bin/Data` tree, matching `global-metadata.dat`, and a decoded
  `lib/arm64-v8a/libil2cpp.so`. For this release, take `base_assets.apk` and
  `config.arm64_v8a.apk` from the official XAPK, extract `assets/bin/Data/*` and
  `libunity.so`, then place the version-matched recovered
  `il2cpp/v172.0.01/libil2cpp_v17201_ssl.so` at that libil2cpp path. The three
  SSL return patches do not affect AssetRipper's static IL2CPP type recovery.
- The process opens more than the shell default 1024 descriptors. Run it with a
  process-local `ulimit -n 16384`:
  `AssetRipper.GUI.Free --cli --input <game-dir> --output <output-dir> --mode unity --script-content-level Level1`.
  With the installed binary at
  `/home/nowl/.local/share/rg-toolkit/tools/AssetRipper/AssetRipper.GUI.Free`, the
  initial output was `unity/king-god-castle-v172.0.01/ExportedProject/` (ignored
  as generated data): 694 MB, Unity `2022.3.62f3`, 26,650 asset files, 2,285 C#
  stubs, six scenes, 65 prefabs, and 30 shaders. It was incomplete: the prepared
  input omitted the Addressables bundles holding the hero content. Do not reuse it.
- Do not open this Level1-script export as a runnable/editable game project.
  On Unity `2022.3.62f3`, its generated stubs have three ambiguous
  `YieldAwaitable` references (`StoryModeBasePanel.cs:125,243` and
  `ChangeBGMVolumeNodeData.cs:67`), then the editor itself SIGSEGVs during
  `MonoScriptInfoScraper::ScanForSourceGeneratedMonoScriptInfo` on its initial
  assembly reload. The reliable viewer-oriented export is AssetRipper with
  `--disable-script-import` (or stubs preserved outside `Assets/` as text);
  keep Level1 stubs only for static inspection, not Unity compilation.
- For the already-exported `v172.0.01` viewer, move `Assets/Scripts` (and its
  `.meta`) to `AuxiliaryFiles/GeneratedScriptStubs`, and `Assets/Plugins` (and
  its `.meta`) to `AuxiliaryFiles/GeneratedGameAssemblies`, then delete only
  that project's `Library/`. The second move matters: AssetRipper copied 97
  game-runtime DLLs, including `Assembly-CSharp.dll` and `UnityEngine.*`; after
  scripts are removed Unity still SIGSEGVs at `MonoManager::ReloadAssembly` if
  it loads them as Editor plugins. Two clean batch launches completed with exit
  code 0 after both moves. AudioClip import emits FSBTool errors because the
  extracted files are not valid desktop WAV/OGG payloads; retain them as viewer
  data because the warnings are non-fatal.
- **Correct hero export (2026-08-30, shader fix 2026-08-31):** extract the original `base_assets.apk`'s
  `assets/aa/Android` bundles directly; the prior convenience copy under
  `apk/xapk_extracted_v17201/bundles/` contained a zero-byte
  `sprites_assets_all_*.bundle` and must not be trusted. A full 81-bundle input
  currently triggers AssetRipper 1.3.3's internal `atlas is not the same as
  mappedAtlas` exception. The working viewer input is the six original bundles
  `characters`, `prefabs`, `sprites`, `illusts`, `shaders`, and
  `*_unitybuiltinshaders_*`; it exports 79,801
  assets to `unity/king-god-castle-v172.0.01/ExportedProject-heroes/ExportedProject/`.
  The first four-bundle export was not visually valid: 414 of 458 materials,
  including the `Sprites-Default` material used by hero prefabs, referenced
  AssetRipper's fake `0000000deadbeef15deadf00d0000000` shader GUID and rendered
  white/magenta in Unity. Re-exporting all six resolves built-in material refs to
  `0000000000000000f000000000000000` and leaves zero material references to the
  fake GUID. Use `--disable-script-import`; Unity 2022.3.62f3 batch-imported the
  corrected project with exit 0.
  Hero assets retain their original hierarchy, especially `Assets/00_Unit/`:
  verification found 1,316 prefabs, 1,352 `Unit_*.png` textures, and 279
  illustrations. It has no imported C# stubs or DLL plugins.

### Workstation disk hygiene for Unity exports (2026-08-30)

- `/home` and the KGC worktree share `/dev/nvme0n1p3`; freeing `/tmp` or `/var`
  does not increase the space reported to Unity for this project. Prioritize
  user cache and ignored, reproducible KGC build directories. In this worktree,
  `.rebuild_v17201` and `.rebuild_local` are disposable output; keep `unity/`,
  `apk/`, `il2cpp/`, and the worktree data unless a task explicitly supersedes
  them.
- The high-impact user cache is `/home/nowl/.cache` (not source data). System
  package cache and journal cleanup require local sudo: `paccache -r -k 2`
  retains two package versions per package, and `journalctl --vacuum-size=500M`
  retains a 500 MB journal. Never use broad deletion against Android SDK,
  emulator data, Downloads, or locally installed model directories without an
  explicit replacement/retention decision.
- **Unity Hub exception:** it requires the writable directory
  `~/.cache/unityhub/tmp` during an Android NDK module post-install rename. If
  `.cache` has been cleared, recreate it with `mkdir -p ~/.cache/unityhub/tmp`
  before retrying; otherwise Hub reports "Android NDK Install failed" with
  `ENOENT` from `mkdtemp`, even after checksum validation and extraction passed.
### Dominion tutorial #40 native flow (2026-08-31)

Tutorial #40 must remain unfinished, but Dominion must already return Chamber `10001` at
`posIndex=1` (visual site 8) and Inn `10101` at `posIndex=0` (visual site 3). The client simulates
construction without calling `/territory/build`: `PrepareTutorial40` snapshots the territory list,
then predicate `b__68_0` removes roots `10000` and `10100` from the live client list. Step 5 calls
`Scene_Territory.GetBuildableArea(1)`; callback `b__68_6` restores the snapshot minus Inn, revealing
Chamber. Step 7 calls `GetBuildableArea(0)`; the later callback restores both rows, revealing Inn.
`b__68_8` calls `TerritoryBuildingListPanel.GetBuildingCell(10100)`, so an empty server snapshot
leaves Inn locked and throws `NullReferenceException` before any HTTP build request. The old seeded
layout had the right rows but reversed positions (`Chamber@0`, `Inn@1`), making each reveal jump to
the other tutorial site. Normal builds still require `refreshRet.buildingRet`; that response shape
is unrelated to the tutorial's local reveal flow. Regression: `server/tests/test_territory.py`.

### Blacksmith create / merge / polish contract (v172.0.01, 2026-08-31)

- `ArtifactCraftTab.<Craft>d__13.MoveNext` RVA `0x30B85FC` uses two craft slots. The request's
  `targetId` identifies a `ResourceArtifact.Type.Piece`; two matching pieces create the normal
  artifact named by the piece's inherited `<Root>`. With one slot empty, `useDust=true`: consume
  one piece plus `CraftDustCost[GetFromTypeRank(piece.fromType)]` (`25/50/100`). Piece rows must be
  present in `/artifact/inventory`'s `artifacts`; the old default inventory contained only the 184
  `Type=Artifact` rows, so the Craft tab had no selectable materials.
- `ArtifactMergeTab.ReloadActionButtonInteractable` RVA `0x30BA4D8` requires both merge slots.
  Consume two matching relics and create their next master-data tier. `GetMergeGoldCost`
  RVA `0x30BA2B8` resolves the output (`next`) resource first, then charges that tier's
  `MergeCost` row (King `400/600/800`, God `1000/1500/2000`, KingGod `4000/6000/8000`).
- `ResourceArtifact.GetFromTypeRank` RVA `0x340E2A8` table for enum values 0..9 is
  `[0,1,2,2,2,0,-1,-1,2,2]`: ShopCommon/Special=0, ShopRare=1,
  ShopSpecial/HardMode/Arena/Event/Raid=2; the two RogueLike families are invalid (`-1`).
- Polishing material request IDs are **resource IDs**, not artifact instance IDs:
  `MaterialArtifactItem.From` RVA `0x338EA10` copies `ArtifactModel.artifactId` into inherited
  `UpgradeMaterial.id` and the instance id into separate `uniqueId`. Stones 901/902/903 add
  10/50/100 points. `ArtifactPolishPointByRank` is transposed relative to the old server code:
  rows `One..Five` are the current option rank and columns are `FromType` rank. Moving an option
  position uses `/artifact/polish/replace-option-slot-idx`, costs
  `ArtifactPolishPointToReplace` (`200/400/800`), and must update both
  `data.options[i].targets` and `options.targets[i].idx`.
- Server implementation: `routes/artifact_routes.py`; durable focused regression:
  `python3 server/tests/test_artifact_blacksmith.py`.

### Guaranteed Forge contract (v172.0.01, 2026-08-31)

- `ArtifactRerollTab.<SmartRerollImpl>d__68.MoveNext` RVA `0x31018A0` sends
  `ArtifactRequestModel{targetId=<instance id>, index=<target position 1..6>,
  stat=<AtkPer|MAtkPer|AtkSpeedPer|HpPer>}` to `/artifact/smart-reroll`. A successful
  response must contain the updated artifact in `results[0]`; an empty result is a visible no-op.
  Generated fields identify `+0x110` as `_smartRerollTypeIndex` and `+0x114` as
  `_smartRerollTargetIndex`; `OnClickSmartRerollTarget` RVA `0x30C917C` stores the selected
  zero-based formation position there, and the request sends it plus one.
- `GetSmartRerollCost` RVA `0x30C9CB0` indexes `ResourceArtifact.fromType`: ShopCommon 1,
  ShopSpecial/HardMode/Arena 4, Event 0, Raid 2 Blacksmith's Tokens (inventory item 800).
  ShopRare, Special, and both RogueLike families return the client's invalid/max sentinel.
- Every active option row becomes the selected stat at level 6/value 24 and targets only the
  requested position. This matches `ReloadSmartRerollOptionUI` RVA `0x30C8A5C`, whose four-row
  preview loop builds each option with the selected type and `targetIndex + 1`. Update both
  `data.options` and parallel `options.{types,lvs,targets}`, then persist and deduct item 800. Regression:
  `server/tests/test_artifact_blacksmith.py`.

### Treasure 50002 / Cor Orbis (2026-09-02)

- `Strings_VI.xml` defines `TreasureName_50002` as `Cor Orbis`, with temporary subname and
  concept text about borrowing, storing, and releasing Mana from nearby plants and animals.
  It also defines skill/buff localization keys `3500020..3500025` and packages `1690..1692`.
- The current `xml_live/Treasures.xml` has no `<Treasure ID="50002">` row, and
  `TreasureBuffDatas.xml` has no `3500020..3500025` rows. Therefore owner, rarity, role,
  recommended unit, numeric values, and runtime implementation cannot be determined from the
  current master data.
- `StoryStages.xml` equips `50002` on story unit `10010210` (Story Mel) in stages
  `410101053` and `410101054`; this is only a scripted NPC loadout, not proof of Treasure
  ownership. Do not confuse it with `Items.xml` item `50002` (Mel's Injury).

## 20. Player Dashboard branding and locale (2026-09-03)

- The public Player Dashboard now supports Vietnamese and English through
  `webui-next/src/components/portal-i18n.tsx`. It defaults from the browser language, persists the
  explicit choice under `localStorage["kgc-player-locale"]`, synchronizes same-tab/cross-tab
  changes with `useSyncExternalStore`, and updates the document `lang`. `SiteShell` installs this
  provider only for the portal, so the administrator dashboard is unchanged.
- `PortalMasthead` is shared by `/player` and `/player/donate`. It is intentionally wordmark-only;
  the old `K / BC` mark and its attempted SVG replacement were removed at the user's request. The
  masthead owns the accessible `VI / EN` switch, and mobile moves its actions below the title.
- Portal copy, common API errors, fixed reward names/notes, request statuses and date formatting all
  follow the selected locale. Operator-authored `PLAYER_DONATE_INSTRUCTIONS` remains literal by
  design because it is deployment content, not application copy. Object-shaped FastAPI errors such
  as `{detail: {code: "insufficient_tickets"}}` are normalized by `player-api.ts` before lookup.
- Verification: `./node_modules/.bin/eslint .` passes; `./node_modules/.bin/next build --webpack`
  exports all 16 pages with TypeScript clean. Chromium headless checks at 1440x1000 and 390x844
  confirmed the login view and locale control render without horizontal overflow.

## 21. Rewarded-ad provider gate (2026-09-03)

- Keep `/portal/api/ticket/video/start` and `/complete` disabled. Google explicitly documents that
  Server-Side Verification is app-only and unavailable for GPT rewarded ads on web; its
  `rewardedSlotGranted` event therefore remains an untrusted browser assertion.
- AppLixir is the only direct web rewarded-video candidate verified against current vendor docs.
  Its v6.1 web callback carries signed `gameApiKey`, `gameId`, `userId`, and unique `tid`; production
  mode is `MD5 and TID`, so it can map an opaque portal session and deduplicate retries before
  calling the existing ticket-accounting helper. Do not trust or sign decisions from `customData`.
- AppLixir is not approved for this project yet. Its current public requirements conflict:
  the main site says 100,000 monthly impressions, while the publisher FAQ requires 5,000 daily ad
  impressions or active users; the signup form nevertheless accepts an `Under 100K` range. It also
  requires a publicly reviewable, original, non-infringing property, exact-domain registration,
  HTTPS, and `ads.txt`. Obtain written pre-approval for the actual portal, traffic, Vietnam-heavy
  audience, and content/IP situation before writing integration code or exposing either endpoint.
- Monetag's signed rewarded postback is documented only for Telegram Mini Apps, not an ordinary web
  portal. AdswedMedia and the surveyed BitLabs/CPX/Lootably/AdGate-style products are offerwalls
  (installs, surveys, registrations, tasks), not the requested one-click rewarded-video UX. Other
  gaming monetization vendors did not publish enough web S2S verification detail to satisfy the
  trust boundary. The smallest next step is AppLixir pre-qualification; if declined, retain
  donations/manual ticket credit rather than weakening the callback invariant.

## 22. Dimension Rift difficulty progression (v172.1.00, 2026-09-05)

- Theme 2100 has challenge levels `-5..16` in `RogueLikeSettings.xml`; level 16 is seasonal.
  `GameCompleteRequestModel` sends `rogueLikeChallengeLevel` @ `0x164` and the run's computed
  `rogueLikeBaseScore` @ `0x168`. There is no request field named `rogueLikeScore`.
- `DimensionRiftStartPanel.get__canChallenge` @ RVA `0x347A5C8` enables the challenge button when
  status `DimensionRiftPlayCount > 4` or `DimensionRiftMaxClearedChallenge >= 0` (defaults 0 and
  -1 respectively). `RogueLikeChallengePanel.Show` @ `0x347DED4` activates levels only through
  `maxCleared + 1`.
- `RogueLikeGameOverPanel.Show` @ `0x3660770` increments play count after every run. On a win it
  writes the selected challenge only when it exceeds the saved max. Its max lookup unusually uses
  default 0, while the selection panel uses -1; therefore the server must explicitly send max=-1
  for a fresh account or clearing level 0 cannot unlock level 1 locally.
- `GameResponseModel` has `rogueLikeScore` @ `0xCC` but no `updatedKeyValues`. The client updates
  its local key dictionary itself; the server mirrors both status keys into the save so `/player`
  restores them after relogin. Existing saves initialize play count from `rogueLikePlayedCount`.
- Server fix: `r_dimension_rift_complete` reads the two real request fields, clamps challenge to
  `-5..16`, requires the five-run gate and sequential `max+1` clear, keeps the best score for the
  leaderboard, and returns the current run score to the game-over panel. Assign the response score
  after `gameComplete.fixed`: that config contains `rogueLikeScore: 0` and otherwise overwrites it.
  Regression: `test_dimension_rift_difficulty_progresses_sequentially` in
  `server/tests/test_ranking.py`.
