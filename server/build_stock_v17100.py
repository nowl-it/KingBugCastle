#!/usr/bin/env python3
"""Build v171.0.00 patched for emulator on REAL server.

- No host rebinding -> connects to REAL awesomepiece servers
- No Awake/CDN patches -> game's normal flow preserved
- Only platform patches: NEO bypass, SSL bypass, XIGNCODE stub, Firebase/GMS skip, null-checks
"""
import sys, subprocess, shutil, pathlib, os, zipfile, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from rebuild_arm64 import sign, ZIPALIGN

REPO = pathlib.Path(__file__).resolve().parents[1]
XAPK = REPO / "apk" / "xapk_extracted_v171"
WORK = REPO / ".rebuild_stock_v17100"
IL2CPP_DEC = REPO / "il2cpp" / "v171.0.00" / "libil2cpp_v171_ssl.so"

ORIG_APKS = {
    "base": XAPK / "com.awesomepiece.castle.apk",
    "config": XAPK / "config.arm64_v8a.apk",
    "base_assets": XAPK / "base_assets.apk",
}

def main():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    outputs = {name: WORK / src.name for name, src in ORIG_APKS.items()}
    for name, dst in outputs.items():
        shutil.copy2(ORIG_APKS[name], dst)

    base_apk = outputs["base"]
    config = outputs["config"]

    # Step 1: extractNativeLibs=true
    print("[+] Forcing extractNativeLibs=true...")
    subprocess.run([sys.executable,
                    str(REPO / "server" / "patchers" / "patch_extract_native.py"),
                    str(base_apk)], check=True)

    # Step 2: Patch libaledatic.so (12 NOPs)
    print("[*] Patching libaledatic.so (12 NOPs)...")
    tmp = pathlib.Path(tempfile.mktemp(suffix=".apk"))
    count = 0
    with zipfile.ZipFile(config, "r") as zin:
        with zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.infolist():
                data = bytearray(zin.read(item.filename))
                ni = zipfile.ZipInfo(item.filename, item.date_time)
                ni.compress_type = item.compress_type
                if item.filename == "lib/arm64-v8a/libaledatic.so":
                    for off in [0x3d2b8, 0x3d2c0, 0x3d2c8, 0x3d2f8,
                                0x3d484, 0x3d4c8, 0x3d4e4, 0x3d4f4]:
                        if data[off+3] in (0x37, 0xb4):
                            data[off:off+4] = b'\x1f\x20\x03\xd5'; count += 1
                    for off in [0xe5728, 0xe57d0, 0xe57e8, 0xe5870]:
                        if data[off+3] == 0x14:
                            data[off:off+4] = b'\x1f\x20\x03\xd5'; count += 1
                    data = bytes(data)
                zout.writestr(ni, data)
    shutil.move(tmp, config)
    print(f"  [+] {count} patches applied")

    # Step 3: Inject decrypted il2cpp + SSL bypass
    print("[*] Injecting decrypted il2cpp + SSL bypass...")
    il2 = bytearray(IL2CPP_DEC.read_bytes())
    for off, name in [(0x2CB68D8, "PinnedCertHandler"),
                       (0x596EF64, "UnityTlsProvider"),
                       (0x596D674, "MobileTlsContext")]:
        il2[off:off+8] = bytes([0x20, 0x00, 0x80, 0x52, 0xC0, 0x03, 0x5F, 0xD6])
    tmp2 = pathlib.Path(tempfile.mktemp(suffix=".apk"))
    with zipfile.ZipFile(config, "r") as zin:
        with zipfile.ZipFile(tmp2, "w") as zout:
            for item in zin.infolist():
                d = zin.read(item.filename)
                ni = zipfile.ZipInfo(item.filename, item.date_time)
                ni.compress_type = item.compress_type
                zout.writestr(ni, d)
            ii = zipfile.ZipInfo("lib/arm64-v8a/libil2cpp.so")
            ii.compress_type = zipfile.ZIP_STORED
            zout.writestr(ii, bytes(il2))
    shutil.move(tmp2, config)

    # Step 4: Patch libxigncode.so BLR X21 -> MOV
    print("[*] Patching libxigncode.so BLR X21...")
    tmp3 = pathlib.Path(tempfile.mktemp(suffix=".apk"))
    with zipfile.ZipFile(config, "r") as zin:
        with zipfile.ZipFile(tmp3, "w") as zout:
            for item in zin.infolist():
                data = bytearray(zin.read(item.filename))
                ni = zipfile.ZipInfo(item.filename, item.date_time)
                ni.compress_type = item.compress_type
                if item.filename == "lib/arm64-v8a/libxigncode.so":
                    data[0x18678:0x1867c] = b'\xe0\x03\x1f\xaa'
                    data[0x1868c:0x18690] = b'\xe0\x03\x1f\xaa'
                zout.writestr(ni, bytes(data))
    shutil.move(tmp3, config)

    # Step 5: Core patches on il2cpp
    def _wr(offset, patch_bytes):
        nonlocal config
        tmp = pathlib.Path(tempfile.mktemp(suffix=".apk"))
        with zipfile.ZipFile(config, "r") as zin:
            data = bytearray(zin.read("lib/arm64-v8a/libil2cpp.so"))
        data[offset:offset+len(patch_bytes)] = patch_bytes
        with zipfile.ZipFile(config, "r") as zin:
            with zipfile.ZipFile(tmp, "w") as zout:
                for item in zin.infolist():
                    d = zin.read(item.filename)
                    ni = zipfile.ZipInfo(item.filename, item.date_time)
                    ni.compress_type = item.compress_type
                    if item.filename == "lib/arm64-v8a/libil2cpp.so":
                        zout.writestr(ni, bytes(data))
                    else:
                        zout.writestr(ni, d)
        shutil.move(tmp, config)

    print("[*] CheckFirebase RET...")
    _wr(0x303c6c0, b'\xc0\x03\x5f\xd6')

    print("[*] GoogleInit RET + SocialInit skip PlayGames...")
    _wr(0x34f6d70, b'\xc0\x03\x5f\xd6')
    _wr(0x34f6d3c, b'\x09\x00\x00\x14')

    print("[*] Google login init -> early return (avoids hang on redroid)...")
    _wr(0x34f6d90, bytes.fromhex('20008052c0035fd6'))

    print("[*] AwesomePrefs null-check + TripleDES null-check...")
    _wr(0x36ed134, b'\x73\x00\x00\xb4')
    _wr(0x36ec830, bytes.fromhex('80000034081040b948000034feffff17c0035fd6'))

    print("[*] LoadStoryMode + RogueLikeDataSet null-checks...")
    _wr(0x3095e0c, b'\xc0\x1f\x00\xb4')
    _wr(0x307c000, b'\x35\x00\x00\xb4')

    # No Awake/CDN patches - let game run normally
    # PreStrings will fail to load (Addressable assets not in Resources, expected).
    # Game should then call CheckUseAssetBundle -> CDN download -> load strings -> proceed.
    print("[=] Awake/CDN left untouched (game uses real server URLs)")

    print("\n=== Signing ===")
    for name, apk in outputs.items():
        aligned = apk.with_name(apk.stem + "_aligned" + apk.suffix)
        subprocess.run([ZIPALIGN, "-p", "-f", "4", str(apk), str(aligned)],
                       check=True, capture_output=True)
        shutil.move(str(aligned), str(apk))
        sign(apk)

    print("\n=== Uninstalling old ===")
    subprocess.run(["adb", "-s", "localhost:5555", "uninstall",
                    "com.awesomepiece.castle"], capture_output=True)

    print("\n=== Installing ===")
    cmd = ["adb", "-s", "localhost:5555", "install-multiple", "--no-incremental",
           str(outputs["base"]), str(outputs["config"]), str(outputs["base_assets"])]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        print("SUCCESS")
    else:
        print("FAILED:", r.stderr)

if __name__ == '__main__':
    main()
