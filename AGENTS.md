<!-- CODEGRAPH_START -->
## CodeGraph

This project has a CodeGraph MCP server (`codegraph_*` tools) configured. CodeGraph is a tree-sitter-parsed knowledge graph of every symbol, edge, and file. Reads are sub-millisecond and return structural information grep cannot.

### When to prefer codegraph over native search

Use codegraph for **structural** questions — what calls what, what would break, where is X defined, what is X's signature. Use native grep/read only for **literal text** queries (string contents, comments, log messages) or after you already have a specific file open.

| Question | Tool |
|---|---|
| "Where is X defined?" / "Find symbol named X" | `codegraph_search` |
| "What calls function Y?" | `codegraph_callers` |
| "What does Y call?" | `codegraph_callees` |
| "How does X reach/become Y? / trace the flow from X to Y" | `codegraph_trace` (one call = the whole path, incl. callback/React/JSX dynamic hops) |
| "What would break if I changed Z?" | `codegraph_impact` |
| "Show me Y's signature / source / docstring" | `codegraph_node` |
| "Give me focused context for a task/area" | `codegraph_context` |
| "See several related symbols' source at once" | `codegraph_explore` |
| "What files exist under path/" | `codegraph_files` |
| "Is the index healthy?" | `codegraph_status` |

### Rules of thumb

- **Answer directly — don't delegate exploration.** For "how does X work" / architecture questions, answer with 2-3 codegraph calls: `codegraph_context` first, then ONE `codegraph_explore` for the source of the symbols it surfaces. For a specific **flow** ("how does X reach Y") start with `codegraph_trace` from→to — one call returns the whole path with dynamic hops bridged — then ONE `codegraph_explore` for the bodies; don't rebuild the path with `codegraph_search` + `codegraph_callers`. Codegraph IS the pre-built index, so spawning a separate file-reading sub-task/agent — or running a grep + read loop — repeats work codegraph already did and costs more for the same answer.
- **Trust codegraph results.** They come from a full AST parse. Do NOT re-verify them with grep — that's slower, less accurate, and wastes context.
- **Don't grep first** when looking up a symbol by name. `codegraph_search` is faster and returns kind + location + signature in one call.
- **Don't chain `codegraph_search` + `codegraph_node`** when you just want context — `codegraph_context` is one call.
- **Don't loop `codegraph_node` over many symbols** — one `codegraph_explore` call returns several symbols' source grouped in a single capped call, while each separate node/Read call re-reads the whole context and costs far more.
- **Index lag**: the file watcher debounces ~500ms behind writes; don't re-query immediately after editing a file in the same turn.

### If `.codegraph/` doesn't exist

The MCP server returns "not initialized." Ask the user: *"I notice this project doesn't have CodeGraph initialized. Want me to run `codegraph init -i` to build the index?"*
<!-- CODEGRAPH_END -->

## Project Context

> **Operator playbooks** (grant items/skins/treasures, un-gate `MinVersion` content, build a
> training-dummy stage, edit master data + push the CDN xml bundle, AES crypto): see **`docs/`**
> at the repo root (`docs/README.md`). This file stays focused on binary patches, RVAs, and
> il2cpp internals.

> **Task workflow (user-mandated 2026-08-18)**: before ANY task, check **`docs/dev-notes.md`**
> first — the personal RE knowledge base (task → known decode → exact RVA/offset → verification
> method → open questions). Follow it if covered; if not, do the work then update it; if it's
> wrong, investigate first and only update once certain.

### Goal
Private server emulator for King God Castle (arm64). Game uses a FastAPI server on port 8080 (HTTP) + a second uvicorn on port 8443 (TLS, `--ssl-keyfile key.pem --ssl-certfile cert.pem`; the old standalone `tls_proxy.py` is gone). Device connects via `adb reverse tcp:80 tcp:8080; adb reverse tcp:443 tcp:8443`. Hosts file on device redirects the API domains → 127.0.0.1.

### Critical Finding: PvPInfoResponseModel.GetCurrentSeasonUntilAt()
- RVA: **0x2CC27FC** (NOT 0x2CC288C which is GetNextSeasonStartAt)
- ARM64 code: `seasonUntilAtDates[semiSeason - 1]` — subtracts 1 from index!
- `semiSeason=0` → index -1 → IndexOutOfRange
- Fix: set `semiSeason=1` in response (`/pvp/info`, `/player`, `/pvp/matching`)

### Method Mapping (PvPInfoResponseModel v170.0.03_arm64)
| Method | RVA | Index calculation | Array |
|---|---|---|---|
| GetCurrentSeasonUntilAt | 0x2CC27FC | `semiSeason - 1` | `seasonUntilAtDates` |
| GetNextSeasonStartAt | 0x2CC288C | `semiSeason` (via +1-1 stub) | `nextSeasonStartAtDates` |
| GetSeasonStartAt | 0x2CC2898 | takes `semiSeason` param | `nextSeasonStartAtDates` |
| GetSeasonUntilAt | 0x2CC293C | takes `semiSeason` param, then -1 | `seasonUntilAtDates` |
| get_dormantScoreDecreaseAt_ | 0x2CC29CC | N/A | `dormantScoreDecreaseAt` |

### PlayerColosseumInfoResponseModel.GetCurrentSeasonUntilAt()
- RVA: 0x2CC5E7C
- ARM64 code: `seasonUntilAtDates[semiSeason - 1]` — same pattern!
- Fix: set `semiSeason >= 2` with array of 2+ elements

### SSL Bypass Patches (arm64 libil2cpp.so, v170.1.00)
Three patches at addresses (in APK libil2cpp.so):
- 0x2CB2248
- 0x5966A04
- 0x5965114

(v170.0.03 offsets were 0x2CB6594 / 0x596E418 / 0x596CB28 — shifted on the version bump, see ARM64 Patch Inventory below for derivation method.)

XIGNCODE stub replaces real libxigncode.so. It is no longer a bare no-op: `server/jni/stub.cpp`
compiles to a native il2cpp poller + UI hooks (~730KB, padded back to the original 510KB so the
patch-set size check passes). It still registers no-op JNI `ZCWAVE_*` methods (boots past the
anti-cheat), then a worker thread dlopen's `libil2cpp.so` and installs hooks (GameUnit stat poller
on `BattleManager.Update`; custom-mail hook on `PostListItem.Set`). See "il2cpp hook techniques" below.

### Google login web-bridge + Cloudflare
The stub hooks `Scene_Login.OnClickGoogleLogin` to open a browser to `/glogin` (domain from
`g_kgc_glogin_host`, scheme from `g_kgc_glogin_scheme`). After OAuth callback, a native poller
thread hits `GET /glogin/pending` every ~1s to retrieve the account ID, then calls
`Scene_Login.Auth(accountId)` to complete login.

**Cloudflare**: the public domain (`kingbugcastle.id.vn`) goes through Cloudflare, which proxies
**all** ports (80, 443, 8080, 8443) and redirects HTTP → HTTPS. The raw-socket native poller
cannot follow HTTPS redirects. Fix: `g_kgc_glogin_poll_host` is patched to the **origin IP**
(`213.35.110.245`) to bypass Cloudflare entirely. Browser still uses the domain (supports HTTPS).
Build script: `GLOGIN_POLL_HOST=<ip>` env var (defaults to `SHARE_HOST`; must override for public).

**NDK**: build with cmake (see SETUP.md), NOT ndk-build. NDK 28 has C++ linking issues
(`__libcpp_verbose_abort` undefined). NDK 27 (`ndk;27.2.12479018`) works.

### Route Model Gap
Many endpoints lack routes in `routes.txt`. The `route_models.json` heuristic maps paths to models by name similarity. Unknown paths return empty `ResponseModel`. To handle missing models, add OVERRIDES in `server.py` which bypass `build_model` and return raw dict. The direct FastAPI handler (`@app.get/post`) takes priority if registered BEFORE the `for _r in ROUTE_MODELS` loop.

### ARM64 Patch Inventory (14 active in rebuild_arm64.py, v170.1.00 offsets)
All patches apply to `config.arm64_v8a.apk` → `lib/arm64-v8a/libil2cpp.so`. Offsets below are **v170.1.00** — re-derived 2026-07-05 via a fresh Il2CppDumper run against this version's own arm64 binary (previous rows were v170.0.03; bumping versions shifts every offset even though the underlying prologue bytes stayed byte-identical). Method: dump.cs's `Offset` field (`= RVA - 0x4000`) matches `patch_apk()`'s raw file-offset convention 1:1 (verified against the known-working v170.0.03 SSL offsets before trusting it for the rest).

| # | Offset | Label | Original bytes | Patch | Purpose |
|---|---|---|---|---|---|
| 1 | 0x2CB2248 | ssl | `fe5fbda9f65701a9` | `20008052c0035fd6` | SSL bypass: `PinnedCertHandler.ValidateCertificate` → true |
| 2 | 0x5966A04 | ssl | `ff0302d1fd7b02a9` | `20008052c0035fd6` | SSL bypass: `UnityTlsProvider.ValidateCertificate` → true |
| 3 | 0x5965114 | ssl | `fe0f1ff8e80300aa` | `20008052c0035fd6` | SSL bypass: `MobileTlsContext.ValidateCertificate` → true |
| 4 | 0x304CDF0 | kgmarble | `fe0f1ef8f44f01a9` | `e0031f2ac0035fd6` | `GameManager.IsKGMarbleAvailable()` → false |
| 5 | 0x32B5DF8 | shop-growth | `fe0f1af8fc6f01a9` | `e0031f2ac0035fd6` | `PackageItem.InitCustomGrowthPackage()` early return |
| 6 | 0x32B7EC8 | shop-season | `ff4301d1fe6701a9` | `e0031f2ac0035fd6` | `PackageItem.InitSeasonPassPackage()` early return |
| 7 | 0x3245178 | pvp-reward | `fe0f1bf8fa6701a9` | `e0031f2ac0035fd6` | `PvPPanel.GetReceivableWinRewardCount()` → 0 |
| 8 | 0x304AC0C | year-event | `fe0f1ef8f44f01a9` | `e0031f2ac0035fd6` | `GameManager.IsYearEventAvailable()` → false |
| 9 | 0x30321DC | babel-data | `fe0f1df8f65701a9` | `e0031f2ac0035fd6` | `GameManager.GetBabelData()` → null (caller checks) |
| 10 | 0x349BAB4 | content-alert | `fe0f1bf8fa6701a9` | `e0031f2ac0035fd6` | `WorldPanel.ReloadNewContentAlert()` early return |
| 11 | 0x304CCEC | card-event | `fe0f1ef8f44f01a9` | `e0031f2ac0035fd6` | `GameManager.IsEventCardCollectingAvailable()` → false |
| 12 | 0x304CBE4 | season-event | `fe0f1ef8f44f01a9` | `e0031f2ac0035fd6` | `GameManager.IsSpecialSeasonalEventOpened()` → false |
| 13 | 0x324A4FC | pvp-init | `ff8303d1fd7b08a9` | `e0031f2ac0035fd6` | `PvPPanel.<Init>d__77.MoveNext()` early return |
| 14 | 0x3059C88 | accessory | `af8cec97e103002a` | `20008052c0035fd6` | `GameManager.IsAccessoryUnlocked()` → true |

**Inactive / not re-derived** (still commented out in `rebuild_arm64.py`, offsets below are stale v170.0.03 — don't trust them if re-enabling, re-derive first):
| Label | v170.0.03 offset | Purpose | Why inactive |
|---|---|---|---|
| deck-reload | 0x3198970 | `DeckPanel.ReloadDeck()` early return | disabled 2026-07-02 for a root-cause investigation, never re-enabled |
| deck-reload2 | 0x3197894 | `DeckPanel.Reload()` early return | same |

**Patch pattern**: `RET_FALSE` = `e0031f2ac0035fd6` = `mov x0,#0; ret`. SSL uses `RET_TRUE` = `20008052c0035fd6` = `mov w0,#1; ret`.

### ARM64 Patch Inventory — private build (`server/builders/build_private.py`)

v171+ ships **no on-disk `libil2cpp.so`** (XIGNCODE NEO packs + encrypts it inside the packer `.so`).
The build recovers one and injects it, then NOPs the NEO unpack path — see
[docs/mftl-extraction.md](docs/mftl-extraction.md) for the unpack recipe and
[docs/private-build.md](docs/private-build.md) for the operator playbook.

**Default input is v172.0.00** (`KGC_APK_SRC=xapk_extracted_v1720`), and it injects that build's
**own** game code: `il2cpp/v172.0.00/libil2cpp_v172_ssl.so`, unpacked out of its packer by
`patchers/unpack_neo.py`. Lib and metadata come from the same build, so **no metadata swap runs**.
The v172 packer (`libbeniolle.so`) is the **same loader binary** as v171.0.01/v171.1.00 — all 8
`NEO_SIG_SITES` byte-identical and the `08008012 e89700b9` pattern hits the same 4 offsets; only
the filename rotated.

*Fallback* (`KGC_APK_SRC=xapk_extracted_v1711` → v171.1.00 native, or `KGC_FORCE_V17100=1` for any
older source) injects that build's own lib; only the v171.0.00 fallback **must** swap v171.0.00's
`global-metadata.dat` into `base_assets.apk` (`patchers/patch_metadata_swap.py`, before
`patch_hosts` / `patch_metadata_http`). That is mandatory, not cosmetic: v171.0.01 **inserted** the
literal `/auth/xcdSeed?version=` at stringLiteral index 1545 of 25730, shifting 94% of all literal
indices, and libil2cpp compiles those indices in.

**Every il2cpp offset is per-lib.** The tables live side by side in `build_private.py`
(`_NRE_STUBS_V17100` / `_NRE_STUBS_V17110` / `_NRE_STUBS_V17200` / `_NRE_STUBS_V17201`) and are picked by `VER`
(**RVA** convention: file offset = `RVA - 0x4000`). They were re-derived from each version's own
`dump.cs` by exact class + signature match; all 10 stub prologues came back byte-identical across
the three, which is the cross-check that the re-derivation landed on the same methods.
`ShopItem.Init` does NOT match by bytes (immediates changed) — it is matched by instruction shape,
with the replacement's `cbz` displacement recomputed against the new bail-out target.

**NEO loader offsets do not shift by a constant between builds** (`libaledatic.so` maps `file == VMA`,
`librolineng.so` maps `VMA == file - 0x4000`, and the loader function grew):

| purpose | v171.0.00 `libaledatic.so` | v171.0.01 `librolineng.so` / v171.1.00 `libxenerene.so` |
|---|---|---|
| integrity bail-outs (`bl` ; `tbnz w0,#31,<fail>`, last is `cbz x0`) | `3d2b8 3d2c0 3d2c8 3d2f8 3d484 3d4c8 3d4e4 3d4f4` | `437b0 437b8 437c0 437f0 43c28 43c6c 43c88 43c98` |
| parser error returns (`mov w8,#-1` ; `str w8,[sp,#0x94]` ; `b`) | `e5728 e57d0 e57e8 e5870` | `12bd0c 12bdb4 12bdcc 12be54` |

v171.0.01 and v171.1.00 share a column because the packer is the **same binary**: 4 bytes differ
across 3.3 MB of code and all 12 patch sites sit at identical file offsets.

The second group is located by **pattern** (`08008012 e89700b9`, exactly 4 hits in both libs); the
first is a table that now **raises** on a byte mismatch instead of skipping quietly. The loader itself
is found by `SONAME = libappsign4a.so`, never by filename — the filename rotates per build.

**`libil2cpp_v171_ssl.so` must be pristine + the 3 SSL patches only.** It rotted over several sessions
(2026-07-19): 21 stray bytes, including a `b 0x3503ba8` that had overwritten `mov w8,#-2` inside
`Scene_Login.<CheckUseAssetBundle>d__79.MoveNext` @ RVA `0x3503b7c`. That stray branch jumped back
into the state-1 await setup = infinite UniTask recursion = stack-overflow SIGSEGV on "Loading
resources", which was misdiagnosed for two sessions as an inherent IL2CPP UniTask bug. Regenerate as
plain `libil2cpp_v171.so` + only these three — `server/patchers/make_v171_ssl_so.py` does exactly that,
and `--check` validates the existing file (both SSL patches present, two known-rot anchors intact,
**zero** stray bytes vs pristine). Never hand-patch this file in place:

| Raw file offset | Method | Patch |
|---|---|---|
| 0x2CB68D8 | `PinnedCertHandler.ValidateCertificate` | `20008052c0035fd6` (RET_TRUE) |
| 0x596EF64 | `UnityTlsProvider.ValidateCertificate` | same |
| 0x596D674 | `MobileTlsContext.ValidateCertificate` | same |

> **Two offset conventions coexist — do not mix them.** The 3 SSL rows above are **raw file offsets**.
> Everything else below comes from `il2cpp/v171.0.00/script.json` `ScriptMethod[].Address`, which is an
> **RVA**; file offset = `RVA - 0x4000`. Tombstone `pc` values are RVAs too, so resolve crash frames via
> `script.json`, never by parsing `dump.cs` offsets.

Patches the build applies on top (all idempotent, each guarded by an expected-prologue check that
`raise SystemExit`s on a mismatch rather than corrupting the binary):

| RVA | File offset | Label | Original bytes | Patch | Purpose |
|---|---|---|---|---|---|
| — | 0x303C6C0 | firebase | `fe0f1bf8` | `c0035fd6` | `GameManager.CheckFirebase()` → `ret`. FCM init is fatal in the v171 login coroutine and needs Play Services; unused on a private server |
| 0x325658C | 0x325258C | pvp-init | `ff8303d1fd7b08a9` | `e0031f2ac0035fd6` | `PvPPanel.<Init>d__77.MoveNext()` early return |
| 0x3251208 | 0x324D208 | pvp-reward | `fe0f1bf8fa6701a9` | `e0031f2ac0035fd6` | `PvPPanel.GetReceivableWinRewardCount()` → 0 |
| 0x32C1EA8 | 0x32BDEA8 | shop-growth | `fe0f1af8fc6f01a9` | `e0031f2ac0035fd6` | `PackageItem.InitCustomGrowthPackage()` early return |
| 0x32C3F78 | 0x32BFF78 | shop-season | `ff4301d1fe6701a9` | `e0031f2ac0035fd6` | `PackageItem.InitSeasonPassPackage()` early return |
| 0x3055F58 | 0x3051F58 | year-event | `fe0f1ef8f44f01a9` | `e0031f2ac0035fd6` | `GameManager.IsYearEventAvailable()` → false |
| 0x3058038 | 0x3054038 | card-event | `fe0f1ef8f44f01a9` | `e0031f2ac0035fd6` | `GameManager.IsEventCardCollectingAvailable()` → false |
| 0x3057F30 | 0x3053F30 | season-event | `fe0f1ef8f44f01a9` | `e0031f2ac0035fd6` | `GameManager.IsSpecialSeasonalEventOpened()` → false |
| 0x303D528 | 0x3039528 | babel-data | `fe0f1df8f65701a9` | `e0031f2ac0035fd6` | `GameManager.GetBabelData()` → null (caller null-checks) |
| 0x34A7B2C | 0x34A3B2C | content-alert | `fe0f1bf8fa6701a9` | `e0031f2ac0035fd6` | `WorldPanel.ReloadNewContentAlert()` early return |
| 0x3062DF0 | 0x305EDF0 | accessory | `fe0f1ff8088c40f9` | `20008052c0035fd6` | `GameManager.IsAccessoryUnlocked()` → true |
| 0x32DB7F0 | 0x32D77F0 | shop-init | `08aa01f0...` (28 bytes) | `881a40b968120034...` (28 bytes) | `ShopItem.Init()` empty list crash bypass. Checks `Count == 0` and skips `get_Item(0)` to prevent SIGSEGV/IndexOutOfRange |

The NRE stubs are a straight port of the v170 set (rows 5-14 of the v170 table above) — every prologue
came back **byte-identical**, only the offsets moved, which is what confirms the `script.json` mapping.
v170's `WorldPanel.IsKGMarbleAvailable` has **no v171 counterpart** and was dropped.

**v172.0.00 offsets** (same patches, re-derived 2026-08-13 from v172.0.00 `dump.cs`; RVAs, file =
RVA − 0x4000; `NRE_STUBS` table rows are RVAs — the build loop subtracts 0x4000):

| RVA | Label | Original bytes (all verified byte-identical to v171.1.00) |
|---|---|---|
| 0x325E0CC | pvp-init | `ff8303d1fd7b08a9` |
| 0x3258D48 | pvp-reward | `fe0f1bf8fa6701a9` |
| 0x32C9A04 | shop-growth | `fe0f1af8fc6f01a9` |
| 0x32CBAD4 | shop-season | `ff4301d1fe6701a9` |
| 0x305BCB4 | year-event | `fe0f1ef8f44f01a9` |
| 0x305DD94 | card-event | `fe0f1ef8f44f01a9` |
| 0x305DC8C | season-event | `fe0f1ef8f44f01a9` |
| 0x3043284 | babel-data | `fe0f1df8f65701a9` |
| 0x34B0374 | content-alert | `fe0f1bf8fa6701a9` |
| 0x3068B4C | accessory | `fe0f1ff8088c40f9` (RET_TRUE) |
| 0x304641C | firebase (file 0x304241C) | `fe0f1bf8` → `c0035fd6` |
| 0x34E38A8 | RegisterHackDetection (file 0x34DF8A8) | `fe57bea9` → `c0035fd6` |
| 0x32DB348 | shop-init (**file offset**, see below) | `941300b428aa01d0086545f9f60300aae00314aae1031f2a020140f92bb03394` |

**v172.0.01-only patches** (added 2026-08-14):

| File offset | Label | Original bytes | Patch | Purpose |
|---|---|---|---|---|
| 0x3776158 | firebase-logevent-1 | `fe0f1df8f65701a9` | `c0035fd6` (ret) | `FirebaseAnalytics.LogEvent(string, Parameter[])` → ret |
| 0x37761BC | firebase-logevent-2 | `fe67bca9f85f01a9` | `c0035fd6` (ret) | `FirebaseAnalytics.LogEvent(string, IEnumerable<Parameter>)` → ret |
| 0x370cee8 | canUseFirebase-gate | `c8010034` (cbz) | `1f2003d5` (nop) | NOP the canUseFirebase gate so ranking dispatches fire |
| 0x2CBB2C4 | ranking-endpt | `fe0f1ef8f44f01a9` (RVA 0x2CBF2C4) | `48da01f0086545f9080140f9085d40f9000540f9c0035fd6` | `Web.GetRankingServerEndPoint()` → return `Web._endPoint` directly (`http://127.0.0.1`), preventing external cloud-run calls |
| 0x34E0EDC | RegisterHackDetection | `fe57bea9` (RVA 0x34E4EDC) | `c0035fd6` (ret) | `Scene_Base.RegisterHackDetectionCallback` → ret |

### v172.0.01 Weekly Combat Power Ranking & Leaderboard Architecture (2026-08-14)

1. **Endpoint Resolution**:
   `Awesomepiece.Web.GetRankingServerEndPoint()` originally attempted to resolve Firebase-based endpoints or loaded `Web.rankingServerEndPoint` pointing to `https://castle-infra-server-...` (which failed/bypassed on local private server). Patched at RVA `0x2CBF2C4` to load `Web._endPoint` directly (`adrp x8, #0x680a000; ldr x8, [x8, #0xac8]; ldr x8, [x8]; ldr x8, [x8, #0xb8]; ldr x0, [x8, #8]; ret`).

2. **Server Routing Gap (`server.py` OVERRIDES)**:
   Added `/ranking/ranking`, `/ranking/pvp-ranking`, `/ranking/colosseum-ranking`, `/ranking/challenge-mode-ranking`, `/clan/ranking`, etc. into `OVERRIDES` pointing to `roster.r_ranking`. Returning empty fallback model causes `RankingPanel.<ShowRanking>d__14.MoveNext` to throw `NullReferenceException` on `myRankingItem.Set(model.playerRank, true)`.

3. **Leaderboard Roster Safety (`roster.py`)**:
   - `deck_units`: Guarantees `deck` array is strictly 6 elements (padded with starter unit IDs `[10000, 10010, 10020, 10030, 10040, 10050]`) so `RankingItem.Set` does not pass null sprites to Unity UI.
   - `rank_row`: Fallbacks for empty/null player and castle names to ensure strings are never null.
   - `playerRank`: Always returns a populated `RankingData` dict for the calling player.

4. **Score submission = `eliteRankingScore` inside `/game/complete` (fixed 2026-08-18, commit a3725ca)**:
   The ranking-stage battle ("Measure Combat Power") reports its score as
   `GameCompleteRequestModel.eliteRankingScore` (field offset 0xC8, a `long`) embedded in the
   normal complete request — there is **no separate score POST**. `RestAPI.AddRanking`
   (v171 coroutine `<AddRanking>d__382.MoveNext` @ 0x2c5d070, wrapper 0x2c56f5c) is called ONLY
   from `SettingsPanel.<OnClickTestRanking>d__86.MoveNext` (0x326f330) — a debug button — and
   `GameOverPanel.Show` (0x35d6f58) only *displays* `get_finalRankingScore`; neither submits the
   weekly score. The submit path is: `Scene_Game.UpdateImpl` computes `GetRankingScore`
   (0x2d70230) → stored → complete request carries it. The handler used to drop it, and
   `r_ranking` scored `bestClearedTheme*100+bestClearedStage` instead, so the combat-power
   board never moved after a battle. Now: `r_game_complete` stores the best value in
   `st["eliteRankingScore"]`; `r_ranking` prefers it, falling back to the old formula for
   accounts that never played a ranking stage. Test: `check_elite_score_flows_through_game_complete`
   in `server/tests/test_ranking.py`. Note: no `ranking*` string literals exist in either v171/v172
   `.so` — API paths are static string fields populated from server data, so path hunting via
   string search is a dead end; the TLS log (`/tmp/kgc_pub_tls.log`) is the source of truth for
   what the client actually calls.

### v172.0.01 "Loading resources…" hang — FirebaseAnalytics.LogEvent in Web.Get (2026-08-14)

v172.0.01 **embeds** `FirebaseAnalytics.LogEvent()` inside `Awesomepiece.Web.Get[T]` — the game's
HTTP client class. Stack trace:
```
Awesomepiece.Web.Get[T]
  → FirebaseAnalytics.LogEvent(string, IEnumerable<Parameter>)
    → FirebaseAnalyticsInternal..cctor
      → FirebaseApp.CreateAndTrack
        → InitializationException: messaging (missing dependency)
          → TypeInitializationException (rethrown)
```
On redroid (no Google Play Services), the Firebase static cctor throws
`TypeInitializationException`, which **kills the HTTP callback mid-flight**. The game fetches
`usePatch` and the response arrives, but the completion handler crashes before it can proceed to
`getPatchFolder`. Symptom: game sits on "Loading resources…" forever, server log shows only
`usePatch` and nothing else.

`CheckFirebase()` (already stubbed to `ret`) only prevents `GameManager` from calling Firebase
init — it does NOT prevent `Web.Get` from calling `LogEvent` directly. The fix is stubbing both
`FirebaseAnalytics.LogEvent` overloads to `ret` (void methods). With the patch, the full flow
resumes: `usePatch` → `getPatchFolder` → CDN assets → login screen.


`ShopItem.Init` v172: site **file 0x32DB348** (ORIG found by byte search, NOT RVA−0x4000 — the
0x32DB748 figure from the first pass was wrong). NEW `b41200b4881a40b968120034f60300aae00314aae1031f2a1f2003d52bb03394`
disassembles to `cbz x20,#0x32db59c; ldr w8,[x20,#0x18]; cbz w8,#0x32db59c; mov x22,x0; mov x0,x20;
mov w1,wzr; nop; bl #0x3fc7410` — both null and empty-list cases jump to the method's own epilogue at
file 0x32db59c (`ldp x20,x19,[sp,#0x60]...ret`), same shape as v171.1.00's fix (only the final `bl`
target differs). The v171.1.00 `bl` word `66983394` vs v172 `2bb03394` is the per-version piece.

### The `ldr → mov` klass patches CAUSE the black lobby — keep them OFF (disproven 2026-07-28)

`LDR_PATCHES` in `build_private.py` (65 sites, grown from an original 18) rewrites every
`ldr x0, [xR]` in `Scene_Lobby.Init` to `mov x0, xR`. **It is off by default and must stay off.**
`KGC_APPLY_LDR=1` re-enables it for an A/B.

The theory it was built on — "under ndk_translation the TypeInfo klass self-pointer fixup
(`0x2001ba1f` → self-pointer) never runs, so `ldr x0,[x23]` yields a bogus address" — is **wrong**.
`x23` holds the **GOT slot**, and the `ldr` is what loads `Il2CppClass*` out of it. Rewriting it to
`mov` leaves x0 pointing at the slot itself, so everything downstream reads garbage:

```
ldr x0, [x23]          // x23 = GameManager's Il2CppClass** GOT slot  <- patched to `mov x0,x23`
ldr x8, [x0, #0xb8]    // klass->static_fields      -> reads slot+0xb8 = garbage
ldr x0, [x8]           // static field 0 = GameManager._singleton -> null
cbz x0, <throw NRE>    // <- the NRE that blanks the lobby
bl  GameManager.Init
```

**Proof** (and the reusable technique): `KGC_LOBBY_DIAG=1` NOPs every null-check branch in
`Scene_Lobby.Init`, so the first null OBJECT falls through to its own dereference and SIGSEGVs with a
locatable fault PC instead of a location-stripped managed NRE. Tombstone:

```
#00 0x03040134  GameManager$$Init      +0x98   ldrb w8,[x19,#0x1b0]   x19 == 0   <- SIGSEGV
#01 0x034E5624  Scene_Lobby$$Init      +0x270  bl GameManager.Init
#02 0x034E368C  Scene_Lobby$$Awake     +0x6E0
#03 HookedLobbyAwake+372  (libxigncode.so)
```

At that same instant the stub's own `GameManager.Get()` returned a **valid** singleton
(`HookedLobbyAwake: GameManager.Get() = 0x7f2e14599540`) — the singleton was never the problem, only
the patched read path was. With `_apply_ldr` off the lobby renders and `HookedLobbyAwake EXIT` logs
cleanly.

Backtrace `pc` values are RVAs; resolve them against `il2cpp/v171.0.00/script.json`
(`ScriptMethod[].Address` is decimal and is the same RVA space; file offset = `RVA - 0x4000`).

The `HookedLobbyAwake` singleton guard in `jni/stub.cpp` (force `GameManager..cctor` if `Get()` is
null) is harmless and stays — it simply never has to do anything.

**Do NOT enable `KGC_ASSETBYPASS`.** That opt-in patch rewrites the `Scene_Login.CheckUseAssetBundle`
kickoff to tail-call `LoadAfterAssetBundle(this, true)`. It was built to dodge the recursion above,
which turned out to be the corrupt-`.so` artifact — and it actively breaks the client: skipping
`usePatch`/`getPatchFolder` means the CDN `xml` bundle (Strings + fonts) never downloads, so every
label in the game renders as garbled/mirrored glyphs. Kept only as a debug escape hatch.

**Host rebinding needs two passes.** `patch_hosts.py` walks only the il2cpp **stringLiteral table**;
two backend URLs live as **field/parameter default values** and are unreachable to it
(`https://castle-infra-server-…run.app`, `https://kgc-cdn-1.awesomepiece.com/patch/`). Left unpatched,
the client silently talks to the real backend. `server/patchers/patch_leftover_hosts.py` does a raw
same-length rebind (path preserved, null-padded so no offset shifts, CRC fixed) and runs right after
`patch_metadata_http.py`. Verify with a metadata scan that **0** real hosts remain.

### Daily-reset boundary — `tomorrow` must be derived, never stored

`Scene_Lobby.Update` (RVA `0x34EA5F0`+) runs, once per second-tick:

```
now = DateTime.UtcNow
if (now >= playerData.tomorrow_)      // DateTime.op_GreaterThanOrEqual @ 0x5745244
    FetchNextDay(...)                 // Scene_Base.FetchNextDay @ 0x34DBEA8
```

`Scene_Base.<FetchNextDay>d__41.MoveNext` calls `RestAPI.Login` (@ `0x2C46FB4`) and re-runs the entire
lobby fetch chain. So a `tomorrow` in the past makes the client **re-login at 1 Hz forever** — 17
requests/second, lobby still rendering and interactive, nothing in logcat (it is normal control flow,
not an exception). `Scene_Territory.Update` has the same call.

`server.py` used to serve `st.get("tomorrow", …)` from the player save, where it was frozen at
account-creation time — so every account entered the loop the day after signup. Now derived via
`next_reset_iso()` (next UTC midnight, and `+7d` for `nextWeek`). Regression test:
`server/tests/test_daily_reset.py`. `PlayerDataResponseModel.tomorrow` is at field offset `0xD0`.

**Method for finding this class of bug**: a fixed-period request loop with no exception is a client
timer, not a retry. Resolve the endpoint's C# entry point, then raw-scan the `.so` for `BL`
instructions targeting its RVA to get callers (`(w>>26)==0x25`, sign-extend `imm26`, `target =
site + imm*4`; file offset = `RVA - 0x4000`). That is how `Scene_Lobby.Update` was found from
`POST /auth/login` in two hops.

### Auth: id-less logins are refused; the template uid is never a save key (2026-08-18, de175b6)

Two fixes from the "player p-0c10a24bc780 lost all data" report (it did not — see below):

1. **`_uid_for_login` fell back to `playerdb.active()` when `login_id` was empty**, so any
   `/auth/login` with no id and no token was handed the active save (dev-0001) *with a
   session bound to it*. The constant `dev-0001` sessions in the DB (every ~5-20 min) were
   that path firing — almost certainly a client that lost its guest id (cache clear /
   reinstall) logging in over and over. Now the fallback is single-player-only;
   multiplayer returns `None` → login refused (`success: False`, no session, no save).
   `mint_session_token` guards `None` the same way. Live-verified: after deploy, an
   empty-id probe creates no session and dev-0001 spam stopped.
   Two further `st.get("uid", "dev-0001")` sites were converted to `st.get("uid") or
   "dev-0001"` the same day (commit f53f38b's follow-up, 2026-08-18): `r_player`'s `uid`
   echo (an empty template uid would have been emitted to the client) and the legacy
   `player.json` migration in `playerdb.py` (could have persisted a `""`-keyed row).
2. **`default_player.json` carried `"uid": "guest-0001"`** and some paths used it as the
   save key (`save_state`/`load_state` single-player boot, `admin /player/reset`), which
   minted a phantom `guest-0001` row (the "NewPlayer" save created 2026-08-07 — harmless:
   no accounts row, never a session, don't delete without asking). Template uid is now
   `""` and every key fallback is `st.get("uid") or "dev-0001"` so it can never persist.

**Incident facts (verified, DB + backup diff, 2026-08-18)**: the player's save
`p-0c10a24bc780` (login `guest-501689756-756593919`, name "Player5893", level 100, 73 cards,
6.19M gold) was **never touched by the altar fix** — only normal gameplay + the
`buildingPoints`→`buildingPoint` key migration. Same 37 uids before/after the scan; binding
intact; no session since Aug 16. "Became guest-0001" was a dashboard artifact + the
empty-id bug above. If a client presents a *new* guest id, a fresh `p-<hash>` save is minted
and the old one can be re-attached (`playerdb.bind_login(old_id, new_uid)` or copy the JSON).
Full write-up: `docs/multi-account-login.md` ("If a player's client lost its guest id").
**`dev-0001` IS NightOwL since 2026-08-18**: the user's account (uid `p-410890b421a5`,
Google `google_102274623045401309225`) was merged onto `dev-0001` and the old KingBug
`dev-0001` save deleted (`server/state/backups/players.db.bak-uidmerge-*` holds the pre-merge
DB). NightOwL's 14 sessions + 174 items + 74 cards carried over; its 600+ KingBug-era
sessions were dropped with the old save.

### Google sign-in: `GET /auth` must mint a token (2026-08-18, 22fe85f)

The client's native Google sign-in is `GET /auth?id=<account>&cookie=...&platform=Android`
(the real backend's `RestAPI.Auth`), and it expects a full AuthResponseModel carrying
`accessToken` back. route_models answered an **empty model** (no OVERRIDE), so a client
with no stored token — fresh install, or after Android "Clear data" — never received one:
its `/auth/login` went out id-less, `r_login` refused it (multiplayer, de175b6), and every
following request hit `load_state()`'s throwaway **template save** ("KingBug"/"BugCastle",
290909 gold, uid echoing dev-0001) — the "my account became KingBug after clearing
storage" report. It worked before only because the device held a token stored by an
earlier web-bridge login. Fix: `direct_routes.py` handles `GET /auth` (+`/auth/auth`
alias) by calling `mint_session_token(id)` — the same resolve/register path
`/auth/register` takes (rate-limited, never falls back to the active save).
Regression: `check_native_google_auth_mints_a_session` in `server/tests/test_multi_login.py`.
**Diagnosis recipe**: game shows template data after a "successful" login → check
`sessions` for the login time; zero new rows means the login body carried no id, which
means the sign-in endpoint the client used answered without a token.

### Altar/building points — one key, never negative (2026-08-17, e118699)

The altar pool ("building points") used **two keys**: `buildingPoint` (singular, the
protocol key, saved verbatim from the client echo) and `buildingPoints` (plural, what the
admin grant and territory fetch read). A negative client value persisted because the save
handler had no lower bound. Fix: `r_building_save` clamps `lo=0`; `_repair_player_state`
migrates the plural key (max-merge, clamp ≥ 0, pop); every writer/reader (admin grant ×2,
dashboard `EDITABLE_FIELDS`) now uses `buildingPoint`. Regression tests:
`check_negative_pool_clamped`, `check_legacy_plural_key_migrates` in
`server/tests/test_building.py`.

### Known One-Time Lobby NRE (not blocking)
- `WorldPanel.Reload()` at IL offset 0x00000 — fires once during init, does not repeat. The stack trace doesn't show sub-calls, suggesting a direct field access on a null component. Hard to pinpoint without RVA; non-blocking since the lobby still renders.

### All previously patched NREs — verified 0 occurrences
- GameManager.IsKGMarbleAvailable (was ~2/s)
- GameManager.IsYearEventAvailable
- GameManager.GetBabelData
- GameManager.IsEventCardCollectingAvailable  
- GameManager.IsSpecialSeasonalEventOpened
- WorldPanel.ReloadNewContentAlert
- KGWikiPanel.FetchKGWiki
- PackageItem.InitCustomGrowthPackage / InitSeasonPassPackage
- DeckPanel.ReloadDeck / Reload
- PvPPanel.GetReceivableWinRewardCount / &lt;Init&gt;d__77.MoveNext

### Runtime debugging environment limitation (2026-07-02)
redroid here runs arm64 code through **ndk_translation on an x86_64 host**. This BLOCKS
Frida from hooking `libil2cpp.so` in the live game process — `Process.enumerateModules()`
never shows it, only `libndk_translation_proxy_*`. No runtime C# object inspection is
possible in this environment. All debugging must be static Ghidra decompile + live
trial-and-error via logcat/screenshots. Don't re-attempt Frida hooks here without a
different (non-redroid, or ARM-host) test environment.

### `List<T>` object layout (C#, ABI-agnostic — confirmed via arm32 dump.cs offsets)
`_items` ptr @+0x8, `_size` (`.Count`) @+0xc, `_version` @+0x10 — relative to the List
object's own pointer (dereference the containing field first). `FUN_02e91408` in the
arm32 build = `List<int>.IndexOf(value) != -1` (i.e. `.Contains(value)`).

### Deck-length invariant (server responses)
`DeckPanel.currentDeck` (RVA `0x1e1a018`, `FUN_01e1a018`) is a Unity-prefab **fixed-size
UI array** that indexes our server-sent deck array — deck must be `>=` this bound or
`IndexOutOfRangeException`. `WorldPanel.ReloadLobbyDeck` (RVA `0x21f4b98`) is the mirror:
it loops over OUR deck length indexing ITS OWN fixed UI arrays, so deck must be `<=` that
bound too. Both currently land on **6** (`server/data/default_player.json` →
`decks[0].deck` length = `DECK_SLOTS` in `server.py`). Previously guessed wrong (5 vs 6)
more than once before Ghidra-verifying both RVAs — don't re-guess if this regresses.

### Artifact secondary-stat crash — `ArtifactOptionUI.Init` (RVA `0x1CEAFBC`)
Loop gate is `targets.Count` (top-level `ArtifactOptions.targets`,
`List<ArtifactOptions.Targets>`), NOT `types`/`lvs`. Only inside the gate does it call
`ResourceArtifactOption.GetValue(types[i], lvs[i], ...)` — a dictionary lookup where
`"None"` is never a registered key. Fix: `targets.Count` must equal `opt_count` exactly
(1/2/3/4 for Normal/King/God/KingGod), never padded to 4, so the hide-branch for the
remaining slots never reaches the `"None"` lookup. `positionIcons`
(`ArtifactOptionLine.Set`, RVA `0x1CEFA14`) use 1-based `targets.idx` values (1-6, via
`FUN_02e91408` = `.Contains`). Sending `idx` with >1 element crashes regardless of the
values (unresolved client JSON-parser quirk, Frida-blocked from further diagnosis — see
above); current server caps `idx` at 1 element.

### CDN xml bundle patching (master data + Strings text) — see docs/cdn-master-data.md
Full workflow, the "no XML comments in Strings_*.xml" gotcha (breaks Localizer runtime
registration for the whole locale, cost ~10 failed attempts to isolate on 2026-07-05),
and the Skill/Unit `<Name>`/`<Desc>`/`<SubName>` key-redirect trick are documented in
`docs/cdn-master-data.md`. Tool: `server/rebuild_xml_bundle.py` or
`server/refresh_master_data.py` (full CDN refresh + local mods + bundle rebuild in one shot).
Pristine bundle backup: `server/real_cdn/xml.bak` (md5 `779193a15d1377a7b8c2e6edfbe94095`).

### Cathy (10800-10810) skill tiers + text keys
Tiers 1-4: `Skill<N> → TransformSkill<1080N> → BuffAtCastSkill<10800N>`
(BaseDef/BaseMDef: 200→300→400→500). Bug fix: `Skill ID="10808" Inherit="108200"` → `"10805"`.
Unit 10810 SubName redirects to `UnitSubName_10800` (not `UnitSubName_10810`).

Text keys added in `server/xml_live/Strings_*.xml` (EN+VI only):
- Skill: `SkillName_10800`, `SkillDesc_10800_Short/Long`
- Overcomes: `Overcome_10800_0` through `_4` (Def/MDef per tier)
- Unit: `UnitName_10810`, `UnitSubName_10800`, `UnitRealName_10800`, etc.
- Lore: `UnitConstellation/Hobby/Talent/Likes/Hates/Note_10800`
- All values end with `(nowl)` per user request (2026-07-05).

### Accessory / treasure / rift-weapon unlock gate (invasion difficulty)
Content unlock for accessory (trang sức), treasure, rift-weapon keys off **invasion cleared
difficulty**, NOT hard-mode clears. Constants in `ResourceChallengeSeason.Constants`:
TreasureUnlockDifficulty=1, **AccessoryUnlockDifficulty=6**, RiftWeaponUnlockDifficulty=11,
MaxDifficulty=25. Invasion stage naming maps to tiers: I-1..I-5 = diff 1-5, **II-1 = diff 6**.
The "[Corruption]" tag on the lock text (`Mode_Hard`=="Corruption") is a red herring — it is the
invasion difficulty tier that gates, not `bestClearedHardTheme`.

Client aggregates `GetInvasionClearedDifficulty(theme)` = `records.First(x=>x.theme==theme).difficulty`
vs the constant. `ThemeDifficultyRecordModel{theme@0x8, difficulty@0xC(=cleared), unlockedDifficulty@0x10}`.

**Server (2026-07-11)**: `data/response_config.json` `invasionUnlockedDifficulty` = **6** (was 5;
set `>=11` to also unlock rift-weapon). `server.py` `r_player()` emits per-theme records with
`"difficulty": unlocked` — it previously used the loop var `d` (1..unlocked), so `.First().difficulty`
returned 1 and accessory(6)/rift(11) stayed locked while treasure(1) worked (masking the bug). The
`d`-loop still pads the list length for `ProfilePanel.ReloadChallenge` per-tier indexing.

Broken-accessory fix: `make_accessory()` used an invalid `data.mainStat="ATK"` (garbage 99.9% stats +
blank names). `load_corruption_accessories()` now builds the 4 real Invasion II-1 reward accessories
from `FixedAccessoryPresets.xml` IDs 2000-2003 (valid stat keys AtkPer/MAtkPer/BaseCriticalProb/etc).

### Inbox (Post) system + custom mail text
Inbox = "Post" internally. Direct handlers in `server.py` (registered before the ROUTE_MODELS loop):
- `GET /post` → `PostResponseModel{posts:[PostData]}` (generated route_models wrongly mapped it to
  PostReceiveResponseModel with no `posts`, so a direct handler is required).
- `POST /post/receive` ← `{postId, receiveAll, targetUnit}` → `PostReceiveResponseModel{rewardListResponseData}`
  (grants Gold/Cash/Heart to player currency, removes the claimed post).
- `POST /admin/sendmail` — send a mail into `st["posts"]`.

`PostData = {id, type, title, text, rewardType, rewardId, rewardAmount, untilAt}`. Mail lives in
`st["posts"]` (persists, removed on claim). **`title`/`text` are localization KEYS**, run through
`Localizer` by `PostListItem.Set`; an unresolved key falls back to `Post_Title_Default` ("You got a
gift") / `Post_Content_Default`. reward/untilAt render literally.

**Custom (non-localized) title/text without a CDN Strings rebuild**: server prefixes the field with
`@raw:` (`_process_posts()` in `server.py`); the native `PostListItem.Set` hook strips the prefix and
writes the literal straight into the `Text` via `set_text`, bypassing the Localizer. Mail without the
prefix localizes normally. Lets a central server push arbitrary per-mail custom text to distributed
clients with no bundle rebuild.

**Reward types** (`PostData.rewardType` string + `rewardId` + `rewardAmount`). `RewardResponseData`
= `{type, id, count}` uses the same vocabulary; `ResourceInventoryItem.GetByRewardTypeAndID(type,id)`
resolves the icon.

> **`RewardResponseData.type` must be a CLIENT type string, and there is no `"Item"`.**
> `GetByRewardTypeAndID` (v171 RVA `0x363549C`) compares against a fixed literal set -
> `InventoryItem`, `Key`, `UnitExpItem`, `UnitSoulItem`, `CardSoul`, `Gold`, `Cash`, `Heart`,
> `Artifact`, `Treasure_*`, `Skin`, `NameTag`, `Flag`, … (dump them by walking its `adrp`+`ldr`
> slots through `.rela.dyn` → `script.json` `ScriptString`). The same strings are what
> `<Reward Type="…">` uses across the master data. An unmatched type resolves to no
> `ResourceInventoryItem`, and the reward then renders with a **wrong icon and a nonsense count** -
> that is the "Temple of Challenge Reward Chest gives x999 of something else" bug.
> The server's internal vocabulary (`Item`/`Unit`/`UnitSoul`, what `_grant_reward` and the
> dashboard use) is translated at the wire boundary by `_wire_rewards()` inside
> `_reward_list_data()` - every reward-carrying response goes through that one function, so state
> keys never move. Test: `server/tests/test_reward_vocabulary.py`.
>
> **`Key` is a ShopItem id, not an inventory id.** `<Reward Type="Key" ID="370">` means ShopItem
> 370, whose `<KeyItem>` names the inventory row (370 → **380**, 70000 → **70005**). `rewardbox.py`
> used to collapse `Key` into `Item` and grant id 370 directly, i.e. the wrong item; it now passes
> `Key` through and `_open_reward_box` resolves it with `missions.key_item_for()`, the same path
> mission rewards take. On claim, `server.py` `_grant_reward()` mutates player state; the client re-fetches
`/player`, `/player/getInventory`, `/card/all` so the grant appears (no client-side apply). Handled:
- **Gold / Cash / Heart** -> currency (`st.gold/cash/heart`).
- **Item** -> `st.inventory` (`itemIds`/`counts`), `rewardId` = `InventoryItems.xml` id. Covers all 173
  inventory items incl. `RewardBoxInventory`/`InstantRewardBox` (the game's own bundle-gift mechanism),
  vouchers, `CardLevelUpItem`, accessory-substat items. **This is the safe way to gift artifacts/
  treasures/accessories** - send a reward box, the player opens it.
- **Unit / Card** -> adds hero to `st.cards` (all heroes already owned on the god account, so usually a
  no-op). **UnitSoul** -> `st.cards[str(id)].soul += count` (soul shards).
- **Treasure** -> appended to `st.treasures` as a real owned instance (`make_treasure()` shape),
  skipped when `treasureId` is already owned - a duplicate shows as an empty slot in the treasure
  panel. **A default save owns every released treasure**, so gifting one is normally a visible
  no-op; check the save's list before concluding the mail system is broken.
- **Artifact / Accessory** -> render in the mail but are NOT auto-granted into state: directly
  injecting owned artifacts/accessories can trip client panel invariants (see the ArtifactOptionUI
  crash above). Gift them as an Item reward box instead.

The dashboard exposes the full sendable catalog via `GET /api/catalog` (Item 173 / Unit 73 / UnitSoul 73
/ Artifact 318 / Treasure 60 / Accessory 108, names resolved from `Strings_EN_US`) with a searchable id
picker; see the "Web dashboard" note in `server/README.md`. `/api/catalog` also returns
`grantable` / `displayOnly` — the dashboard groups the reward-type dropdown from those, so moving a
type between them is a one-line change in `dashboard.py`, not a UI edit.

### Dimension hero gacha — overcome, cardExpResults, and the two buy paths (2026-08-09)

**Dimension heroes** (e.g. D.Ophelia 10790) use `overcome` (0-5) for star upgrades instead of
`soul`. `overcome` is incremented on duplicate pulls. Key fields in `st.cards[str(unitId)]`:
`overcome` (int, default 0), `unitId` must be present in the dict.

**`_grant_reward()` dimension logic** (`server.py:2649`):
- First pull (hero NOT in cards): creates card with `SEED["cardTemplate"]`, then checks
  `Units.xml` `IsDimensionUnit` — if true, sets `overcome=1` (hero starts at 1 star).
- Duplicate (hero already in cards): increments `overcome += 1`, returns `True`.
- **Never delete a dimension hero from cards to "reset" them** — just set `overcome=0` or `1`.
  Deleting removes the hero entirely and shows "Not Owned" in barracks.

**Two gacha buy paths** (`server/shop_routes.py`) — both must handle dimension heroes:

1. **Direct gacha path** (line 140+, `/shop` with `gachaId` only): already has `newUnitIds`,
   `cardExpResults`, and `upgrade=True` + `DimensionOvercome` type change for duplicates.

2. **Shop buy path** (line 309+, `/shop` with `itemId` + `gachaId`, e.g. scroll purchase):
   - Must also check `_grant_reward()` return value → set `pull["upgrade"] = True` for dupes
   - Must change `rg["type"]` to `"DimensionOvercome"` and `rg["count"]` to overcome value
   - Must build `new_unit_ids` and `card_exp_results` lists
   - Must include `"newUnitIds": new_unit_ids, "cardExpResults": card_exp_results` in response

**`cardExpResults` is required** — without it, the client's local card state stays stale after
the gacha animation. The hero shows correct stars only after game restart (when `/card/all`
is re-fetched). With `cardExpResults`, the client updates immediately.

**`card_to_dict()` requires `unitId` in the card dict** — `server.py:340` reads `c["unitId"]`.
A card missing this field crashes the entire `/card/all` response, making ALL heroes show
"Not Owned". Always include `"unitId": rid` when constructing card dicts manually.

**KeyItem mismatch** — ShopItem and Gacha `<KeyItem>` can differ:
- ShopItem 70000: `<KeyItem>70005</KeyItem>` (scroll item)
- Gacha 8001: `<KeyItem>70000</KeyItem>` (key id for gacha rolls)
The buy path should prefer `gacha_el.findtext("KeyItem")` over `el.findtext("KeyItem")`.

**Gacha pool for 8001** (DimensionUnitGacha): 0.5% D.Ophelia, 1.5% unit 10490, 48% cores,
50% echoes — 98% of pulls are materials. Pity system: `GachaCeil` key `DimGachaCeil_PickUp`,
target=80 stacks. Pre-roll reset: `stacks[key] = stacks[key] % primary_limit`.

### Dashboard game art — hero portraits + item icons (2026-08-01, commit 8e7377a)

`webui-next/public/assets/{heroes,items}/*.webp` ship real game art, committed in-repo (2.2MB total,
zero-cost rule: binaries live on GitHub, never on OCI). `Avatar` (heroes page) and `ItemIcon` (items
page) render `/assets/<dir>/<id>.webp` with letter/icon fallback via `onError`.

- **Heroes (73/73)**: sprites `Unit_Illust_<uid>` (1024px) from `base_assets.apk`
  `assets/aa/Android/illusts_assets_all_e2c109d34546ff649ffc05fd03601e1f.bundle`; prefer the exact
  base name over `_FOOL` variants; downscale 256px WebP q85.
- **Items (156/176)**: sprite name = `InventoryItems.xml` `<Sprite>` value, else `InventoryItem_<id>`;
  sprites live in `sprites_assets_all_399fdbab3759918334e166259a6f87c3.bundle`, but their atlas
  textures are **external cab-* dependencies** — UnityPy must load ALL 81 bundles of the APK together
  (`unzip -j base_assets.apk "assets/aa/Android/*"` to one dir, then `UnityPy.load(dir)`) or the
  Sprite `.image` lookup fails with `File cab-… not found`. The 20 missing ids (2200s map skins,
  2400s, 4200s, `SeasonalEventToken_S26`) are CDN-runtime event content — no base sprite exists.
- Re-extraction tooling was ad-hoc python heredocs; reproduce from this recipe if a version bump
  shifts bundle names/hashes.

`POST /admin/sendmail` and the dashboard's `POST /api/player/{pid}/mail` both strip a hand-typed
`@raw:` before storing (`_process_posts` re-adds it at read time). The server.py copy used to
rebind its own loop variable and stored the prefix, which then rendered literally in game.

Regression test: `server/tests/test_rename_and_mail.py` (Treasure grant + dedupe, and the rename
persistence below).

### il2cpp hook techniques (`server/jni/stub.cpp`)
Two ways to hook a managed method from the stub `.so`. Picking wrong = hook installs ("success" log)
but the handler never fires:
1. **methodPointer swap** (`*(void**)methodInfo = &Hooked`): ONLY intercepts methods the **Unity engine
   invokes via MethodInfo.methodPointer** — MonoBehaviour messages (`Update`/`OnEnable`/`Awake`/`Start`).
   `BattleManager.Update` (stat poller) uses this. Invisible to C#→C# calls.
2. **inline detour** (`install_inline_hook()`): patches the compiled function prologue (16-byte absolute
   jump `LDR X17,#8; BR X17; .quad dest`) + an mmap'd trampoline (16 stolen bytes + jump back to
   target+16) for the original. Intercepts **all callers including direct C#→C# compiled calls**, because
   `obj.Method(arg)` compiles to a direct `bl` to the native function and never derefs methodPointer.
   Guard: aborts if any of the 4 stolen prologue instrs is PC-relative (ADR/ADRP/LDR-literal/B/BL/B.cond/
   CBZ/TBZ) — can't relocate them; most prologues (stp/mov/sub sp) are PIC so it works.

**Before debugging a hook, confirm it was installed.** The stub logs exactly one line per hook. All
three failures below were silent and each cost a session:

- **Wrong `dlopen` handle.** The poll loop used to take `dlopen("libil2cpp.so",RTLD_NOLOAD)` and fall
  back to the NEO packer (`librolineng.so`). The dex loader loads the packer long **before** Unity
  loads libil2cpp, so poll 0 returned the packer and every `il2cpp_*` `dlsym` failed — no hooks, only
  a `Failed to resolve il2cpp_*` line to notice. A handle is now accepted only if it exports
  `il2cpp_domain_get`. **Tell-tale: `libil2cpp.so is loaded (poll took 0s)` is the bug; 1s+ is right.**
- **`r-xp` never matches under ndk_translation.** Guest ARM64 pages are mapped `r--p` and executed by
  the translator, so any `/proc/self/maps` scan filtering on `r-xp` finds nothing and its whole
  fallback is dead code. Use `dl_iterate_phdr` for a load bias (`dlpi_addr`); libil2cpp's first LOAD
  is at vaddr 0, so `dlpi_addr + <symbol VMA>` is the runtime address, with no `-0x4000` fudge.
- **`#if 0` left behind.** A diagnostic session wrapped the Google-login redirect, the
  `Scene_Login.Update` web-login bridge **and** the `Scene_Lobby.Awake` singleton guard in one
  `#if 0` block and never restored it. Nothing warned; the button just did nothing.

`PostListItem.Set` (the custom-mail hook) needed #2: it's rendered via a UITableView cell callback
(direct C# call), and neither `PostListItem` nor `PostBoxPanel` defines any Unity message. First
attempt used #1 → "Hooked successfully" but the handler never ran. Verified in-game 2026-07-11.

### Awakening (thức tỉnh) — `potentialTier` semantics (v171.1.00, fixed 2026-08-01)

Awakening = the potential system: **one tier, 0 = not awakened, 1 = awakened (max)**. Client
constants: `Constants.PotentialTier.Max = 1` (`.cctor` @ RVA `0x2F56C4C`), unlock levels
`GetFirstSemiPotentialLv=4 / GetSecondSemiPotentialLv=8 / GetPotentialLv=16`. The client renders the
awakened badge from `CardData.potentialTier` (field @ `0xB8`, ObscuredInt) via localize key
`CardPotentialTier_` ("Thức tỉnh {tier}" in VI). **Seed `potentialTier` MUST be 0** — the old
`default_player.json` seeded 1, so every fresh lv1 hero showed "Thức tỉnh 1" and the detail screen
could not change it.

Client enable rules (decompiled, v171.1.00):
- `Constants.NeedToUpgradePotentialTier(CardData)` @ RVA `0x2F4EFC4`: returns true only when
  `level == 16` AND `potentialTier == 0` (drives the upgrade affordance; "16+" unlock text =
  literal `Cardinfo_16+Potential_Unlocked`).
- `PotentialButton.Set(...)` @ RVA `0x31C0F20` (called from `CardInfoPanel.ReloadTier1Potentials` @
  `0x31788C0`): button enabled only if `level >= potential.ReqLevel` (master-data `ResourceUnit.
  Potential.ReqLevel`, 16 for the tier-1 potentials) and `potentialTier < Max`.
- Server-side upgrade endpoint already existed and does the right thing: `POST /card/upgradePotentialTier`
  (`r_card_upgrade_potential`, increments tier, no level check — client gates first).
- Slot selection: `PotentialButton.SetPotential` → `GameManager.SetPotential` → `POST /deck/setPotential`
  with `SetCardPotentialRequestModel = {presetIdx, idx, unitId, potential}` — exactly what
  `r_deck_set_potential` reads.

Fix (commit `95fd9ee`): `data/default_player.json` `cardTemplate.potentialTier` 1 → 0, same in
`admin_api.py` give-all-heroes. Existing saves must be reset in place (`playerdb.save` loop — no
`save_player`; API is `save(uid, st)`). Deploy DB had 3 players fixed (dev-0001 + two redroid test
accounts). A lv30 hero on the god account is unawakened after the fix and can be awakened once via
the button — by design.

**Static client analysis without Ghidra**: for a small function, disassemble with capstone straight
off `il2cpp/v171.0.00/libil2cpp_v171_ssl.so` — file offset = `RVA - 0x4000` (dump.cs `RVA:` lines).
ObscuredInt fields are read as a 20-byte pair (`ldur q0,[x,#+0x14]` + `ldr w8,[x,#+0x14+4]` copied to
stack) then decrypted via the thunk at RVA `0x2B84070` (`b 0x2B8EB3C`; x1=0). Every "CardData field"
read in UI code follows this pattern; grep dump.cs for the class, take the method RVA, disassemble.
String-literals cross-ref: `script.json` `ScriptString[].Address` gives literal VMAs (e.g.
`CardPotentialTier_` @ `0x6A4A6B0`), but script.json methods carry **no** literal references, so
identifying the using method still needs raw scanning — prefer decompiling the panel method directly.

### Public OCI deploy (2026-08-01) — `213.35.110.245`

Live private server for real clients; verified working end-to-end on redroid 2026-08-01 (guest
auto-register + Google web-login bridge → player created on deploy DB, CDN bundle + lobby fetches
served, arena battles counted).

- **SSH**: `ssh -i /home/nowl/Code/kgc/oracle/ssh-key-2026-07-31.key -o IdentitiesOnly=yes
  ubuntu@213.35.110.245` (Ubuntu 20.04 x86_64, hostname `instance-20260727-1513`; the key was
  injected via a **boot-volume swap** through a temp instance `instance-20260801-0037`/
  `161.118.225.174`).
  Console connections need `-i` on both hops + `HostKeyAlgorithms=+ssh-rsa
  PubkeyAcceptedAlgorithms=+ssh-rsa` (serial console only; `exec request failed` is normal).
- **Services**: `kgc.service` (runs `serve_public.sh`: preflight → HTTP 8080 + TLS 8443 with
  self-signed `cert.pem`), `kgc-dashboard.service` (dashboard.py :8081). `serve_public.sh` sets
  `KGC_QUIET=1` and **redirects uvicorn output to `/tmp/kgc_pub_http.log` + `/tmp/kgc_pub_tls.log` —
  NOT journald**. Trace lines (`[213.35.110.245] CDN GET … -> HIT`, `[auth] login id#… -> uid=…`)
  live in those files; journald only has systemd/spawn lines.
- **Exposure**: OCI security list + instance iptables (saved persistent) open 22/80/443/8080/8081/8443;
  iptables NAT PREROUTING `80→8080`, `443→8443`. Client APK bakes `SHARE_HOST=213.35.110.245`
  (HTTP for API + CDN, HTTPS for the TLS server; the SSL-bypass patch accepts the self-signed cert).
- **Python**: 3.8.10 is too old for fastapi≥0.140 — python-build-standalone 3.12.13 installed at
  `~/py312`, venv rebuilt at `/home/ubuntu/kgc/.venv` (old 3.8 kept as `.venv.38`). `pip install -e .`
  fails on purpose (needs JRE keytool for APK tooling) — plain `pip install -r requirements.txt` is
  what the server needs. `git-lfs` required for `libil2cpp_v171_ssl.so`; `script.json` is gitignored
  and must be rsynced separately from `il2cpp/v171.0.00/`.
- **Deploy flow**: push to GitHub `nowl-it/kgc-private-server` → on server `git pull` → restart the
  touched service(s). Dashboard auth is username/password only — create the first account with
  `python3 dashboard.py --create-admin <user>` (playerdb.admin_create); there is no token mode.
  Admin API `GET /api/players?admin_token=…` lists players.
- **CI/CD (GitHub Actions, since 2026-08-01)**: `.github/workflows/ci.yml` runs the full pytest suite
  (22 tests, `server/tests/`) on push/PR touching `server/**` — needs `pytest httpx httpx2` installed
  on top of requirements.txt (fastapi 0.141's TestClient wants `httpx2`; dashboard tests import
  `httpx`, which mitmproxy no longer pulls in). `.github/workflows/deploy.yml` auto-deploys on push to
  main touching `server/**` (plus `workflow_dispatch`): SSH with a **restricted deploy key** whose
  authorized_keys line is `restrict,command="/home/ubuntu/kgc/server/deploy_hook.sh"` — the hook
  (versioned in-repo) refuses on dirty tracked files, `git pull --ff-only`, then `sudo -n systemctl
  restart kgc.service` + `kgc-dashboard.service`. Key = GitHub secret `DEPLOY_KEY`, host key pinned
  as repo variable `SERVER_HOST_KEY` (ed25519; rotate both if the instance is rebuilt). The deploy
  key can run ONLY the hook — it cannot open a shell.
- **Dashboard UI build**: esbuild bundle in `server/webui/` (`build.mjs` → `dist/app.js`, one
  minified file, no importmap) — `dashboard.py` serves `webui/dist` when present. Rebuild locally,
  commit `dist/`, then `git pull` on server.
- **Client release workflow** (`.github/workflows/build-xapk.yml`, manual dispatch): builds
  `KingBugCastle_172.0.00.xapk` (`KGC_APK_SRC=xapk_extracted_v1720 SHARE_HOST=… --share`, job needs
  `permissions: contents: write` or `gh release create` 403s) and creates a GitHub Release whose
  **name = `King Bug Castle <version>`** and **asset = `KingBugCastle_<version>.xapk`** (version =
  `tag` input, default **`v172.0.00`**; if that tag already exists a `-YYYYMMDD-HHMMSS` suffix is
  appended). **Release notes are detailed but must never mention the server host / URLs / build
  command** — keep them to generic feature + install + troubleshooting text. The `stock-v172.0.00`
  release (base source xapk, `com.awesomepiece.castle@172.0.00.xapk`, 1.1GB) is **deleted
  (release + tag) after every build** — the workflow downloads it from GitHub CDN (free, never
  from the OCI box: paid egress) during the build, then removes it. To build again, re-create it
  first from the local copy at `apk/com.awesomepiece.castle@172.0.00.xapk`:
  `gh release create stock-v172.0.00 --title "Stock XAPK v172.0.00 (CI build source)" --notes "…" --latest=false 'apk/com.awesomepiece.castle@172.0.00.xapk'`.
- **Zero-cost rule (user-mandated, 2026-07-31)**: nothing may cost real money. GitHub Actions +
  public-repo release assets are free; the 1.1GB stock xapk and built client xapk are stored there,
  not on OCI. Keep any large binary off the OCI instance (egress is billed); OCI hosts only the
  server code + master data.
- Local dev still runs on 8080/8443 with `--reload`; local port 8081 is taken by adb (redroid), so
  tunnel the dashboard via `ssh -N -L 8082:localhost:8081 …`.
- **Sudoers syntax gotcha (2026-08-01)**: NEVER write a comma (`,`) in a command specification inside a sudoers file. A comma is parsed as a list separator by sudoers, and if it's placed inside a command path or arguments without escaping, it triggers a parse error. A parse error in *any* include file (like `/etc/sudoers.d/`) will fail-close `sudo` system-wide. Always use `visudo -c -f <file>` to validate syntax before applying.
- **OCI Recovery & Quotas**:
  - The `Oracle Cloud Agent Run Command` feature is NOT supported on Ubuntu images (only Oracle Linux / CentOS / Windows), so it cannot be used for emergency root shell access.
  - E2.1.Micro free-tier quota is consumed by the existence of an instance, even if it is stopped.
  - ARM A1.Flex instances can be spun up as temporary recovery instances by detaching the boot volume from the broken instance and attaching it to the new ARM instance as the boot volume (if ARM capacity is available).
  - Never terminate the MAIN instance if you can avoid it, as its ephemeral public IP will be lost. Note: Reserving an IP when not attached to a running instance incurs charges, which violates the zero-cost rule.
