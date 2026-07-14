# Setup - run your own KGC private server

Clone the repo, run one setup script, and you have your own King God Castle
private server that a modded client connects to. Works on **Linux, macOS, and
Windows**, against **redroid, BlueStacks, LDPlayer, or a real Android phone**.

> The server + build pipeline are pure Python plus a few Java/adb CLI tools.
> The native pieces (`libxigncode.so`, `libmain_wrapper.so`) ship **prebuilt**,
> so you do **not** need the Android NDK or SDK to build - just `apktool`,
> `apksigner`, `zipalign`, `adb`, and a JRE.

---

## 1. Prerequisites

| Tool | Linux | macOS | Windows |
|---|---|---|---|
| apktool, apksigner, zipalign, adb, JRE | `sudo apt install apktool apksigner zipalign adb default-jre` | `brew install apktool android-platform-tools openjdk` (+ SDK build-tools for zipalign/apksigner) | Android SDK **build-tools** (apksigner.bat, zipalign.exe) + **platform-tools** (adb) + apktool + a JRE, all on PATH |
| Python 3.9+ | preinstalled | preinstalled | python.org |

All five must be on your `PATH`. `python3 setup.py` checks them and prints what's missing.

## 2. Supply the game files

The game APK is **not** in this repo (copyright + 1 GB). Use the built-in
`kgc-cli` tool to download the correct **King God Castle v170.1.00, arm64** XAPK:

```bash
mkdir -p apk && ./kgc-cli download -v 170.1.00 -o apk/
```

> **Why `kgc-cli`?** APKs from third-party sites (APKPure, etc.) often strip
> `libil2cpp.so` (the IL2CPP runtime binary). `kgc-cli` downloads a complete
> XAPK with all native libraries included. If you use a manually-downloaded XAPK
> and the build fails with `libil2cpp.so not found`, re-download with `kgc-cli`.

## 3. Setup

Create a Python virtual environment (recommended — some distros block system-wide
`pip install` with `externally-managed-environment`):

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows
```

Then run setup and install dependencies:

```bash
python3 setup.py                       # checks tools, extracts XAPK, makes a debug key
pip install -r server/requirements.txt
```

## 4. Start the server

Two listeners: HTTP :8080 and TLS :8443 (the client talks HTTPS; the SSL-bypass
patch accepts the self-signed cert). `setup.py` generates `server/cert.pem` +
`server/key.pem` for you.

```bash
cd server
../.venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8080 &
../.venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem &
```

(On Windows, run the two commands in two terminals, or use `serve_public.sh` under WSL/Git-Bash.)

## 5. Build + install the client for YOUR device

Everything routes through **one baked host + adb**, so the same steps cover every
target. Two scenarios:

### A. Local testing - your device is adb-connected (recommended)

This works identically on redroid, BlueStacks, LDPlayer, and a USB-tethered real
phone. No root, no host-file edits, no privileged ports.

**Connect adb to your device/emulator:**

| Target | Connect | Typical serial |
|---|---|---|
| redroid (Linux/Docker) | `adb connect localhost:5556` | `localhost:5556` |
| BlueStacks | enable ADB in settings, `adb connect 127.0.0.1:5555` | `127.0.0.1:5555` |
| LDPlayer | `adb connect 127.0.0.1:5555` (or `:5554`/`:5557`) | `127.0.0.1:5555` |
| Real phone (USB) | enable USB debugging, plug in | `adb devices` shows it |

Confirm with `adb devices`. Then **bake `127.0.0.1` and install** (side-by-side app
`com.nowl.castle`, "King Bug Castle" - does not touch the real game):

```bash
ADB_SERIAL=<serial> .venv/bin/python server/rebuild_arm64_mod.py --host 127.0.0.1
```

**Route the device's :443 to your server's :8443** (no root needed):

```bash
adb -s <serial> reverse tcp:443 tcp:8443
adb -s <serial> reverse tcp:80  tcp:8080     # optional, CDN is https so usually not needed
```

Launch "King Bug Castle". The client hits `127.0.0.1:443` → adb-reverse → your
`:8443` server. Watch it connect:

```bash
tail -f /tmp/kgc_server.log         # or the uvicorn console
```

> `adb reverse` is per-connection - re-run it after replugging USB or restarting
> the emulator.

### B. Share to remote players (no adb)

For players who just download and play, you can't use adb reverse. You bake a
**public** server address into the XAPK and expose your server to the internet.
See **[SHARE.md](SHARE.md)** - it covers the host constraint (≤26 chars), Cloudflare
Tunnel / public-IP / LAN options, and produces `KingBugCastle.xapk`.

---

## Which app am I running?

`rebuild_arm64_mod.py` builds **King Bug Castle** (`com.nowl.castle`), installed
**alongside** the real game so nothing is overwritten. To replace the real app
instead, use `rebuild_arm64.py` (same patches, original package id).

## Rebuilding the native .so (rare - only after editing the C++)

The prebuilt `.so` ship in the repo. Only if you edit `server/jni/stub.cpp` or
`libmain_wrapper.cpp` do you need the NDK:

```bash
cd server && ndk-build && cp libs/arm64-v8a/libxigncode.so xigncode_stub/arm64/
KGC_REBUILD_NATIVE=1 ...   # forces libmain_wrapper.so recompile (auto-finds NDK via ANDROID_NDK_HOME)
```

## Path overrides (non-standard layouts)

The build auto-derives everything from the repo root. Override via env if needed:
`KGC_ROOT`, `KGC_XAPK` (extracted-splits dir), `KGC_WORK` (build scratch), `ADB_SERIAL`.

---

## Troubleshooting

### `libil2cpp.so not found` in config APK

The XAPK from third-party sites (APKPure, etc.) may strip the IL2CPP native
binary. Re-download using the repo's built-in tool:

```bash
./kgc-cli download -v 170.1.00 -o apk/
rm -rf apk/xapk_extracted && python3 setup.py
```

### `externally-managed-environment` on pip install

Some distros (Arch, Fedora, etc.) block system-wide pip. Use a virtual
environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
```

### Google Play Services missing on redroid

redroid without GApps can't initialize Firebase. The game will show errors like
`Firebase modules failed to initialize` and `NullReferenceException` at login.
This is expected — the server still handles all API requests. To add GApps, use
a redroid image with Google Play Services (e.g. `redroid/redroid:12.0.0-gms-latest`).

### `adb reverse` stops working after reboot

`adb reverse` is per-connection. Re-run after replugging USB or restarting the
emulator:

```bash
adb -s <serial> reverse tcp:443 tcp:8443
```
