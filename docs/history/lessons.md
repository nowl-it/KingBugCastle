# Lessons - the trap ledger

Every entry below cost at least one session. They are grouped by *what you see*, because
that is how you will meet them again.

---

## 1. Diagnosis traps

### A fixed-period request loop is a client timer, not a retry
**Symptom:** the server logs the same endpoint every second, forever. No exception client-side,
nothing in logcat.
**Cause:** `TOMORROW` in the player save was frozen at account creation, so
`Scene_Lobby.Update` saw `now >= tomorrow` and called `FetchNextDay` → `RestAPI.Login` → the
whole lobby fetch chain, at 1 Hz, indefinitely.
**Rule:** derive time boundaries (`next_reset_iso()`), never store them. If a loop has a
*constant* period and no error, suspect a client compare against stale state.

### A "managed NRE" with no useful frame is a null you can locate yourself
**Symptom:** `NullReferenceException` at IL offset `0x00000`, or a location-stripped managed
throw that tells you nothing.
**Method:** temporarily NOP every null-check branch in the suspect method
(`KGC_LOBBY_DIAG=1` did exactly this). The first null object then falls through to its own
dereference and SIGSEGVs at a *real* fault PC. Resolve that PC through `script.json`.
This is how the black-lobby NRE was proved to be caused by the `ldr → mov` patches, not by
the singleton.

### Two offset conventions coexist. Mixing them wastes days
- `script.json` `ScriptMethod[].Address` and tombstone `pc` values are **RVAs**.
- The SSL patch table and some build patches are **raw file offsets**.
- File offset = `RVA − 0x4000` for `libil2cpp.so` - *not* for every library.
  `libaledatic.so` maps file == VMA; `librolineng.so` maps VMA == file − 0x4000; the NEO loader
  function itself grew between builds so offsets do **not** shift by a constant.
**Rule:** resolve crash frames via `script.json`, never by parsing `dump.cs` offsets, and
never by assuming the delta carries over to a different `.so`.

### Every il2cpp offset is per-lib
Bumping the game version shifts offsets even when the prologue bytes are byte-identical. The
project keeps one stub table per version (`_NRE_STUBS_V17100` … `_NRE_STUBS_V17310`) and picks
by `VER`. The cross-check that a re-derivation landed on the right method is *byte-identical
prologues across versions* - with `ShopItem.Init` as the documented exception (immediates
changed; match by instruction shape and recompute the `cbz` displacement).

### A hook that "installed successfully" may never fire
Three separate silent failures, one session each:
1. **Wrong `dlopen` handle.** Accept a handle only if it exports `il2cpp_domain_get`. Tell-tale:
   `libil2cpp.so is loaded (poll took 0s)` is the bug; 1 s+ is correct.
2. **`r-xp` never matches under ndk_translation.** Guest ARM64 pages are `r--p` and executed by
   the translator. Use `dl_iterate_phdr` for a load bias instead of scanning `/proc/self/maps`.
3. **`#if 0` left behind.** A diagnostic session wrapped three features in one `#if 0` and never
   restored it. Nothing warned; the button just did nothing.

### Pick the right hook mechanism or your handler never runs
- **methodPointer swap** intercepts only methods Unity invokes via
  `MethodInfo.methodPointer` - MonoBehaviour messages (`Update`/`Awake`/`OnEnable`).
- **inline detour** (prologue jump + trampoline) intercepts **all** callers, including direct
  C#→C# `bl`. Guard: abort if any stolen instruction is PC-relative.

`PostListItem.Set` needed the second kind - it is a UITableView cell callback, and neither
`PostListItem` nor `PostBoxPanel` defines a Unity message.

### Frida cannot help here
redroid runs arm64 code through **ndk_translation on an x86_64 host**.
`Process.enumerateModules()` never shows `libil2cpp.so`, only `libil2cpp_proxy_*`. There is no
runtime C# object inspection in this environment. All debugging is static decompile + live
trial-and-error via logcat and screenshots.

---

## 2. Binary patching traps

### Never hand-patch the lib you ship
`libil2cpp_v171_ssl.so` rotted over several sessions: 21 stray bytes, including a branch that
overwrote `mov w8,#-2` inside a `MoveNext` state machine. Result: infinite UniTask recursion,
stack overflow on "Loading resources", misdiagnosed across two sessions as an inherent IL2CPP
bug.
**Rule:** regenerate from pristine + the three SSL patches
(`server/patchers/make_v171_ssl_so.py --check` enforces zero stray bytes). Every build patch is
guarded by an expected-prologue check that raises rather than corrupting the binary.

### The `ldr → mov` klass patches are wrong, and the theory behind them is wrong
`LDR_PATCHES` rewrote `ldr x0, [xR]` in `Scene_Lobby.Init` to `mov x0, xR`, on the theory that
the TypeInfo self-pointer fixup never runs under ndk_translation.
It does run. `xR` holds the **GOT slot**; the `ldr` is what loads `Il2CppClass*` out of it. The
rewrite leaves `x0` pointing at the slot, so `klass->static_fields` reads garbage and the
singleton comes back null. 65 sites, off by default, must stay off.

### Disproven patches get deleted, not commented out
`KGC_ASSETBYPASS` rewrites the asset-bundle kickoff to skip `usePatch`/`getPatchFolder`. That
means the CDN `xml` bundle (strings + fonts) never downloads and every label renders as
garbled glyphs. It exists only as a debug escape hatch, and every session that "re-enabled" it
lost time.

### CRC cannot be faked by editing the catalog
Custom bundle bytes cannot retain the catalog's original CRC. Editing `m_ExtraDataString` to
`0000000000` is invalid JSON; shrinking it requires fragile binary-length repairs; catalog
corruption blocks *every* bundle. Force CRC to zero at the four runtime sites instead
(`AssetBundleRequestOptions.get_Crc` + three direct CRC arguments).

---

## 3. Client-contract traps

### `RewardResponseData.type` has no `"Item"`
`GetByRewardTypeAndID` compares against a fixed literal set - `InventoryItem`, `Key`,
`UnitExpItem`, `UnitSoulItem`, `CardSoul`, `Gold`, `Cash`, `Heart`, `Artifact`, `Treasure_*`,
`Skin`, `NameTag`, `Flag`, … An unmatched type resolves to no icon, and the reward renders with
the **wrong icon and a nonsense count**.
The server's internal vocabulary (`Item`/`Unit`/`UnitSoul`) is translated at the wire boundary
by `_wire_rewards()`. Every reward-carrying response goes through that one function.

### `Key` is a ShopItem id, not an inventory id
`<Reward Type="Key" ID="370">` means ShopItem 370, whose `<KeyItem>` names the inventory row
(370 → 380). Collapsing `Key` into `Item` grants the wrong item.

### Mail `title`/`text` are localization KEYS
`PostListItem.Set` runs them through `Localizer`; an unresolved key falls back to
`Post_Title_Default`. To push arbitrary text with no CDN rebuild, prefix with `@raw:` and let
the native hook write the literal straight into the `Text`.

### `ShopItem.Init` crashes on an empty list
The method indexes `get_Item(0)` without checking `Count`. The patch checks `Count == 0` and
jumps to the method's own epilogue - same shape across versions, only the final `bl` target
differs.

### Deck length is a two-sided invariant
`DeckPanel.currentDeck` indexes a fixed-size UI array (deck must be ≥ 6), and
`WorldPanel.ReloadLobbyDeck` loops over our deck indexing its own fixed arrays (deck must be
≤ 6). Both were Ghidra-verified. Landing on 6 is not a guess.

### Artifact options: `targets.Count` must equal the option count exactly
`ArtifactOptionUI.Init` gates on `targets.Count` and inside the gate calls
`ResourceArtifactOption.GetValue(types[i], lvs[i], …)`, where `"None"` is never a registered
key. Padding to 4 to "be safe" is what crashes it.

### Dimension heroes never get deleted to reset them
Deleting a dimension hero from `st.cards` removes it entirely and shows "Not Owned". Set
`overcome` instead. And `card_to_dict()` reads `c["unitId"]` - a card missing it kills the whole
`/card/all` response, making **all** heroes show "Not Owned".

### `cardExpResults` is mandatory for any gacha that grants a hero
Without it the client's local card state stays stale after the animation; stars appear correct
only after a restart. Both gacha buy paths must emit it.

---

## 4. State-model traps

### Two keys for one value means one of them is wrong
- **Altar points:** `buildingPoint` (protocol) vs `buildingPoints` (admin/territory). A negative
  client value persisted because no lower bound existed. Now one key, clamped ≥ 0, with an
  in-place migration for existing saves.
- **Accessory sub-stats:** `FixedAccessoryPresets` tier lines are additive duplicates of the same
  key, so seeded accessories showed 7-8 lines instead of one stat with a summed value. Merge by
  key at creation *and* in the change handler (remove all entries for `targetSubStat`, insert one
  `newStat`).

### The template save's `uid` must never be a save key
`default_player.json` carried `"uid": "guest-0001"`, and several paths used it as the save key,
minting a phantom row. Template uid is now `""` and every fallback is
`st.get("uid") or "dev-0001"`.

### Never fall back to "the active save" for an unidentified login
`_uid_for_login` did, so any `/auth/login` with no id and no token was handed the active save
*with a session bound to it*. In multiplayer the answer is `None` → login refused. A client
that presents a new guest id gets a **new** save, and the old one can be re-attached with
`playerdb.bind_login(old_id, new_uid)`.

### "My account became KingBug" means the login carried no id
`GET /auth` used to answer an empty model, so a fresh install never received a token; its
`/auth/login` went out id-less and every subsequent request hit the throwaway template save.
Diagnosis recipe: check `sessions` for the login time - **zero new rows** means the sign-in
endpoint answered without a token.

### Awakening is one tier, and the seed must be 0
`potentialTier` 0 = not awakened, 1 = awakened (max). The default save seeded 1, so every fresh
lv1 hero showed "Thức tỉnh 1" and the detail screen could not change it. Client-side gating:
level 16 + tier 0 for the upgrade affordance; the server endpoint does not re-check level.

### Accessory unlock keys off *invasion difficulty*, not hard-mode clears
`ResourceChallengeSeason.Constants`: Treasure 1, **Accessory 6**, RiftWeapon 11, Max 25.
The `[Corruption]` tag on the lock text is a red herring. `r_player()` must emit
`difficulty: unlocked` per theme - it used the loop variable once, so `.First().difficulty`
returned 1 and accessory/rift stayed locked while treasure worked, masking the bug.

---

## 5. Process traps

### `il2cpp` (the dumper) blocks on "press any key"
Every invocation that forgets to feed stdin hangs until the session is killed - and it was paid
for in tokens more than once. Documented in `docs/dev-notes.md`; drive stdin explicitly.

### A route with no model answers an empty model, which crashes panels
`RankingPanel` NREs on `myRankingItem.Set(model.playerRank, true)` when the ranking route
returns the generic empty `ResponseModel`. Missing routes become `OVERRIDES` returning a real
dict.
Related: `deck_units` must be exactly 6 elements and names must never be null, or
`RankingItem.Set` feeds null sprites to Unity UI.

### The TLS log is the only source of truth for what the client calls
No `ranking*` string literals exist in either `.so` - API paths are static string fields
populated from server data. Hunting paths by string search is a dead end; read
`/tmp/kgc_pub_tls.log`.

### `/auth/xcdSeed` index shifting
v171.0.01 **inserted** a literal at index 1545 of 25730, shifting 94% of all literal indices.
Mixing a v171.0.01 lib with v171.0.00 metadata is not "close enough" - libil2cpp compiles those
indices in. Lib and metadata must come from the same build.

### Deploys that only restart a unit file silently do nothing
`kgc.service` runs `serve_public.sh` and redirects uvicorn to `/tmp/kgc_pub_http.log` and
`/tmp/kgc_pub_tls.log` - **not** journald. Trace lines live in those files. The Caddy sync path
shipped as a 502 once because the deployed file and the unit were out of step.

---

## The three rules that would have prevented most of the above

1. **Read the real function before patching the symptom.** Decompile, then edit.
2. **Derive, never store.** Time boundaries, gates, offsets, CRC - anything copied into state
   goes stale.
3. **One representation per fact.** Two keys, two codepaths, or two sources of truth will
   diverge, and the divergence will be silent.
