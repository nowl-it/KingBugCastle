# KGC private server (emulator)

Reverse-engineered private server for **King God Castle** (`com.awesomepiece.castle`),
reconstructed from the il2cpp dump of client `v170.0.03` (active client `v170.1.00`, arm64).
Goal: boot the real client against a server you control for offline testing /
mechanic experimentation.

> Research / interoperability use only. Server-authoritative game — this emulates
> the backend; it does not modify or distribute the client.

**Start here:**
- **[../SETUP.md](../SETUP.md)** — first-run: clone → `setup.py` → run your own server,
  on any OS, against redroid / BlueStacks / LDPlayer / a real phone.
- **[WORKFLOW.md](WORKFLOW.md)** — day-to-day edit/test/deploy loop, "which file do I
  edit" table, rules that have caused real crashes when violated.
- **[data/README.md](data/README.md)** — schema of the 4 JSON files under `data/`.
- **[../AGENTS.md](../AGENTS.md)** (repo root) — arm64 patch inventory + RVA map, kept
  current with every Ghidra-verified finding.
- **[../documentation/GOD_ACCOUNT_DATA_AGENT_PROMPT.md](../documentation/GOD_ACCOUNT_DATA_AGENT_PROMPT.md)**
  — self-contained brief for delegating the god-account data-completion task to a fresh
  agent; also doubles as the fullest incident write-up of crashes found so far.

## What it is

- `pipeline/extract_models.py` — parses `dump.cs` → `generated/models.json` (357 wire
  models, exact field names/types from `Awesomepiece.Model`) + `generated/restapi.json`
  (431 `RestAPI` methods → request/response model).
- `pipeline/map_routes.py` — maps the 284 REST route strings (from `stringliteral.json`) →
  RestAPI method → response model. Auth-critical paths are hand-pinned.
- `server.py` — FastAPI app. Registers all 284 routes + a catch-all. Every endpoint
  returns a **wire-valid** ResponseModel (`code:0` + all fields at typed defaults),
  which Newtonsoft on the client deserializes without crashing. Important screens
  (auth, player, currencies) are filled from `state/player.json`. Response data
  that isn't request-time logic lives under `data/*.json` (see below).

## Architecture discovered

Flow the client runs at boot (the login critical path):

```
POST /auth/shake-hand          handshake (returns code 0)
POST /auth/checkPatchVersion   {version} -> ok
GET  /auth/getPatchFolder      -> {patchFolder:"<date>"}  (addressables date dir, from response_config.json)
POST /auth/xcdSeed             XIGNCODE3 seed exchange (AuthResponseModel.seed)
POST /auth/register | /login   -> AuthResponseModel {accessToken, seed, serverTime, expiredAt, loginId}
GET  /player                   -> PlayerDataResponseModel (full profile)
GET  /player/currencies        -> {gold, cash, heart}
GET  /player/tutorial-status, /card/all, /deck, ...  (~280 more)
```

Backend hosts (all `awesomepiece.com` / GCP):

| Host | Role |
|---|---|
| `castle-infra-server-65408603887.asia-northeast3.run.app` | infra / patch (`INFRA_SERVER_URL`, hardcoded in `RestAPI`) |
| `axis-game.awesomepiece.com` | main game REST API (the 284 routes) |
| `kgc-k8s-1.awesomepiece.com` | game k8s cluster |
| `isekai-lobbyserver.awesomepiece.com` | lobby / realtime (arena, colosseum) |
| `kgc-cdn-1.awesomepiece.com` | addressables CDN (you already mirror this) |

Transport = HTTPS + JSON (Newtonsoft). Auth = `accessToken` (bearer/cookie).
Anti-cheat = **XIGNCODE3** (Wellbia) — client-side; server only exchanges a seed,
so a stub seed is enough for the API. SSL pinning present (`CertificateHandler`,
2 `pinning` refs) → must be bypassed to MITM.

## Prerequisites / Setup

To clone and run this project from scratch, you need:

1. **System Tools**: Install `apktool`, `apksigner`, and `adb`.
   - Ubuntu/Debian: `sudo apt install apktool apksigner adb`
   - MacOS: `brew install apktool apksigner android-platform-tools`
2. **Python Environment**: Install the required Python packages:
   ```bash
   cd server
   pip install -r requirements.txt
   ```
3. **Original APKs**: You must obtain the original game files (v170.0.03 or v170.1.00) before you can patch and deploy:
   - Download the original XAPK (e.g., from APKPure).
   - Rename the `.xapk` extension to `.zip` and extract it.
   - Place `base.apk`, `split_config.apk`, and `split_base_assets.apk` into the `apk/` folder at the root of the project (create the folder if it doesn't exist).

## Run

```bash
cd server
python3 -m uvicorn server:app --host 0.0.0.0 --port 8080
curl localhost:8080/                 # health
curl -X POST localhost:8080/auth/login -d '{"token":"x"}'
```

Edit `state/player.json` to set currencies/level/etc. For a pure-literal response,
add it to `data/static_overrides.json` (no code change needed). For a response with
per-request logic (dates, state reads), add a builder to `DYNAMIC_OVERRIDES` in
`server.py` and keep its constant values in `data/response_config.json`.

## Point the client at it

You must do BOTH: route the hosts to your machine, AND defeat TLS so the client
trusts your cert.

### A. Redirect hosts (pick one)

1. **DNS / hosts** — on the device/emulator, map the API hosts to your server IP:
   ```
   <YOUR_IP>  axis-game.awesomepiece.com
   <YOUR_IP>  kgc-k8s-1.awesomepiece.com
   <YOUR_IP>  isekai-lobbyserver.awesomepiece.com
   <YOUR_IP>  castle-infra-server-65408603887.asia-northeast3.run.app
   ```
   Leave `kgc-cdn-1` pointing at your addressables mirror (or the real CDN).

2. **mitmproxy reverse/transparent** — run `mitmproxy` and reverse the above hosts to
   `localhost:8080`. Easiest for capturing real traffic to refine responses.

3. **Binary patch** — `INFRA_SERVER_URL` is a hardcoded string literal in `libil2cpp.so`
   (and the other hosts in global-metadata). Patch the string in place (same byte
   length, e.g. `http://10.0.0.5:8080/........` padded) to skip DNS entirely. Most
   robust on rooted devices.

### B. Defeat TLS pinning (required)

The client validates the server cert (`CertificateHandler` / `ServerCertificateValidation`).
Options, easiest first:
- **Frida** with a universal SSL-unpinning + `UnityWebRequest.CertificateHandler` bypass
  script. Hook the cert validation to always return true.
- **Plain HTTP** if you binary-patch `https://` → `http://` in the host strings (B avoided).
- Install your mitmproxy CA as a system cert (Android 14+ needs root / Magisk module).

### C. XIGNCODE3

Client-side anti-cheat. For local API testing it only needs the seed handshake
(`/auth/xcdSeed`, `/auth/xcd`) which the emulator answers. If the client hard-fails
when the XIGNCODE module can't reach Wellbia servers, neuter it with Frida (hook the
xigncode init to no-op) or patch it out of the APK.

## Refining responses (the iterative loop)

Most endpoints return empty-but-valid objects. To make a specific screen work:
1. Run mitmproxy against the **real** server once, hit that screen, capture the JSON.
2. Drop the captured body into an `OVERRIDES` builder (or a static fixture file).
3. Restart — the client now sees real-shaped data from your server.

Field names/types are already known (`generated/models.json`) so you only supply values.

## redroid test box

redroid must run with **`androidboot.redroid_gpu_mode=guest`** (swiftshader software render).
With `gpu_mode=host` the vsync/Choreographer passthrough is broken (white screen + a
destroyed-mutex crash). swiftshader is slower but renders correctly and is stable.

## Files

```
server/
  server.py              FastAPI emulator (run this)
  deploy.sh              full pipeline: patch+sign+install+start (arm32 target)
  rebuild_arm64.py       arm64 client rebuild (SSL+NRE stubs, sign, install)
  rebuild_arm64_mod.py   side-by-side variant (com.nowl.castle); --share bakes a
                          server host + packages KingBugCastle.xapk (see ../SHARE.md)
  serve_public.sh        run the server bound 0.0.0.0 (HTTP :8080 + TLS :8443) for
                          remote players; Cloudflare-Tunnel / public-IP / LAN guidance
  rebuild_xml_bundle.py  CDN XML bundle patcher
  data/                  response data as JSON (static_overrides, response_config,
                          item_templates, default_player) - edit these, not code
  state/player.json      editable save (live source of truth after first boot)
  generated/             models.json, restapi.json, routes.txt, route_models.json
  pipeline/              dump.cs -> generated/*.json (run when dump.cs changes)
    extract_models.py
    map_routes.py
  patchers/              internal deps of deploy.sh (arm32 binary patches)
    patch_apk_inplace.py patch_metadata_http.py patch_prestrings.py patch_rename.py
  capture/               ground-truth capture tools (hit the real backend, dump JSON)
    dump_real_api.py mitm_fake_auth.py
  tests/                 assert-based sanity checks
    test_artifact.py
  dashboard.py           unified web dashboard server (:8081) - see below
  webui/                 the single web UI (Battle Tracker + Admin), static files
  real_cdn/              cloned CDN bundles served verbatim at /patch/{path}
  jni/                   stub.cpp -> libxigncode.so (ndk-build); native il2cpp
                          poller + UI hooks. Output copied to xigncode_stub/arm64/
  xigncode_stub/         libxigncode.so replacement: registers no-op XIGNCODE3 JNI
                          methods, then hooks il2cpp (GameUnit stat poller on
                          BattleManager.Update; custom-mail hook on PostListItem.Set)
```

## Web dashboard — `dashboard.py` + `webui/` (:8081)

One web UI + one server. Replaced the old split (a static `tracker_ui/`, its `log_tracker.py`
backend, and a dead Next.js `admin/` skeleton). Run it and open http://localhost:8081/:

```bash
cd server && python3 dashboard.py     # or: uvicorn dashboard:app --port 8081
```

Two tabs:
- **Battle Tracker** — live in-battle hero stats over WebSocket `/ws`. `dashboard.py` reads
  `adb -s $ADB_SERIAL logcat -s XignCodeStub`, parses the native poller's output (resolving
  buff/skill ids to names from `scratchpad/xml_live/Strings_*.xml`), and broadcasts hero updates.
- **Admin** — acts directly on the game state JSON (`state/players/*.json`, `state/player.json`),
  the same files `server.py` reads per request (edits apply on the client's next fetch, no
  restart): server status, per-player currency/level/name editor, and mail send/delete. Mail is
  appended to a player's `posts` array; `server.py` serves it (wrapping title/text with `@raw:`
  so the literal text renders, bypassing the Localizer). Mail can carry a **reward**: currencies,
  or any item from `GET /api/catalog` (Item/Unit/UnitSoul/Artifact/Treasure/Accessory, names from
  `Strings_EN_US`) via a searchable id picker - `server.py` `_grant_reward()` mutates state on claim
  (Item -> inventory incl. reward boxes; UnitSoul -> hero soul; Artifact/Treasure/Accessory are
  display-only, gift them as an Item reward box). REST under `/api/*`.

`ADB_SERIAL` env var overrides the device serial (default `localhost:5556`).

## Native stub (XIGNCODE replacement) — `jni/stub.cpp`

More than a no-op: after registering stub `ZCWAVE_*` JNI methods (so the client boots past the
anti-cheat), a worker thread dlopen's `libil2cpp.so` and installs hooks. Two hook techniques —
see `AGENTS.md` "il2cpp hook techniques":
- **methodPointer swap** — only intercepts Unity engine messages (e.g. `BattleManager.Update`, the
  in-battle GameUnit stat poller that feeds the `dashboard.py` Battle Tracker tab).
- **inline detour** (`install_inline_hook`) — needed for direct C#→C# calls like `PostListItem.Set`
  (custom Inbox mail title/text: server prefixes `@raw:`, the hook strips it and writes the literal
  via `set_text`, bypassing the Localizer — no CDN Strings rebuild needed).

Build: `ndk-build` in `server/`, then `cp libs/arm64-v8a/libxigncode.so xigncode_stub/arm64/` and
run `rebuild_arm64.py` / `rebuild_arm64_mod.py`.
