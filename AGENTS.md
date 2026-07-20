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
compiles to a native il2cpp poller + UI hooks (~350KB, padded back to the original 510KB so the
patch-set size check passes). It still registers no-op JNI `ZCWAVE_*` methods (boots past the
anti-cheat), then a worker thread dlopen's `libil2cpp.so` and installs hooks (GameUnit stat poller
on `BattleManager.Update`; custom-mail hook on `PostListItem.Set`). See "il2cpp hook techniques" below.

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

### ARM64 Patch Inventory — v171.0.00 private build (`server/build_v171_private.py`)

v171 ships **no on-disk `libil2cpp.so`** (XIGNCODE NEO packs + encrypts it inside `libaledatic.so`).
The build injects the offline-recovered `il2cpp/v171.0.00/libil2cpp_v171_ssl.so` and NOPs the NEO
unpack path — see [docs/mftl-extraction.md](docs/mftl-extraction.md) for the recovery recipe and
[docs/v171-private-build.md](docs/v171-private-build.md) for the operator playbook.

**`libil2cpp_v171_ssl.so` must be pristine + exactly 3 patches.** It rotted over several sessions
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

The NRE stubs are a straight port of the v170 set (rows 5-14 of the v170 table above) — every prologue
came back **byte-identical**, only the offsets moved, which is what confirms the `script.json` mapping.
v170's `WorldPanel.IsKGMarbleAvailable` has **no v171 counterpart** and was dropped.

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
above); current server caps `idx` at 1 element. Full writeup:
`documentation/GOD_ACCOUNT_DATA_AGENT_PROMPT.md`.

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
resolves the icon. On claim, `server.py` `_grant_reward()` mutates player state; the client re-fetches
`/player`, `/player/getInventory`, `/card/all` so the grant appears (no client-side apply). Handled:
- **Gold / Cash / Heart** -> currency (`st.gold/cash/heart`).
- **Item** -> `st.inventory` (`itemIds`/`counts`), `rewardId` = `InventoryItems.xml` id. Covers all 173
  inventory items incl. `RewardBoxInventory`/`InstantRewardBox` (the game's own bundle-gift mechanism),
  vouchers, `CardLevelUpItem`, accessory-substat items. **This is the safe way to gift artifacts/
  treasures/accessories** - send a reward box, the player opens it.
- **Unit / Card** -> adds hero to `st.cards` (all heroes already owned on the god account, so usually a
  no-op). **UnitSoul** -> `st.cards[str(id)].soul += count` (soul shards).
- **Artifact / Treasure / Accessory** -> render in the mail but are NOT auto-granted into state:
  directly injecting owned artifacts/accessories can trip client panel invariants (see the
  ArtifactOptionUI crash above). Gift them as an Item reward box instead.

The dashboard exposes the full sendable catalog via `GET /api/catalog` (Item 173 / Unit 71 / UnitSoul 71
/ Artifact 318 / Treasure 59 / Accessory 108, names resolved from `Strings_EN_US`) with a searchable id
picker; see the "Web dashboard" note in `server/README.md`.

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

`PostListItem.Set` (the custom-mail hook) needed #2: it's rendered via a UITableView cell callback
(direct C# call), and neither `PostListItem` nor `PostBoxPanel` defines any Unity message. First
attempt used #1 → "Hooked successfully" but the handler never ran. Verified in-game 2026-07-11.
