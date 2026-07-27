# Workflow — private server dev loop

For anyone (human or AI) editing `server/`. Read this before touching `server.py` or
`data/*.json`. For the god-account data-completion task specifically, see
`documentation/GOD_ACCOUNT_DATA_AGENT_PROMPT.md` (self-contained agent brief). For arm64
binary patches / RVA tables, see `AGENTS.md` at the repo root. For operator playbooks
(grant items/skins/treasures, un-gate content, build a dummy stage, push a CDN bundle,
crypto API), see **[`../docs/`](../docs/README.md)**.

## Where does my change go?

| You're changing... | Edit this |
|---|---|
| A response value with no per-request logic (a constant, an empty list, a fixed struct) | `data/static_overrides.json` — add the route key, no code change |
| A constant used by a response that DOES have per-request logic (dates, `st.get()` fallback, formulas) | `data/response_config.json`, referenced from the existing handler in `server.py` |
| A template field for artifact/accessory/treasure/rift-weapon/rift-crystal | `data/item_templates.json` |
| Player identity/currency/card-template/deck seed defaults | `data/default_player.json` |
| New route logic (state mutation, computed values) | `server.py` — add to `DYNAMIC_OVERRIDES` |
| A binary patch to the client `.so` | `rebuild_arm64.py` (arm64, the live target) |
| A client-side UI behavior / il2cpp method hook (custom mail text, in-battle stat poller) | `jni/stub.cpp` — `ndk-build` in `server/`, then `cp libs/arm64-v8a/libxigncode.so xigncode_stub/arm64/` and rerun `rebuild_arm64.py`/`rebuild_arm64_mod.py`. Pick the right hook technique (methodPointer swap vs inline detour) — see `AGENTS.md` "il2cpp hook techniques" |
| The build/patch/sign/install pipeline itself | `rebuild_arm64.py` (replaces the real app) or `rebuild_arm64_mod.py` (side-by-side King Bug Castle) |

Rule of thumb: if the value doesn't change based on `st`/`body`, it's data — put it in
`data/`, not in a Python literal. See `git log` for the 2026-07-02 refactor that moved
~50 routes' worth of hardcoded literals into `data/*.json` for this exact reason (the
whole point was "should be trivial to read/change without touching code").

## The edit-test-deploy loop

1. Edit `server.py` and/or `data/*.json`.
2. **Syntax-check before restarting** (catches typos before wasting a device-test cycle):
   ```bash
   python3 -c "import ast; ast.parse(open('server.py').read()); print('ok')"
   ```
3. Restart the server (no `--reload` — module-level globals like `DEFAULT_ARTIFACTS` are
   built once at import time from `data/*.json`, so a stale process serves stale data):
   ```bash
   pkill -f "uvicorn server:app"; sleep 1
   nohup uvicorn server:app --host 0.0.0.0 --port 8080 > /tmp/kgc_server.log 2>&1 &
   disown; sleep 2; ss -tlnp | grep 8080   # MUST show a listener before continuing
   tail -20 /tmp/kgc_server.log             # check for import-time exceptions
   ```
   The combined pkill+restart often reports a spurious "Exit code 144" from the `pkill`
   half even when the restart itself succeeds — don't trust the exit code, check
   `ss -tlnp` and retry the `nohup` line alone if nothing is listening.

   The device talks HTTPS, so a **second uvicorn on :8443** must also run (the standalone
   `tls_proxy.py` is gone — it's just uvicorn with TLS):
   ```bash
   nohup uvicorn server:app --host 0.0.0.0 --port 8443 \
     --ssl-keyfile key.pem --ssl-certfile cert.pem > /tmp/kgc_tls.log 2>&1 &
   ```
   Both are the same app; restart both after a code/data edit. Device wiring:
   `adb reverse tcp:80 tcp:8080; adb reverse tcp:443 tcp:8443`.
4. If you touched anything artifact-related, run the regression check (184 artifacts,
   4 tiers, catches the `targets.Count == opt_count` invariant regressing):
   ```bash
   python3 tests/test_artifact.py
   ```
5. Clear logcat, relaunch the app, **ask the user to tap through the screen you changed**
   — never `adb input tap` for interactive flows, the user does this themselves:
   ```bash
   adb -s 127.0.0.1:5555 logcat -c
   adb -s 127.0.0.1:5555 shell am force-stop com.awesomepiece.castle
   sleep 1
   adb -s 127.0.0.1:5555 shell am start -n com.awesomepiece.castle/.MainActivity
   ```
6. After the user confirms they've tapped through, check for crashes:
   ```bash
   adb -s 127.0.0.1:5555 logcat -d | grep -iE "AndroidRuntime|Unity.*Exception|FATAL"
   ```
   Empty output = no crash. If something appears, get the full stack:
   `adb -s 127.0.0.1:5555 logcat -d -v time | grep -A20 "<timestamp from the crash line>"`.
7. One crash at a time. Fix, restart, retest — don't batch multiple unverified guesses
   into one test cycle, you won't know which one worked or introduced a new regression.

## Rules (violating these has caused real crashes — see `AGENTS.md` and
`documentation/GOD_ACCOUNT_DATA_AGENT_PROMPT.md` for the full incident write-ups)

- **Never guess a response shape or a value constraint.** Shape comes from
  `il2cpp/v170.0.03/dump.cs` (grep the `*ResponseModel` class). Value constraints (array
  length, valid id range, enum bounds) come from Ghidra-decompiling the client method
  that consumes it. A shape that merely "looks reasonable" is how every crash in this
  project started.
- **AES padding is space-pad, not PKCS7.** Newtonsoft on the client throws
  `JsonReaderException: Additional text after JSON` on non-whitespace trailing bytes but
  tolerates trailing spaces. `aes_encrypt()` in `server.py` already does this — don't
  change it to PKCS7.
- **Some request bodies arrive hex-encoded** (ASCII hex text of the ciphertext, not raw
  binary) — `aes_decrypt()` already detects and unwraps this. If you add a new decrypt
  path, copy the detection, don't assume raw binary.
- **Direct `@app.get/post` routes must be registered BEFORE the `for _r in ROUTE_MODELS`
  loop** to win — FastAPI/Starlette matches routes in registration order, first match
  wins. A route added to `OVERRIDES`/`DYNAMIC_OVERRIDES` for a path that ALSO has a direct
  handler is dead code for that path (it's still reachable via other paths mapped to the
  same function, so isn't always safe to delete — check before assuming).
- **`redroid` here blocks Frida** from hooking `libil2cpp.so` (ndk_translation on x86_64
  host hides the translated library from module enumeration). Don't spend time trying to
  attach Frida for runtime C# inspection in this environment — it has already been tried
  and confirmed blocked. Static Ghidra + live logcat/screenshot iteration only.
- **The user taps the device screen themselves** for anything interactive (login, panel
  navigation, artifact selection). Don't use `adb input tap` to simulate this — ask and
  wait for the user's report.
- **Restart the server after every `data/*.json` edit too**, not just `server.py` — the
  JSON is read once at import time into module-level globals (`RCFG`, `STATIC_OVERRIDES`,
  `ITEM_TEMPLATES`, `DEFAULT_ARTIFACTS`, etc.), so a running process won't pick up file
  changes.
- **`state/player.json` is live save data, not a template.** Deleting it regenerates from
  `DEFAULT_PLAYER` (built from `data/default_player.json` + XML-derived id lists) on next
  boot — don't hand-edit it expecting the change to survive a state-mutating request, and
  don't treat edits to `data/default_player.json` as retroactively applying to an existing
  save.

## Sanity-check commands

```bash
# Confirm the server module imports cleanly and route/data counts look right
python3 -c "import server; print('routes:', len(server.OVERRIDES)); print('artifacts:', len(server.DEFAULT_ARTIFACTS))"

# Artifact invariant regression check (targets.Count == opt_count per tier)
python3 tests/test_artifact.py

# Health check against a running server
curl -s localhost:8080/ | python3 -m json.tool
```
