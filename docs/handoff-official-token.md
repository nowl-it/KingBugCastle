# Handoff: obtain a live official-server `accesstoken` for KGC (King God Castle)

> This is a self-contained brief for a fresh agent. It records what has been **proved**, what has
> been **tried and failed**, and the two remaining paths. Read `docs/dev-notes.md` §33–§35 for the
> full evidence; this file is the distilled brief.

## Goal

`api/find_player.py` must query the **official** KGC backend (`https://kgc-k8s-1.awesomepiece.com`)
to look up a player by name (`잠이- 졸려`), then by Account ID. Profile/ranking data must come from
production, not from our private server.

## Hard constraints

- Respond in **Vietnamese**.
- **Never use the shell `timeout` command** — let scripts run to completion; prefer background runs.
- No phone-passcode / device-interaction commands unless the user has explicitly sanctioned it.
- **Production request budget is ~290 and shrinking.** Every `prod_probe.py` run without
  `--player` silently costs **3** requests (format matrix on `/auth/getPatchFolder`). Print the
  intended mode and count requests before running.
- The repo has many unrelated user changes — **commit narrowly**.
- The iPhone `00008101-000125E62122001E` ("NOwL", iOS 26.7.1, `PasswordProtected=False`, game
  174.0.00) is on USB. Keep the screen unlocked during any backup.

## What is PROVED (do not re-derive)

1. **Request format is correct.** `api/config.py` was fixed: AES-128-ECB key `a6072ad6b9c959ff`,
   lowercase-hex zero-padded body, `version: 174.0.00` header (**set via `KGC_VERSION=174.0.00`
   env, do not edit the default**), `platform`, `time`. `GET /auth/getPatchFolder` answers
   `HTTP 200 {"code":200,"patchFolder":"LIVE/2026_10_06_xGrY0WbLgR"}`. Header shape is *not*
   the reason tokens fail — the same dead token returns `401` under both shapes.
2. **The token in the iOS plist is genuine.** `accessToken` is itself 3DES-encrypted with
   `MD5("APPROJECTL2")`; decryption yields the 32-char token. Only `HandleAuthResponse`
   (RVA `0x364452C`) writes prefs, and it is called from `Auth` **and** `ReAuth`, so the plist
   holds the token the client uses. Prod verdicts:
   - `200` = live
   - `402 ExpiredToken` = **server-issued, just expired** (token is real)
   - `401 NotCertifiedToken` = server does not recognise it
   - `401 WrongTokenError` = no token at all; garbage → `401 NotCertifiedToken`
3. **Why the game never logs out** (this was the central question):
   `Scene_Game.UpdateImpl` → `RestAPI.ShakeHand()` (RVA `0x2D2EE9C`, single caller in the binary
   at call site `0x2E73388`) → `GET /auth/shake-hand`. The game pings from its main gameplay
   loop, so the server slides the session window continuously.
4. **The whole cookie chain is mapped** (see §34): `AppSignManager.GetCookie` (`0x361FC5C`) → JNI
   `com.wellbia.xigncode.AppSignClientSystem.getCookie2` → `libxigncode.so` (a 24-export JNI shim)
   → atomic slot `System+0x30` = `dlsym(handle, "ZCWAVE_SendCommand")`, where the symbol name is
   built on the stack with a **double XOR that cancels**, so the plaintext is simply the mask bytes
   → `ZCWAVE_SendCommand(cmd=0x20)` → `ZCWAVE_SendCommandVa` jump table → a registered handler.

## What has been TRIED and FAILED

| Attempt | Result |
|---|---|
| House Arrest / AFC into the game container | `InstallationLookupFailed` — no file-sharing shortcut |
| Incremental MobileBackup2 (`KGC_BACKUP_COMPLETE=1`) | device error **205 "Manifest references files not in backup"** because our instrumented upload discards files |
| A run that *prints* `Starting INCREMENTAL stream backup` | device **still streams everything**, still 115 s — it never committed a snapshot |
| Stock unfiltered `Mobilebackup2Service` backup (one-time bootstrap) | started 01:09, died `ConnectionTerminatedError` at 01:14; **not retried** |
| Timed relaunch during capture (several windows) | `402` (too old) or `401` (login not yet certified) |
| `POST /auth/login`, `/auth`, `/auth/auth`, `/auth/xcd` minting the token directly | all gated by the XIGNCODE cookie — cannot be minted outside the genuine client |
| Passive MITM harvester (2026-08-24) | not reproducible — cert pinning |

## The core tension

`tools/capture_and_probe.py` reads the game plist **~119 s** into the backup stream (the game's
container sits near the end; ~9000 files at ~75 files/s). The token lives **~100 s**. So capture is
inherently slower than the token.

**Timing model that fits all six runs:** after force-quit + relaunch, an *early* (uncertified)
token lands in the plist within seconds, the **certified** one lands ~**90 s** after relaunch, and
it then lives ~100 s.

- relaunch **before** capture → read at T+119 → age ~150 s → `402`
- relaunch at T+55 → certified write would be ~T+145, read at T+118 → reads the early
  uncertified token → `401`
- **untested sweet spot: relaunch exactly at T=0** → certified ~T+90 → read T+119 → age ~29 s →
  should be `200`

## The two remaining paths

### Path A — make capture fast, then use the T=0 window

1. Retry the **stock, unfiltered** backup so the device finally commits incremental state:
   ```python
   async with Mobilebackup2Service(ld) as mb:
       await mb.backup(full=True, backup_directory=str(BACKUP))
   ```
   Note `__init__` takes **no** `backup_directory` — pass it to `backup()`. Keep the phone unlocked;
   expect 15–30 min and a few GB (63 GB free).
2. Then run the chained
   `capture_and_probe.py && KGC_VERSION=174.0.00 python3 api/find_player.py --name "잠이- 졸려"`
   and have the user force-quit + reopen the game **exactly when the capture starts**.
3. If captures drop to a few seconds, the TTL race disappears entirely.

### Path B — compute the cookie locally and mint on demand (the real prize)

Port `ZCWAVE_SendCommand(cmd=0x20)` to Python. Then
`GET /auth/xcdSeed?version=174.0.00` → build cookie → `GET /auth/xcd?cookie=…` → `accessToken`,
in milliseconds, no backup stream, no race.

Status: the call-chain is fully mapped (§34) but the actual cookie body lives behind **yet another
function pointer** (`handler = *(u64*)0x44040` in `libraphael_barrier.so`), whose implementation
is inside the **packed 5.6 MB core** embedded in `libgabriel.so`.

Key facts for whoever continues:
- `apk/com.awesomepiece.castle@174.0.00.xapk` → `config.arm64_v8a.apk` → `lib/arm64-v8a/`.
- `libxigncode.so` = 559 KB JNI shim, 24 exports, `Java_..._GetCookie2` @ `0x1EB18` (cmd `0x20`),
  `GetCooke` @ `0x1E728` (cmd `0x1c`), `Cleanup` @ `0x1E524` (cmd `0x16`). Atomic slot
  `System+0x30`, ctx = `*(u64*)0x8C0B0` (.bss).
- Init function @ `0xFF04` does the double-XOR name decode and `dlsym`; `dlopen` handle comes from
  `System+8+0x924`.
- `libgabriel.so` (8.6 MB) is a **60-byte stub** that embeds three **uncompressed arm64 ELFs**:
  `0xDF620..0x120620` = `libraphael_barrier.so` (266 KB, `ZCWAVE_SendCommand` @ `0xD388`),
  `0x120620..0x6869C8` = the packed core (5.6 MB, **no dynsym**),
  `0x6BE620..0x848620` = `libsariel.so` (1.6 MB, `ZCWAVE_SendCommand` @ `0x22414`).
- `ZCWAVE_SendCommandVa` @ `0xD250`: `w8 = cmd - 0x15; if w8 > 0xf → default`; byte jump table at
  `0x301A0`, target = `0xD290 + table[w8]*4`; cmds `0x1c`/`0x20` → `0xD2D0` →
  `handler = *(u64*)0x44040; handler(cmd, ap)`.
- **Trap:** `.rela.plt` is *not* in PLT-slot order in these libs. Map by `r_offset` (GOT address),
  not by relocation index — otherwise `bl 0x87D0` reads as `usleep` when it is really
  `ZCWAVE_SendCommandVa` (GOT `0x43E20`).
- Reusable tools: `tools/xign_xref.py`, `tools/xign_bl.py`, `tools/xign_absrefs.py`.
- Open risk: the cookie may embed a device fingerprint set by `setUserInfo`/init, in which case a
  Python port will not validate. Verify early with one cheap `GET /auth/xcd`.

## Also still open

`api/find_player.py` only scans **top rankings** — even with a live token it reported
"not found in top rankings" (and skipped Strife because `/colosseum` also needs the token).
Either widen the sweep or obtain the Account ID directly.
