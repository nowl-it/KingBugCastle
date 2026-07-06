# KGC private server (emulator)

Reverse-engineered private server for **King God Castle** (`com.awesomepiece.castle`),
reconstructed from the il2cpp dump of client `v169.1.05` (compatible 170.0.0x).
Goal: boot the real client against a server you control for offline testing /
mechanic experimentation.

> Research / interoperability use only. Server-authoritative game — this emulates
> the backend; it does not modify or distribute the client.

**Start here:**
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
  rebuild_arm64_mod.py   side-by-side variant (com.nowl.castle)
  rebuild_xml_bundle.py  CDN XML bundle patcher
  make_share.sh          bundle patched client + server into a shareable zip
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
  admin/                 Next.js admin panel (pnpm install to set up)
  real_cdn/              cloned CDN bundles served verbatim at /patch/{path}
  xigncode_stub/         no-op libxigncode.so (disables XIGNCODE3 anti-tamper)
```
