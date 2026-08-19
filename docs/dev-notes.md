# Dev Notes — Personal Reverse-Engineering Knowledge Base

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
  `/tmp/opencode/kgc_*dump*/out/dump.cs` (may not survive reboots — regenerate with
  Il2CppDumper if missing).
- **RVA vs file offset (ARM64)**: file offset = `RVA - 0x4000`. The 3 SSL patch rows in
  AGENTS.md are **raw file offsets** — everything else is RVA. Never mix.
- **dump.cs `Offset:`** field = `RVA - 0x4000` = raw file offset — matches `patch_apk()`
  conventions 1:1. Method name resolution = grep dump.cs for the class, read the method's
  `RVA: 0x...` line.
- **Tombstone `pc` values are RVAs** — resolve via `script.json`, never dump.cs offsets.
- **Disassembly**: capstone off the raw `.so` at file offset (`so[addr-0x4000:]`).
- **Find callers of a method**: raw-scan for `BL` targeting its RVA: `(w>>26)==0x25`,
  sign-extend `imm26`, `target = site + imm*4`. (How `Scene_Lobby.Update` was found from
  `POST /auth/login` in two hops.)
- **Frida is BLOCKED on redroid** (ndk_translation — `Process.enumerateModules()` never shows
  libil2cpp). Static Ghidra/capstone + logcat/screenshots only. Don't re-attempt.
- **Static-cctor guard pattern** (ignore while reading logic): `ldr w8,[x,#0xe0]; cbnz w8,skip;
  bl #0x2ad08a8` — runtime helper cluster: `0x2ad0774` (ensure static ctor), `0x2ad08a8`,
  `0x2ad09bc`, `0x2ad09c4`, `0x2ad09cc`. The `[x,#0x310]` bools are per-method cctor guards too.
- **Division magics**: unsigned `/5` = `umull x,w,0xCCCCCCCD; lsr #0x22`; signed `/10` =
  `smull x,w,0x66666667; lsr #0x3f; asr #0x21; add` (same magic, shift 33 vs 34 — check the
  shift to tell /10 from /5).
- **`List<T>.Find` in compiled code**: display class allocated via a `bl` helper, captures
  stored at `[disp,#0x10]/[disp,#0x14]`, then `Find(list, disp, null)` — the predicate thunk
  near `0x308xxxx` (v172) reads `[x1,#0x10]`/`[x1,#0x14]` (this.captures) vs `[x0,#0x18...]`.
  `Find` = `0x43cfcb8` (v172.0.01) / `0x43c49ec` (v171.0.00).
- **`List<T>` layout**: `_items` @+0x8, `_size` (`Count`) @+0xc, `_version` @+0x10 (relative to
  the List object pointer — dereference the containing field first).
- **Deck-length invariant**: server deck must be exactly 6 elements
  (`DECK_SLOTS`) — see AGENTS.md "Deck-length invariant".
- **String literals**: `script.json` `ScriptString[].Address` = literal VMAs; methods carry no
  literal refs — find the using method by decompiling, not string search.
- **Offsets move between versions** (v170.0.03 → v171 → v172: every prologue byte-identical,
  offsets shifted). Re-derive per version; never reuse across libs.

---

## 1. Invasion rewards — COMPLETE decode (2026-08-18)

User client is **v171.1.00** (no dump exists; v171.0.00 dump + v172.0.01 dump/binary are the
proxies — panel absent in v171.0.00, added by v171.1.00; GameManager API identical).

### Client contract

- `InvasionRewardDatasResponseModel{RewardData rewardDatas}`;
  `RewardData{int index@0x10, int pass@0x14, long rewardState@0x18}`.
  Rewards themselves come from CDN `InvasionRewards.xml` (flat IDs, `divmod(rid,100)`,
  200 rows: themes 1-20, 51-70 × 5 difficulties) — the response carries **only claim state**.
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
  `entry.rewardState = rewardState` (wholesale overwrite — sibling themes transiently wrong until
  re-fetch; that's the real game's behavior too).
- **`GetInvasionRewardDatasByPassIndex(pass)`** (v171.0.00 `0x304EE50`): entries with
  `entry.pass == pass` (b__0 v172 `0x308A978`).
- **`HasInvasionPass(passIndex, pass)`** (v171.0.00 `0x304EB98`, v172 `0x3055E90`):
  `Find(entry.index == passIndex && entry.pass == pass)` (b__0 v172 `0x308A8F0`).
- **`GetReceivableRewardCount(passIndex)`** (v172 `0x33EDB40`; the panel tab badge):
  - 25 rows: `theme = base + r/5`, `difficulty = r%5`, `base = (odd?51:0) + 5*(pass//2)`
    (v172.0.01 base is 0-based → theme 0 for pass 0 — its own quirk; v171.1.00 counts 1-based).
  - gate: skip row unless `GetInvasionClearedDifficulty(theme) > difficulty`
    (`0x30568B8` v172 = `records.First(t.theme==theme).difficulty` via Find, null → 0).
  - then: `entry.pass == 0` → count (pass-0 shortcut) **or** `HasInvasionPass(P, entry.pass)`
    → count — the count needs an entry `{index: P, pass: P}` for every pass P ≥ 2!
  - count only if NOT `InvasionRewardReceived(theme, difficulty, entry.pass)` (bit clear).
  - **Symptom of wrong shape**: all entries deserialize `{0,0,0}` → only pass 0 counts
    (25 on Part 1, 0 everywhere else) — exactly the user's report.

### Server response (the fix, shipped 7b84fc5, `server/routes/challenge_routes.py`)

`GET /invasion/reward` (no `theme` in body) returns 16 entries, normal-first, markers last:
1. **8 group entries** `{index: TI(t), pass: P(t), rewardState}` — one per (TI, pass) group,
   mask = OR over the group's 5 themes of `st_mask[t] << (5*((t-1)%10))`.
2. **2 pass-1 entries** `{index: 0|2, pass: 1}` for themes 1-20 (pass-reward display/claim).
3. **6 markers** `{index: p, pass: p, rewardState: 0}` for p = 2..7 — make
   `HasInvasionPass` true. Passes 0 and 1 need none (shortcut / own group entry).
   Do NOT add {0,0}/{1,1} markers — they'd shadow the real entries (same probe key).

Claim POST (`theme` present): `{rewardListData, rewardState: st_mask[theme] << (5*((theme-1)%10))}` —
the offset matters, the client bit-tests at `(d-1)+5*((theme-1)%10)`.

Server helpers: `_invasion_pass_index`, `_invasion_pass_of`, `_invasion_entry_mask`.
State key: `st["invasionRewardState"][str(theme)]` = per-theme 5-bit mask (bit `d-1`), set by
`_invasion_claim` regardless of `pass` (normal + pass claims share one bit — deliberate
simplification). Tests: `server/tests/test_invasion_reward.py` (run with `python3
tests/test_invasion_reward.py` — the `check_*` functions are not pytest-collected).

---

## 2. Weekly ranking / eliteRankingScore (2026-08-14/18)

- Score submission = `eliteRankingScore` (long, field offset 0xC8) inside `POST /game/complete` —
  **no separate score POST**. `RestAPI.AddRanking` only fires from a debug button
  (`SettingsPanel.<OnClickTestRanking>`). The ranking-stage battle ("Measure Combat Power")
  computes `GetRankingScore` (v171 `0x2d70230`) → stored → complete request carries it.
- `r_game_complete` stores best in `st["eliteRankingScore"]`; `r_ranking` prefers it, falls back
  to `bestClearedTheme*100+bestClearedStage`. Test: `check_elite_score_flows_through_game_complete`.
- No `ranking*` string literals in v171/v172 `.so` — API paths are static fields; **the TLS log
  (`/tmp/kgc_pub_tls.log`) is the source of truth for what the client calls**.
- `GetRankingServerEndPoint()` patched (v172.0.01 file `0x2CBB2C4`) to return `Web._endPoint`
  (127.0.0.1) instead of the cloud-run URL.
- Leaderboard roster safety in `roster.py`: `deck_units` (6, pad with
  `[10000,10010,10020,10030,10040,10050]`), `rank_row` (never-null names), `playerRank` always
  populated for the caller. Empty fallback model → `RankingPanel` NRE — routes must return
  populated rows.

## 3. Daily reset (2026-07-31)

`tomorrow` must be **derived** (`next_reset_iso()` — next UTC midnight, `+7d` for `nextWeek`),
never stored: `Scene_Lobby.Update` (RVA `0x34EA5F0`+) re-runs the whole login chain at 1 Hz when
`now >= tomorrow_` (`PlayerDataResponseModel.tomorrow` @ 0xD0). A past value = constant
re-login loop, 17 req/s, NO exceptions. Test: `server/tests/test_daily_reset.py`.
Fixed-period loops with no exception = client timer, not retry.

## 4. Auth & sessions (2026-08-18)

- `_uid_for_login`: id-less logins refused in multiplayer (never fall back to the active save —
  that minted dev-0001 sessions every ~5-20 min). Single-player fallback only.
- `GET /auth?id=...` (native Google sign-in) MUST mint a token (`direct_routes.py` →
  `mint_session_token`) — an empty model means a fresh client never gets `accessToken` and every
  later request hits the throwaway template save ("KingBug"). Diagnosis: zero new session rows
  at login time = the login body carried no id.
- Template uid is `""`; every key fallback is `st.get("uid") or "dev-0001"` — never persist a
  `""` or `guest-0001` row. Full write-up: `docs/multi-account-login.md`.
- `dev-0001` = NightOwL since 2026-08-18 (uid `p-410890b421a5`, merged; old KingBug save
  deleted, backup in `server/state/backups/players.db.bak-uidmerge-*`).

## 5. Reward vocabulary (2026-08-09/18)

- Wire types are CLIENT strings (`InventoryItem`, `Key`, `Gold`, `Cash`, `Heart`, `UnitSoul`,
  `CardSoul`, `Artifact`, `Treasure_*`, `Skin`, ...) — there is **no `"Item"`**; an unmatched
  type renders a wrong icon + nonsense count. Internal state keys translate at the wire boundary
  in `_wire_rewards()` (`_reward_list_data()`); state keys never move.
  Test: `server/tests/test_reward_vocabulary.py`.
- **`Key` = ShopItem id**, not inventory id: `<Reward Type="Key" ID="370">` → ShopItem 370,
  `<KeyItem>` names the inventory row (370→380, 70000→70005). `missions.key_item_for()`.
- Safe way to gift artifacts/treasures/accessories: send a **reward box** (Item reward), the
  player opens it. Direct Artifact/Accessory injection can trip panel invariants
  (ArtifactOptionUI crash — see AGENTS.md).
- Dashboard catalog: `GET /api/catalog` (173 items / 73 units / 318 artifacts / 60 treasures /
  108 accessories, names from `Strings_EN_US`).

## 6. Dimension gacha & cards (2026-08-09)

- Dimension heroes (e.g. D.Ophelia 10790) use `overcome` (0-5), NOT `soul`; first pull sets
  `overcome=1`, duplicates increment. Never delete the card to "reset" — set `overcome`.
- Both buy paths (`server/shop_routes.py`): `_grant_reward()` return → `pull["upgrade"]`,
  `rg["type"]="DimensionOvercome"`, and **`newUnitIds` + `cardExpResults` are mandatory** —
  without them the client's card state is stale until restart.
- `card_to_dict()` REQUIRES `unitId` in the card dict (server.py:340) — missing it crashes
  `/card/all` → all heroes show "Not Owned".
- Gacha `<KeyItem>` ≠ Shop `<KeyItem>` (8001→70000, shop 70000→70005) — prefer the gacha's.

## 7. Awakening / potentialTier (2026-08-01)

- `potentialTier`: 0 = not awakened, 1 = max. Seed MUST be 0 (`default_player.json` had 1 →
  every fresh hero showed "Thức tỉnh 1"). Client enables only at `level==16 && tier==0`.
- Upgrade endpoint exists and is correct: `POST /card/upgradePotentialTier` (client gates).
- Slot selection: `POST /deck/setPotential` `{presetIdx, idx, unitId, potential}`.
- ObscuredInt fields read as 20-byte pairs via thunk RVA `0x2B84070` (v171.0.00) — static
  analysis without Ghidra: capstone straight off the .so, file = RVA-0x4000.

## 8. CDN / master data (2026-07-05)

- `docs/cdn-master-data.md` — bundle rebuild, Strings gotchas (no XML comments in
  Strings_*.xml — breaks the whole locale's Localizer), Skill/Unit key-redirect trick.
- Tools: `server/rebuild_xml_bundle.py`, `server/refresh_master_data.py`; pristine backup
  `server/real_cdn/xml.bak` (md5 `779193a15d1377a7b8c2e6edfbe94095`).
- **Host rebinding needs two passes**: `patch_hosts.py` (stringLiteral table) +
  `patch_leftover_hosts.py` (field/parameter defaults — `castle-infra-server…run.app`,
  `kgc-cdn-1.awesomepiece.com/patch/`). Verify 0 real hosts remain after.

## 9. Content-unlock gates (2026-07-11)

- Accessory/treasure/rift-weapon unlock keys off **invasion cleared difficulty**
  (`ResourceChallengeSeason.Constants`: Treasure=1, **Accessory=6**, RiftWeapon=11, Max=25;
  invasion II-1 = diff 6). `[Corruption]` tag is a red herring.
- `data/response_config.json` `invasionUnlockedDifficulty` = 6 (≥11 unlocks rift-weapon too).
- `r_player()` emits per-theme records with `"difficulty": unlocked` — it previously used the
  loop var `d` (1..unlocked) so `.First().difficulty` returned 1 and 6/11 stayed locked
  (masked by treasure=1 working). The `d`-loop still pads list length for
  `ProfilePanel.ReloadChallenge`.
- Accessories: `load_corruption_accessories()` builds the 4 real Invasion II-1 rewards from
  `FixedAccessoryPresets.xml` IDs 2000-2003 (valid stat keys — `mainStat="ATK"` was garbage).

### 9a. Accessory change-sub-stat — duplicate-tier decode (2026-08-18, d843ed5)

**Client models (v172.0.01)**: `AccessoryChangeSubStatRequestModel{accessoryId, targetSubStat,
itemId}` — `targetSubStat` is the **OLD** stat (confirm panel `_targetSubStatName` =
`beforeStatNames[targetIndex]`). Response `AccessoryResultResponseModel{accessories,
deletedAccessories, playerGold, playerCash, inventories, addedExpItems}` — exactly what
`_make_result_response` sends; the client's `AccessoryModel.data.subStats` = `List<{key,value}>`
objects (NOT strings — the parallel `subStats: List<string>`/`subStatScores: List<float>` are a
second, deduped view).

**Client apply path**: `<OnClickConfirm>d__17.MoveNext` (RVA 0x334FF70) → success → `GameManager`
@ RVA 0x305B060: for each response accessory, find by id in the owned list then
**`CopyFrom` (RVA 0x2CCCAC0 = shallow field copy, no merge)** — list entries are never replaced,
only field-copied; not-found → append; then remove `deletedAccessories`, apply gold/cash.

**Root cause of "chosen stat applied + extra lower-tier stats"**: `FixedAccessoryPresets.xml`
tier lines are additive duplicates of the same key (e.g. 6× `BaseDefDen 4.0` + 1× `2.0`), and
`make_fixed_accessory` kept every line as its own `data.subStats` entry (only the parallel lists
were deduped). The client renders `data.subStats`, so seeded accessories showed 7-8 stat lines;
the change handler replaced only the FIRST copy, leaving the rest as "extras" (and handing the
full summed score to the new stat while the leftover copies kept their own — inflated pool).

**Fix (server-side only)**: `make_fixed_accessory` (both copies: `routes/accessory.py` +
`routes/rewardbox.py`) builds `data.subStats` from the deduped `scores` dict (one entry per key,
value = score × unit); `ensure_accessory_state` merges duplicates in existing saves (heal —
38/38 live players fixed at deploy); `r_accessory_change_sub_stat` removes ALL `target_stat`
entries and inserts one `new_stat` entry with the summed score at the first removed index.
Regression: `test_accessory_merge_duplicate_substats` in `server/tests/test_accessory.py`.
Verified live: dev-0001 acc 62 `[AtkPer 26.0, BaseDef 80.0]` after manual remnant cleanup
(the old handler had given AtkPer the full 26 pool while leaving BaseDefDen 22 behind).

## 10. Post/mail system (2026-07-11)

- Inbox = "Post": direct handlers `GET /post`, `POST /post/receive`, `POST /admin/sendmail`
  (registered before the ROUTE_MODELS loop — generated models lack `posts`).
- `title`/`text` are localization KEYS (fallback `Post_Title_Default`); `@raw:` prefix bypasses
  the Localizer via the native `PostListItem.Set` hook (strip at write, re-add at read —
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

- `[GAME/COMPLETE] body=` debug print in `r_game_complete` — confirm from a real battle, then
  remove.
- v172.0.01 `GetReceivableRewardCount` uses a 0-based theme base (theme 0 for pass 0, gate
  fails → 20 not 25) — its own quirk; not our bug, not fixable server-side. Verify against a
  real v172 client if one ever appears.
- One-time `WorldPanel.Reload()` NRE at IL offset 0x00000 — non-blocking, unpinned.
- `deck-reload`/`deck-reload2` v170 patches still disabled (root-cause investigation 2026-07-02,
  never re-enabled — re-derive v171+ offsets if ever needed).

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
  - colosseum (semiSeason=2): `[-30,-15,15]` — semi 1 started 30d ago, semi 2 started 15d ago
  - pvpInfo (semiSeason=1): `[-15,16,31]` — semi 1 started 15d ago
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

### Friendly Battle (custom match) — implemented 2026-08-19
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
5. After battle: `POST /colosseum/complete-round-data` — same handler as regular, but
   friendly matches are NOT supposed to affect score. (Currently they still do because the
   client sends the same `win` flag — a `gameType` field would be needed to differentiate.)

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