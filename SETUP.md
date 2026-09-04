# Setup - run your own KGC private server

Clone the repo, run one setup script, and you have your own King God Castle
private server that a modded client connects to. Works on **Linux, macOS, and
Windows**, against **redroid, BlueStacks, LDPlayer, or a real Android phone**.

> The local server and TUI launcher are cross-platform Python plus a few Java/adb CLI tools.
> The native pieces (`libxigncode.so`, `libmain_wrapper.so`) ship **prebuilt**,
> so you do **not** need the Android NDK or SDK to build - just `apktool`,
> `apksigner`, `zipalign`, `adb`, and a JRE.

---

## 1. Prerequisites

| Tool | Linux | macOS | Windows |
|---|---|---|---|
| apktool, apksigner, zipalign, adb, JRE | `sudo apt install apktool apksigner zipalign adb default-jre` | `brew install apktool android-platform-tools openjdk` (+ SDK build-tools for zipalign/apksigner) | Android SDK **build-tools** (apksigner.bat, zipalign.exe) + **platform-tools** (adb) + apktool + a JRE, all on PATH |
| Python 3.9+ | preinstalled | preinstalled | python.org |
| Node.js 20+ and pnpm 11.3 | package manager or nodejs.org | `brew install node pnpm` | nodejs.org, then `npm install -g pnpm@11.3.0` |

The Android tools must be on your `PATH`. `python setup.py` checks them and prints what's missing.

## 2. Supply the game files

The game APK is **not** in this repo (copyright + 1 GB). On Linux x86_64, the bundled
`kgc-cli` can download the correct **King God Castle v170.1.00, arm64** XAPK:

```bash
mkdir -p apk && ./kgc-cli download -v 170.1.00 -o apk/
```

On macOS or Windows, place a legally obtained, complete arm64 `.xapk` or `.zip` in
`apk/`; the bundled `kgc-cli` executable is Linux x86_64 only.

> **Why v170.1.00?** It is the last version that ships `libil2cpp.so` in the APK,
> so this clone-and-run path patches it directly and needs nothing else. Newer
> **v171 / v172** clients pack the code inside XIGNCODE NEO, so the game binary has to be
> unpacked out of the packer first (`server/patchers/unpack_neo.py`, offline and
> automatic) before `server/builders/build_private.py` can inject it. That path works
> and is documented in [docs/private-build.md](docs/private-build.md);
> it is just a longer first run than this one.

> **Why `kgc-cli`?** APKs from third-party sites (APKPure, etc.) often strip
> `libil2cpp.so` (the IL2CPP runtime binary). `kgc-cli` downloads a complete
> XAPK with all native libraries included. If you use a manually-downloaded XAPK
> and the build fails with `libil2cpp.so not found`, re-download with `kgc-cli`.

## 3. Setup

Create a Python virtual environment (recommended — some distros block system-wide
`pip install` with `externally-managed-environment`):

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies, then run setup. Installing first lets Windows generate the
self-signed TLS certificate through the Python fallback when OpenSSL is absent:

```bash
python -m pip install -r server/requirements.txt
python setup.py                        # checks tools, extracts XAPK, makes keys/cert
```

## 4. Start the server

Two listeners: HTTP :8080 and TLS :8443 (the client talks HTTPS; the SSL-bypass
patch accepts the self-signed cert). `setup.py` generates `server/cert.pem` +
`server/key.pem` for you.

The same TUI starts HTTP, TLS, the admin API, and Next.js on every platform:

```bash
python server/run.py
```

Use `python server/run.py --check` to validate dependencies without starting anything.
Press `d` to connect and wire the configured adb device. The launcher uses process
groups native to each OS and stores logs in that OS's temporary directory.

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

Linux/macOS:

```bash
ADB_SERIAL=<serial> python server/rebuild_arm64_mod.py --host 127.0.0.1
```

Windows PowerShell:

```powershell
$env:ADB_SERIAL = "<serial>"
python server/rebuild_arm64_mod.py --host 127.0.0.1
```

**Route the device's :443 to your server's :8443** (no root needed):

```bash
adb -s <serial> reverse tcp:443 tcp:8443
adb -s <serial> reverse tcp:80  tcp:8080     # optional, CDN is https so usually not needed
```

Launch "King Bug Castle". The client hits `127.0.0.1:443` → adb-reverse → your
`:8443` server. Watch it connect:

Select `Game HTTP` or `Game TLS` in the TUI to watch its live log.

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

The prebuilt `.so` ship in the repo. Only if you edit `server/jni/stub.cpp` do you need
NDK 27 (`ndk;27.2.12479018`). NDK 28 has C++ linking issues (`__libcpp_verbose_abort`
undefined) — do NOT upgrade.

```bash
cd /tmp && rm -rf stub_build && mkdir stub_build && cd stub_build
cat > CMakeLists.txt << 'EOF'
cmake_minimum_required(VERSION 3.18)
project(xigncode CXX)
set(CMAKE_CXX_STANDARD 17)
add_library(xigncode SHARED /path/to/kgc/server/jni/stub.cpp)
target_link_libraries(xigncode log dl)
target_compile_options(xigncode PRIVATE -fno-exceptions -fno-rtti)
set_target_properties(xigncode PROPERTIES LINK_FLAGS "-Wl,-init,xigncode_stub_init")
EOF
cmake -DCMAKE_TOOLCHAIN_FILE=$ANDROID_NDK/build/cmake/android.toolchain.cmake \
      -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-24 \
      -DANDROID_STL=c++_static -DCMAKE_BUILD_TYPE=Release . && cmake --build .
cp libxigncode.so /path/to/kgc/server/xigncode_stub/arm64/
cp libxigncode.so /path/to/kgc/server/xigncode_stub/
```

## Path overrides (non-standard layouts)

The build auto-derives everything from the repo root. Override via env if needed:
`KGC_ROOT`, `KGC_XAPK` (extracted-splits dir), `KGC_WORK` (build scratch), `ADB_SERIAL`.

---

## Troubleshooting

### `libil2cpp.so not found` in config APK

The XAPK from third-party sites (APKPure, etc.) may strip the IL2CPP native
binary. On Linux x86_64, re-download using the repo's built-in tool:

```bash
./kgc-cli download -v 170.1.00 -o apk/
rm -rf apk/xapk_extracted && python setup.py
```

On macOS or Windows, replace the XAPK in `apk/`, remove `apk/xapk_extracted`, and
run `python setup.py` again.

### `externally-managed-environment` on pip install

Some distros (Arch, Fedora, etc.) block system-wide pip. Use a virtual
environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r server/requirements.txt
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1` instead.

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
