# HANDOVER

Everything the next maintainer needs that is **not** already written down somewhere else.

The other docs tell you *how* to do things. This one tells you *what you are actually
signing up for*: which parts are load-bearing, which will break next, which "obvious"
change has already been tried and cost a week, and what the recurring job actually is.

Read this end to end once. After that, use it as the index.

---

## 0. Sixty-second orientation

King God Castle (`com.awesomepiece.castle`, Unity 2022 IL2CPP) is a **server-authoritative**
mobile game. There is no offline mode: the client asks the backend for everything it owns.
This repo is a from-scratch reimplementation of that backend, plus the client-side patching
needed to point a real APK at it.

Three deliverables, in dependency order:

1. **The server** (`server/`, FastAPI) - answers all 351 routes the client can call.
2. **The client build** (`server/build_v171_private.py`) - takes the store APK, unpacks the
   anti-cheat container, injects the game code, rebinds hostnames, re-signs, installs.
3. **The master data** (`server/xml_live/` → `server/real_cdn/xml`) - a cloned copy of the
   game's CDN content bundle, which we re-serve and occasionally edit.

It currently works end to end: v171.1.00 client boots to a full lobby on redroid, Guest login
succeeds, zero HTTP 500s across a play session.

**What this project is not:** it is not a cheat client, not a bot, and not something that
touches the live official servers. Everything runs against our own backend on our own device.

---

## 1. Day 1 - prove it still works before you change anything

Do this first. If any step fails, fix that before touching features; you will otherwise
spend a day debugging a break you inherited.

```bash
cd ~/Code/kgc/server

# 1. Test suite. 36 assert-based scripts, no framework. Each is runnable alone.
#    Takes ~3 min; test_playerdb_concurrent spawns real processes.
for f in tests/test_*.py; do python3 "$f" >/dev/null 2>&1 || echo "FAIL $f"; done
#    expect: no output

# 2. Module self-checks. Every extracted module has one.
for m in state config decoration_routes pvp territory_routes shop_routes \
         seasonal roster gamedata playerdb; do
  python3 $m.py >/dev/null 2>&1 || echo "FAIL $m"
done
python3 local_mods/__init__.py --check      # this one takes --check
#    expect: no FAIL; "ok: local_mods behave (5 mods, all idempotent)"

# 3. Response contract audit - checks what the client READS, not just HTTP 200.
python3 api_audit.py            # expect: routes audited 351/351, no high/medium

# 4. Route coverage - every path the client can call has a handler.
python3 route_coverage.py       # expect: only the 2 known never-called paths

# 5. "Is this safe to expose" gate.
python3 preflight.py            # expect: "ready to expose"

# 6. The unpacker still recovers a valid ELF from the packer.
python3 patchers/unpack_neo.py --self-check   # expect: 113836232 bytes

# 6b. Dashboard UI. Templates are compiled at runtime, so a typo renders a blank tab
#     instead of throwing - this is the only thing that catches it.
node webui/check_templates.mjs                # expect: 12 components, 11 modules

# 7. Bring the stack up (game :8080 + :8443 TLS, dashboard :8081)
./run.sh
```

Verified baseline (2026-07-31), so you can tell a real regression from noise:

| Check | Expected |
|---|---|
| Test scripts | **36/36 pass** |
| Module self-checks | 10/10 + `local_mods` ok |
| `config.py` | `171.1.00, gate 171100, 354 routes, xml xml_live` |
| `api_audit.py` | `351/351`, findings `{'null-object': 29}` - all **low** severity, no high/medium. If a panel ever looks empty, re-run with `--all` and check whether one of these 29 is the cause |
| `route_coverage.py` | 2 handlers for paths the v171 client never calls (`/territory`, `/x2/xls.cgi`) - harmless |
| `preflight.py` | `ready to expose (1 warning)` |
| `unpack_neo --self-check` | `113836232 bytes from lib/arm64-v8a/libxenerene.so` |
| `check_templates.mjs` | `webui templates ok (12 components, 11 modules)` |
| `gamedata.py` | 15623 strings, 73 heroes, 173 items, 300 buffs, 326 skills |
| `playerdb.py` | `sqlite, schema v4, 3 migrations` |

Then build and run a client:

```bash
KGC_APK_SRC=xapk_extracted_v1711 SHARE_HOST=127.0.0.1 ADB_SERIAL=localhost:5555 \
  python3 server/build_v171_private.py
adb shell am start -n com.nowl.castle/co.ab180.airbridge.unity.AirbridgeActivity
```

> Note the activity: **`AirbridgeActivity`**, not `MainActivity`. Launching MainActivity gives
> you a silent no-op and looks like a broken build.

**Green = the whole pipeline is intact.** That is the baseline you protect.

---

## 2. The mental model - four planes

Most wasted time in this project comes from editing the right value in the wrong plane.
`docs/README.md` describes two; there are really four.

| # | Plane | Lives in | Change takes effect | Symptom when you pick wrong |
|---|-------|----------|---------------------|------------------------------|
| 1 | **Player state** | `server/state/players.db` (SQLite) | Next request. No restart. | - |
| 2 | **API response shape** | `server.py` + route modules + `data/*.json` | `run.sh` auto-reloads | Client shows nothing / crashes on a null |
| 3 | **Client master data** | `server/xml_live/*.xml` → `real_cdn/xml` bundle | Rebuild bundle + restart + clear device UnityCache | "I edited the XML and nothing happened" |
| 4 | **Client code** | `libil2cpp.so` inside the APK | Full rebuild + reinstall | Only place a *behaviour* can change |

The classic confusion: **granting** a player a treasure is plane 1. Making that treasure
*exist and be un-gated* for the client is plane 3. Making the client stop crashing when it
renders it is plane 4. Three different edits, three different loops.

A second, subtler split: `server/xml_live/*.xml` feeds **both** plane 2 (the JSON API reads it
directly) and plane 3 (the bundle is built from it). Editing it changes the API immediately
but does **not** reach the client until you run `rebuild_xml_bundle.py`. Half the "the server
knows about it but the game doesn't" reports are this.

---

## 3. Which doc answers what

| Question | Doc |
|---|---|
| How do I run this from a fresh clone? | `SETUP.md` |
| Start servers, wire a device, push a change | `docs/deploy-and-run.md` |
| Give a player gold / items / units | `docs/save-editing.md` |
| Something is version-gated and invisible | `docs/content-unlock.md` |
| Edit master data and get it to the client | `docs/cdn-master-data.md` |
| Build a test stage / training dummy | `docs/stages-and-spawns.md` |
| Talk to the API by hand (curl/python) | `docs/api-and-crypto.md` |
| Build the v171 client | `docs/v171-private-build.md` |
| Recover `libil2cpp.so` from the packer | `docs/mftl-extraction.md` |
| Multiple accounts / devices / Google login | `docs/multi-account-login.md` |
| Expose it to strangers safely | `docs/public-hosting.md` |
| Ship an APK to a remote player | `SHARE.md` |
| Which file do I edit for X | `server/WORKFLOW.md` |
| ARM64 patch offsets, RVA maps, il2cpp internals | `AGENTS.md` |
| Dated session findings, "why is it like this" | `KNOWLEDGE.md` |
| Player-facing (Vietnamese) | `README_PLAYER.md`, `docs/v171-emulator-note.md` |

`AGENTS.md` and `KNOWLEDGE.md` are the two you will reread most. `AGENTS.md` is the reference
(tables, offsets); `KNOWLEDGE.md` is the narrative (what happened, what it cost).

---

## 4. The recurring job

This project is not "done and static". The upstream game keeps moving, and two things drift:

### 4a. Master-data patches (roughly weekly)

```bash
scripts/check_cdn_update.sh
```

It reports one of three states:

- **nothing** - no change.
- **new folder** (e.g. `2026_08_04`) - a real patch. Run:
  ```bash
  ./kgc-cli config fetch && ./kgc-cli config extract -o xml_history/<date>/
  python3 server/refresh_master_data.py         # --dry-run first
  python3 server/rebuild_xml_bundle.py
  ```
- **`REPUBLISH DETECTED`** - the devs rewrote the **same** folder in place. The folder name
  did not change, so `refresh_master_data.py`'s diff sees nothing. Use the other script:
  ```bash
  python3 server/rebase_xml_live.py xml_history/<date>
  python3 server/rebuild_xml_bundle.py
  ```

  This trap is real and cost a full debugging session: the devs **do** silently rewrite a
  published folder. `check_cdn_update.sh` now fingerprints the GCS `etag` header (one HEAD,
  no 4.5 MB download) specifically to catch it.

Both paths call `server/local_mods/` - the single source of truth for our five master-data
edits, all idempotent. **Never hand-edit `xml_live` for a change you want to survive a
refresh.** Put it in `local_mods/` or it is gone at the next patch.

### 4b. Client version bumps (roughly monthly)

The store client and the CDN folder move **independently**. `check_cdn_update.sh` watches
both. When the client bumps:

```bash
./kgc-cli download -v <version> --arch arm64 -o apk/
```

> Use `kgc-cli`, not `apkeep`. apkeep silently hands you the `armeabi_v7a` variant, which has
> no `config.arm64_v8a.apk`, and the build then fails much later with a confusing error.

Then, in order:

1. Check the packer. It is a ~114 MB `.so` whose **filename rotates every build**
   (`libaledatic` → `librolineng` → `libxenerene` …). **Match it by `SONAME = libappsign4a.so`,
   never by filename.** Same rule for the NEO blob (`assets/*.wio`, `*.fis` - also rotates).
2. Diff the packer against the previous version. v171.0.01 → v171.1.00 differed by **4 bytes
   across 3.3 MB** and all 12 NEO patch sites sat at identical offsets, so the existing build
   script covered both. If it is byte-similar, you are probably done.
3. Unpack its il2cpp: `python3 server/patchers/unpack_neo.py <packer.so> <out.so>`.
4. Re-derive the NRE stub offsets for the new lib (see §6c).
5. Build, install, play for 10 minutes, watch `adb logcat` and the server log for 500s.

---

## 5. The trap ledger

Each of these cost real time. They are grouped by where they bite.

### 5a. Client build

**The packer's Java stub calls `System.exit(1)`, and its class names rotate.**
A stock, unmodified v171.1.00 crash-loops on redroid too - ~100 ms after start, no tombstone,
no native crash, no linker error. The chain is: packer `JNI_OnLoad` → `bytehook_init` returns
**3** (`INITERR_SYM`; it cannot resolve symbols through `ndk_translation`) → `UnsatisfiedLinkError`
→ the Java stub's `catch { System.exit(1); }`. The only useful log line is
`bytehook_tag: … return: 3`.
`patchers/patch_genesis.py` strips the exit. It used to hardcode the class names
(`edu/ngrinesi/dichalanga` …), which rotate per build - so it printed "not found", patched
nothing, and the crash loop read as a brand-new bug. **It now locates the file by content**
(a `System.exit` inside a `loadLibrary` catch). Same rule as the SONAME one: match by
behaviour, not by name.
→ **Always verify stock crashes too before bisecting your own patches.**

**Injecting `libil2cpp.so` is not optional**, even though the packer carries its own copy of
the game code. `libunity.so` `dlopen()`s `"libil2cpp.so"` **by name**, and the packer only
writes that file out along the boot path our patches NOP. No file →
`JNI FatalError … dlopen failed: library "libil2cpp.so" not found` → SIGABRT in ~300 ms.
Both libs are mapped in a healthy run, which is exactly what makes the packer look
self-sufficient when it is not. Tested by building with the inject skipped.

**The 65 `ldr → mov` klass patches CAUSE the black lobby.** They look like a fix and are not.
They are env-gated **off** (`KGC_APPLY_LDR=1` to re-enable). Do not turn them on.

**Never set `KGC_ASSETBYPASS=1`.** It breaks Strings and the whole UI.

**`il2cpp/v171.0.01/` holds a PACKER, not il2cpp.** Check `SONAME`: `libappsign4a.so` = packer,
`libil2cpp.so` = game code. That file shipped mis-named for two days and read as "v171.0.01's
il2cpp is already extracted" when nobody had done it.

**Metadata is not drop-in across versions.** v171.0.01 *inserted* a string literal at index
1545 of 25730, shifting ~94% of the indices the older lib was compiled against. This only
matters on the `KGC_FORCE_V17100=1` fallback path now - the current build injects v171.1.00's
**own** il2cpp against its **own** shipped metadata, so no swap runs and there is nothing to
drift. If you ever do need the swap, `patch_metadata_swap.py` must run **before**
`patch_hosts.py` / `patch_metadata_http.py`.

### 5b. Master data / CDN

**Zero XML comments in `Strings_*.xml`.** The game's `Localizer.ParseTextAsset` mis-handles
comment nodes while iterating `<String>` children. **One** comment anywhere silently breaks
the **entire locale's** runtime dictionary - every `Localize(key)` call falls back to
returning the raw key, including entries that already worked in the pristine file. This is
not a size issue: a 1.7 KB comment-free batch worked; a much smaller edit with one comment
broke everything. Cost ~10 failed attempts to isolate.
`rebuild_xml_bundle.py` refuses to run if it detects one. **Do not bypass that check.**
(`Skills.xml`/`Units.xml`/`ActiveSkills.xml` use a more tolerant parser - comments there are
fine.)

**Cold-cache launch always hangs once.** The first launch after
`rm -rf …/files/UnityCache` hangs on "Loading resources" - all requests succeed, no exception.
Launch twice. **Match cache state on both sides of any A/B test**, or the confound reads as a
regression.

**Every lookup in `check_cdn_update.sh` must end in `|| true`.** It once grepped
`PATCH_FOLDER` out of `server.py` (which had moved to `response_config.json` long before), and
under `set -euo pipefail` the no-match grep killed the script *before* the etag section ever
ran. Silent abort, no error, looked like "no update".

**Unit 10810 is Alessia (Cathy's vampire form), not Ophelia.** Ophelia is 10790. Our
hand-written strings assumed otherwise; they have been dropped in favour of the official text
a republish shipped. Do not re-add them.

### 5c. Server

**A route can answer 200, with every declared field, and still be dead.** Four distinct ways,
all found by `api_audit.py` and gated by `tests/test_api_contract.py`:

1. A date-shaped string at `null` or `""` → the client's `DateTime.Parse` throws. Deadline-ish
   names (`expired`/`until`/`end`/`next`) need a **future** value; `expiredAt` in the past makes
   the client re-login immediately.
2. A handler group merged into `DYNAMIC_OVERRIDES` **after** `OVERRIDES` was snapshotted from
   it. ~30 decoration/mini-game routes were dead this way, and `route_coverage` still called
   them handled because it read the *source* dict. `OVERRIDES` is now built last, with an
   assert.
3. A wrong route→model mapping. `route_models.json` **guesses** by name similarity and records
   a `score`. `/player/rename` scored 0.58 into the wrong model, so every rename was silently
   discarded. Look the method up in `generated/restapi.json` and pin it in
   `data/route_models_extra.json` **with `_method`** - that field is the proof you checked, and
   `test_route_coverage` requires it. **Pin the superset, never narrow**: unknown keys are
   ignored by the client, a missing one is a dead panel.
4. Data under a name the client never reads. `/clan/ranking` sent `clanRankings`/`myClanRanking`
   for a model declaring `ranking`/`playerClanRank`. **Emit both spellings when unsure.**

**`RewardResponseData.type` uses the client's vocabulary and there is no `"Item"`.**
`ResourceInventoryItem.GetByRewardTypeAndID` matches a fixed literal set
(`InventoryItem`/`Key`/`UnitSoulItem`/`CardSoul`/`Gold`/…). An unmatched type silently renders
the wrong icon and a garbage count (the "Reward Chest x999" bug). Translation happens at
exactly one boundary - `_wire_rewards()` inside `_reward_list_data()`. Also:
`<Reward Type="Key" ID=…>` is a **ShopItem** id whose `<KeyItem>` is the real inventory row -
resolve via `missions.key_item_for()`, never grant the id directly.

**`semiSeason` IndexOutOfRange = the 30/31 lobby hang.**
`PvPInfoResponseModel.GetCurrentSeasonUntilAt` does `seasonUntilAtDates[semiSeason-1]`. Fix is
server-side: `semiSeason >= 1` and `seasonUntilAtDates`/`nextSeasonStartAtDates` with 2+
elements. Same trap in `PlayerColosseumInfoResponseModel` (needs `semiSeason >= 2`).

**Stale `tomorrow` = a 1 Hz re-login storm.** Derive it, never store it.

**Lost updates need more than a transaction.** Handlers do load → mutate dict → save as
separate steps, so a per-save transaction still loses the other process's write. An HTTP
middleware in **both** `server.py` and `dashboard.py` holds `playerdb.write_lock()` (flock,
cross-process) for the whole request. The `asyncio.Lock` is taken **first** - flock blocks the
thread, so a second request in the same process would otherwise freeze the event loop while
the holder awaits.
The dashboard's create-player call **must not** hold the flock: it delegates over HTTP to
`server.py`, which takes the same lock, and holding it across the proxy call deadlocks both
sides. `_DELEGATED` in `dashboard.py` exempts it.

**Two uvicorn processes wrote the same JSON file under a `threading.Lock`** - which locks
nothing across processes. That is what silently reset a 96-item accessory list. Hence SQLite.
**Never read `players.db` directly; always go through `playerdb.py`.**

### 5d. Security

**Loopback is not a boundary behind a proxy.** Behind a Cloudflare Tunnel or any reverse
proxy, *every* request arrives from loopback. The admin guard is a three-rung ladder
(`KGC_ADMIN_TOKEN` → admin account + session → loopback-only), and the loopback rung is last
and weakest for exactly this reason. This was once a live hole: `serve_public.sh` was relaxed
to accept an account instead of a token, which left the game port's guard with nothing to
check and everything to allow.

**`load_state()` must not fall back to the active player in multiplayer mode.** It used to.
That meant anyone who could reach the port read and wrote whichever save the dashboard had
last selected, **with no token at all** - found 2026-07-31 by probing from a non-loopback
peer: `POST /player/rename` with a garbage token renamed the active player's castle. Fixed;
`admin_api.active_state()` reads `playerdb.active()` directly so the dashboard still works.
Regression test: `tests/test_public_hardening.py`.

**When you change a security invariant, the old tests keep asserting the hole.**
`test_identity_routing.py` literally asserted `"no session must fall back to active"` - it was
encoding the vulnerability as the spec, so it went red on the *fix* and looked like the fix was
wrong. `state.py`'s own self-check had the same stale assumption and was only caught later.
After any invariant change, grep the tests for the **old** behaviour before you trust a red
suite. A failing test is not automatically a broken change.

**`preflight.py` reads config; it does not attack.** It said "ready to expose" while both of
the above were live. **Probe a running instance from a non-loopback peer** before you believe
any readiness claim.

**`TestClient`'s default peer is the literal string `"testclient"`**, which is not loopback -
so an admin-guard test silently passes for the wrong reason. Always pass
`client=("127.0.0.1", 50000)`.

**Account ids are bearer credentials.** They are logged as an 8-char fingerprint, never
verbatim, because `admin_log` feeds the dashboard's log view.

**`KGC_MULTIPLAYER` gates auto-creating a save for an unknown account id.** In single-player
mode, binding an account to the *active* save pins every account that ever logged in to it,
permanently. That happened; the poisoned rows survived the mode switch and had to be deleted
by hand.

### 5e. Tooling / process

**`git filter-repo` rewrites stashes and drops their untracked component.** 116 files were
stashed, filter-repo rewrote history, and 27 new untracked files vanished from disk. They were
recovered by docstring-prefix matching against unreachable blobs. **Commit before any history
rewrite. A stash is not a backup.**

**`.gitignore` directory exclusion makes negations unreachable.** `il2cpp/*` excludes the
*directories*, so git never descends into them and `!il2cpp/*/libil2cpp_v*_ssl.so` can never
match. You need the four-line form:
```gitignore
il2cpp/*
!il2cpp/*/
il2cpp/*/*
!il2cpp/*/libil2cpp_v*_ssl.so
```

**`git checkout <file>` on a heavily-modified working file.** Reverted a modularized
`server.py` back to the 4701-line monolith. Check what a checkout discards before running it.

**`KGC_BACKUP_HOURS` was staging real player saves into git.** `server/state/backups/` is now
ignored. Watch for this whenever you add a new on-disk artefact.

**`adb reverse` is per-connection.** After the emulator restarts, run `./run.sh device` or
nothing reaches the server and it looks like a server bug.

**Clear the global proxy on every fresh redroid:** `adb shell settings put global http_proxy :0`.
A leftover proxy makes every request vanish.

---

## 6. Techniques worth keeping

These are the tricks that took the longest to find and are the most reusable.

### 6a. Recovering an il2cpp string literal with no stringliteral dump

An `adrp`+`ldr` pair loads a `.data` slot whose `R_AARCH64_RELATIVE` **addend** is the
literal-slot address. Parse `.rela.dyn`, then map through Il2CppDumper `script.json`
`ScriptString`. This is how `/player/rename`'s real URL was confirmed when the model mapping
was untrustworthy.

Il2CppDumper runs headless:
```bash
dotnet ~/.local/share/rg-toolkit/tools/Il2CppDumper/Il2CppDumper.dll <so> <global-metadata.dat> <outdir>
```
It crashes on the trailing "press any key" - the output is already written by then. Ignore it.

### 6b. Finding a decoder with no xrefs

Ghidra's xref graph is useless inside a packer. **Raw-scan for `BL`/`B` instruction encodings**
targeting the address range you care about, instead of trusting the decompiler's call graph.
That is how the NEO decoder was located.

### 6c. Re-deriving patch offsets after a version bump

Every RVA shifts on a version bump. Do **not** reuse offsets blindly.

Run Il2CppDumper against **that version's own** `libil2cpp.so` + `global-metadata.dat`. Each
method's `Offset` field = `RVA - 0x4000`, which empirically equals `patch_apk()`'s raw
file-offset convention. Then **verify by prologue bytes**: when v170.0.03 → v170.1.00 was
re-derived, all 14 prologue byte sequences came back byte-identical; only the offsets moved.
If a prologue does *not* match, you have the wrong method - stop and re-resolve.

Resolve crash-frame RVAs via `script.json` `ScriptMethod[].Address`, **not** `dump.cs`.

ARM64 patch constants:
```
RET_TRUE   20008052 c0035fd6    # mov w0,#1 ; ret
RET_FALSE  e0031f2a c0035fd6    # mov x0,#0 ; ret
RET        c0035fd6
NOP        1f2003d5
```

### 6d. Hooking C# from native code

Two techniques, and picking the wrong one gives you a silent no-op:

- **methodPointer swap** - works only for engine-invoked messages (`BattleManager.Update`).
- **inline detour** (`install_inline_hook`) - required for direct C#→C# calls
  (`PostListItem.Set`).

`mprotect` before any methodPointer swap. Never hardcode arm32 offsets into the arm64 stub.
Verify with `adb logcat -s XignCodeStub` - you must see one `Hooked …` line per hook, or they
silently did nothing.

The live stub is `server/jni/stub.cpp`, **not** the legacy no-op `xigncode_stub/xigncode_stub.c`.
Build: `ndk-build` in `server/`, then
`cp libs/arm64-v8a/libxigncode.so xigncode_stub/arm64/`.

### 6e. Custom mail text without a CDN rebuild

`PostData.title`/`text` are **localization keys**, not literals - an unresolved key renders as
"You got a gift". To send real text: prefix with `@raw:` server-side (`_process_posts()`), and
the native `PostListItem.Set` hook strips the prefix and writes via `set_text`. No Strings
rebuild, no client re-download.

### 6f. Data-only "translation" via key redirect

`Skill`/`ActiveSkill` entries support explicit `<Name>`/`<Desc>`/`<LongDesc>`/`<ShortDesc>`
tags (and `Unit` supports `<SubName>`) that redirect the Localizer lookup to **any** existing
key. Without the tag, the game auto-derives it from the entry's own id (`"SkillName_" + id`).
So `<Name>SkillName_10790</Name>` on a different skill borrows Ophelia's already-translated
text. This is how content the devs shipped but never localized gets readable names with no
Strings edit at all.

### 6g. Reading a stat key

**Never infer a stat's meaning from its key name.** `BaseDefPen` is **Menace** (Uy hiếp) and
`BaseDefDen` is **Guard** (Hộ vệ) - not armour penetration/reduction. Resolve through
`gamedata.stat_label()`, which reads `Strings_*.xml`. Misreading these puts a support stat on a
crit DPS set and leaves the Menace/Guard synergy sets scaling nothing.

---

## 7. Load-bearing / do not touch casually

| Thing | Why it is fragile |
|---|---|
| `il2cpp/v171.*/libil2cpp_v*_ssl.so` | Plain lib + **exactly 3** SSL patches at raw offsets. It rotted once and faked an engine bug. Keep pristine; regenerate with `patchers/make_v171_ssl_so.py`. |
| `server/real_cdn/xml.bak` | The pristine CDN bundle (md5 `779193a15d1377a7b8c2e6edfbe94095`). Restore from here, never re-clone. |
| `OVERRIDES` construction order in `server.py` | Must be built **last**, after every `handlers()` merge. There is an assert. Do not move it. |
| `config.RCFG` | Mutated in place, never rebound - every module holds its own reference. |
| The flock middleware | Ordering (`asyncio.Lock` then flock) is load-bearing. `_DELEGATED` exemption prevents a deadlock. |
| `local_mods/` | The only edits that survive a master-data refresh. All must stay idempotent. |
| `patch_genesis.py` / packer SONAME matching | Content-based matching. Reverting to filename matching resurrects a whole class of phantom bugs. |

---

## 8. Every environment knob

| Var | Default | What it does |
|---|---|---|
| `KGC_MULTIPLAYER` | `1` | Per-account saves. `0` = everyone shares the active save. |
| `KGC_MAX_PLAYERS` | `200` | Caps auto-created saves (`/auth/register` is unauthenticated). |
| `KGC_ADOPT_LONE_SAVE` | off | One-shot single→multi migration. Indistinguishable from a hijack once done. |
| `KGC_ADMIN_TOKEN` | unset | Top rung of the admin ladder. **Set this when exposing publicly.** |
| `KGC_TRUST_PROXY` | off | Read `cf-connecting-ip`/`x-forwarded-for`. **Required behind a tunnel**, or all per-IP limits share one bucket. Opt-in because a directly-reachable port lets anyone forge it. |
| `KGC_RATE_LIMIT` / `KGC_RATE_WINDOW` | 600 / 60s | Per-IP request cap. `/patch/` exempt. |
| `KGC_NEW_PLAYER_PER_IP` / `_WINDOW` | 5 / 3600s | Registration rate limit. |
| `KGC_MAX_BODY` | 1 MB | Enforced on declared *and* chunked bodies. |
| `KGC_BACKUP_HOURS` | 24 | In-process; due-check under the cross-process lock so both uvicorns don't fire. |
| `KGC_QUIET` | off | Stop echoing one line per request. Dashboard buffer still fills. |
| `KGC_CONTENT_GATE` | derived | Override the `serverVersion`-derived gate. **Required if you deploy the v170 client** (pin `170100`). |
| `KGC_APK_SRC` | `xapk_extracted_v171` | Which extracted XAPK to build from. `xapk_extracted_v1711` = v171.1.00. `WORK` follows it, so builds don't collide. |
| `KGC_FORCE_V17100` | off | Fall back to the v171.0.00 lib + metadata swap. |
| `KGC_APPLY_LDR` | **off** | The 65 `ldr→mov` patches. **They cause the black lobby. Leave off.** |
| `KGC_LOBBY_DIAG` | off | NOP null-checks in `Scene_Lobby.Init` to turn a managed NRE into a locatable SIGSEGV. |
| `KGC_ASSETBYPASS` | - | **Never set.** Breaks Strings and the UI. |
| `SHARE_HOST` | - | Host baked into the APK (`patch_hosts.py`). ≤26 chars, bare host. |
| `ADB_SERIAL` | `localhost:5556` | Target device. |
| `GLOGIN_DEV` | off | Google-login web bridge without real credentials. |

---

## 9. Known debt and open items

Deliberate shortcuts, all marked `ponytail:` in source. Run `grep -rn "ponytail:" server/` for
the live list. The ones with a real ceiling:

- `playerdb.py:77` - fresh SQLite connection per call, no pool. Sub-ms at this request rate.
- `playerdb.py:585` - **one global write lock**, not per-uid. Fine for a handful of req/s.
  Upgrade path: per-account locks, if throughput ever matters.
- `roster.py:11` - every cross-player call JSON-parses **every** player row. Fine at
  `MAX_PLAYERS=200`; O(n) per ranking request. This is the first thing to bite at scale.
- `state.py:111` - registration rate limit is an in-process sliding window, so each uvicorn
  gets its own allowance and a restart forgets. Move the counter into the DB if this ever
  fronts real traffic.
- `google_login.py:62` - skips re-verifying the JWT signature. That trust holds **only**
  because we fetched the token ourselves over TLS. If the fetch path ever changes, this
  becomes a hole.
- `google_login.py:160` - one global login slot, no per-device keying. Two people logging in
  simultaneously will collide.
- `server.py:2296` - fixed-window rate limit, no burst smoothing.

Other open items:

- **GPGS native Google login cannot work on a repacked build** - it needs the Play Console
  signing certificate. The web bridge (`GLOGIN_DEV=1`) and transfer codes are the working
  cross-device paths. Do not spend time on the native button.
- **Frida does not run on redroid** (`ndk_translation` blocks both server-inject and gadget).
  Use the native il2cpp poller in the XIGNCODE stub instead, or a real ARM device.
- **redroid Choreographer crash at ~70 s** - a destroyed-mutex FORTIFY abort via
  `ndk_translation`. Emulator defect, not ours; will not happen on real devices. Don't chase it.
- **v170 fallback path** (`rebuild_arm64.py`) still exists but is not exercised. If you run it,
  pin `KGC_CONTENT_GATE=170100` or v171-gated content gets sent to a v170 client.
- **git remote is not configured** (removed by the history rewrite). To publish:
  ```bash
  git remote add origin <url>
  git push --force origin main     # every commit hash changed
  ```
  GitHub keeps the old commits as unreachable for a while; a support-requested GC or
  delete-and-recreate is needed to purge them fully.
- **Uncommitted working tree.** ~87 modified/untracked files are staged for the next commit,
  including the recovered modules and the v171.1.00 unpacker.

---

## 10. Cookbook - "I need to…"

| Task | Do this |
|---|---|
| Give a player 1M gold | Dashboard → Players → field editor. Or `docs/save-editing.md`. |
| Send an item to everyone | Dashboard → Mail → broadcast, catalog reward picker. |
| Make a hidden unit visible | `docs/content-unlock.md` - it is a `MinVersion` gate, plane 3. |
| Add a training-dummy stage | `docs/stages-and-spawns.md`. Stage id = `theme*100 + stage`. |
| Change what a route returns | Edit `data/*.json` first; only touch a handler if the data can't express it. |
| Add a new route | Put it in the right module's `handlers()`. Confirm it lands in `OVERRIDES`, then run `api_audit.py`. |
| Debug "the panel is empty" | `python3 api_audit.py --route /the/path`. It checks the four dead-route classes. |
| Debug "the client crashed" | `adb logcat` → find the RVA → resolve via `script.json` `ScriptMethod[].Address` → add an NRE stub. |
| Ship a build to a friend | `SHARE_HOST=<host> python3 server/rebuild_arm64_mod.py --share` → `SHARE.md`. |
| Expose the server publicly | `docs/public-hosting.md`. Set `KGC_ADMIN_TOKEN` **and** `KGC_TRUST_PROXY=1`. Run `preflight.py`, then **probe it from off-box**. |
| Find where something is defined | CodeGraph MCP (`codegraph_search` / `codegraph_context`). It is a full AST index - do not grep first. |

---

## 11. Handover checklist for whoever is next

- [ ] Run everything in §1. Baseline green.
- [ ] Read §2 (four planes) and §5 (traps). Those two sections are 80% of the value here.
- [ ] Run `scripts/check_cdn_update.sh` and confirm you understand all three outcomes.
- [ ] Build a client once, end to end, and play for 10 minutes.
- [ ] Configure the git remote and push (§9).
- [ ] Skim `AGENTS.md` §"ARM64 Patch Inventory" so the offset tables aren't a surprise later.
- [ ] Confirm `~/.android/debug.keystore` exists (pass `android`) - the build signs with it.
- [ ] `redroid-data/` is root-owned (Docker volume). Direct access needs sudo; run those
      commands yourself rather than scripting them.

Good luck. The two things most likely to bite you first are the **republish trap** (§4a) and
the **wrong-plane edit** (§2). Everything else is written down.
