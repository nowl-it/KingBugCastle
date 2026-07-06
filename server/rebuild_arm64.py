#!/usr/bin/env python3
"""
Rebuild arm64 APK with SSL bypass + lobby-NRE stubs + XIGNCODE3 stub.
Targets v170.1.00 (offsets re-derived via Il2CppDumper against this
version's arm64 libil2cpp.so; all prologue bytes confirmed identical to
v170.0.03, only file offsets shifted - see server/rebuild_arm64_170_1_00.py
for the derivation).
"""

import sys, struct, zipfile, zlib, pathlib, subprocess, shutil, os

XAPK = pathlib.Path("/home/nowl/Code/kgc/.deploy/xapk_extracted")
WORK = pathlib.Path("/home/nowl/Code/kgc/.rebuild3")

ORIG_APKS = {
    "base": XAPK / "com.awesomepiece.castle.apk",
    "config": XAPK / "config.arm64_v8a.apk",
    "base_assets": XAPK / "base_assets.apk",
}

XC_STUB = pathlib.Path("/home/nowl/Code/kgc/server/xigncode_stub/arm64/libxigncode.so")
KEYSTORE = pathlib.Path("/home/nowl/Code/kgc/.debug.keystore")
if not KEYSTORE.exists():
    KEYSTORE = pathlib.Path.home() / ".android" / "debug.keystore"

APKSIGNER = shutil.which("apksigner") or shutil.which("apksigner.jar")
ZIPALIGN = shutil.which("zipalign")

RET_TRUE = bytes([0x20, 0x00, 0x80, 0x52, 0xC0, 0x03, 0x5F, 0xD6])
RET_FALSE = bytes([0xE0, 0x03, 0x1F, 0x2A, 0xC0, 0x03, 0x5F, 0xD6])

ALL_PATCHES = [
    # SSL bypass ONLY (matches the proven real-server capture build).
    # Strings/PreStrings load from local APK Resources - do NOT NOP the loader.
    # No guest patches (unneeded). No metadata patch (server served over TLS).
    (0x2CB2248, "ssl", bytes.fromhex("fe5fbda9f65701a9"), RET_TRUE),
    (0x5966A04, "ssl", bytes.fromhex("ff0302d1fd7b02a9"), RET_TRUE),
    (0x5965114, "ssl", bytes.fromhex("fe0f1ff8e80300aa"), RET_TRUE),
    # WorldPanel.IsKGMarbleAvailable -> always return false.
    # Original: str x30,[sp,#-0x20]! ; stp x20,x19,[sp,#0x10]
    # The NRE happens because the static game-data dictionary is null.
    # Patching to return false avoids the NRE spam every frame.
    (0x304CDF0, "kgmarble", bytes.fromhex("fe0f1ef8f44f01a9"), RET_FALSE),
    # PackageItem.InitCustomGrowthPackage -> early return (no shop package data).
    # Original: str x30,[sp,#-0x60]! ; stp x28,x27,[sp,#0x10]
    # NRE when prefab PackageItem components iterate with no server data.
    (0x32B5DF8, "shop-growth", bytes.fromhex("fe0f1af8fc6f01a9"), RET_FALSE),
    # PackageItem.InitSeasonPassPackage -> early return.
    # Original: sub sp,sp,#0x50 ; stp x30,x25,[sp,#0x10]
    (0x32B7EC8, "shop-season", bytes.fromhex("ff4301d1fe6701a9"), RET_FALSE),
    # PvPPanel.GetReceivableWinRewardCount -> always return 0.
    # Original: str x30,[sp,#-0x50]! ; stp x26,x25,[sp,#0x10]
    # IndexOutOfRange because winRewardReceived is empty and an inner array
    # at [model+0x220][0xc0] is also empty.
    (0x3245178, "pvp-reward", bytes.fromhex("fe0f1bf8fa6701a9"), RET_FALSE),
    # DeckPanel.ReloadDeck / DeckPanel.Reload -> TEMPORARILY UNPATCHED to
    # capture the real crash (root-cause investigation, 2026-07-02). Restore
    # these two RET_FALSE stubs before any non-debug deploy. NOTE: offsets
    # below are still the v170.0.03 ones - not re-derived since inactive.
    # (0x3198970, "deck-reload", bytes.fromhex("ff0302d1fd7b02a9"), RET_FALSE),
    # (0x3197894, "deck-reload2", bytes.fromhex("ff4305d1eb2b0d6d"), RET_FALSE),
    # PvPPanel.<Init>d__77.MoveNext -> early return. NOT re-derived for
    # v170.1.00 (compiler-generated async state machine, harder to relocate
    # by name); left disabled rather than guessed.
    # (0x324BB70, "pvp-init", bytes.fromhex("ff8303d1fd7b08a9"), RET_FALSE),
    # GameManager.IsYearEventAvailable -> always return false.
    # Original: str x30,[sp,#-0x20]! ; stp x20,x19,[sp,#0x10]
    # Same pattern as IsKGMarbleAvailable - null data dictionary.
    (0x304AC0C, "year-event", bytes.fromhex("fe0f1ef8f44f01a9"), RET_FALSE),
    # GameManager.GetBabelData -> return null.
    # Original: str x30,[sp,#-0x30]!; stp x22,x21,[sp,#0x10]
    # Returns BabelResponseModel.BabelModel; null-check passes in caller via cbz x0.
    (0x30321DC, "babel-data", bytes.fromhex("fe0f1df8f65701a9"), bytes.fromhex("e0031f2ac0035fd6")),
    # WorldPanel.ReloadNewContentAlert -> early return.
    # Original: str x30,[sp,#-0x50]!; stp x26,x25,[sp,#0x10]
    # NRE after GetBabelData returns null (no babel data from server).
    (0x349BAB4, "content-alert", bytes.fromhex("fe0f1bf8fa6701a9"), bytes.fromhex("e0031f2ac0035fd6")),
    # GameManager.IsEventCardCollectingAvailable -> always return false.
    # Original: str x30,[sp,#-0x20]!; stp x20,x19,[sp,#0x10]
    # Same pattern as IsKGMarbleAvailable.
    (0x304CCEC, "card-event", bytes.fromhex("fe0f1ef8f44f01a9"), RET_FALSE),
    # GameManager.IsSpecialSeasonalEventOpened -> always return false.
    # Original: str x30,[sp,#-0x20]!; stp x20,x19,[sp,#0x10]
    # Same pattern as IsKGMarbleAvailable.
    (0x304CBE4, "season-event", bytes.fromhex("fe0f1ef8f44f01a9"), RET_FALSE),
]


def patch_apk(apk_path):
    """Apply all patches to libil2cpp.so inside the APK."""
    data = bytearray(apk_path.read_bytes())
    with zipfile.ZipFile(apk_path) as z:
        info = z.getinfo("lib/arm64-v8a/libil2cpp.so")
        assert info.compress_type == 0, "libil2cpp.so is compressed"

    ho = info.header_offset
    fn_len = struct.unpack_from('<H', data, ho + 26)[0]
    ex_len = struct.unpack_from('<H', data, ho + 28)[0]
    lib_off = ho + 30 + fn_len + ex_len
    assert bytes(data[lib_off:lib_off+4]) == b'\x7fELF'

    patched = 0
    for off, kind, expected, new_bytes in ALL_PATCHES:
        end = off + len(new_bytes)
        if end > info.file_size:
            print(f"  SKIP 0x{off:x} ({kind}): exceeds file")
            continue
        cur = bytes(data[lib_off+off: lib_off+off+len(new_bytes)])
        if expected is not None:
            if cur == new_bytes:
                print(f"  OK   0x{off:x} ({kind}): already patched")
                patched += 1
                continue
            if cur != expected:
                print(f"  SKIP 0x{off:x} ({kind}): expected {expected.hex()} got {cur.hex()}")
                continue
        data[lib_off+off: lib_off+end] = new_bytes
        print(f"  PATCH 0x{off:x} ({kind}): {cur.hex()} -> {new_bytes.hex()}")
        patched += 1

    # Update CRC
    lib_data = bytes(data[lib_off: lib_off+info.file_size])
    crc = zlib.crc32(lib_data) & 0xFFFFFFFF
    struct.pack_into('<I', data, ho + 14, crc)

    # Update central directory CRC
    pos = bytes(data).find(b'PK\x01\x02', lib_off + info.file_size)
    while pos >= 0:
        nl = struct.unpack_from('<H', data, pos + 28)[0]
        if bytes(data[pos+46: pos+46+nl]) == b'lib/arm64-v8a/libil2cpp.so':
            struct.pack_into('<I', data, pos + 16, crc)
            break
        pos = bytes(data).find(b'PK\x01\x02', pos + 1)

    apk_path.write_bytes(data)
    return patched


def inject_xc_stub(apk_path):
    """Replace libxigncode.so with stub."""
    data = bytearray(apk_path.read_bytes())
    stub = XC_STUB.read_bytes()

    with zipfile.ZipFile(apk_path) as z:
        info = z.getinfo("lib/arm64-v8a/libxigncode.so")
        orig_size = info.file_size
        assert info.compress_type == 0

    ho = info.header_offset
    fn_len = struct.unpack_from('<H', data, ho + 26)[0]
    ex_len = struct.unpack_from('<H', data, ho + 28)[0]
    lib_off = ho + 30 + fn_len + ex_len

    # Pad stub to original size
    stub_padded = stub + b'\x00' * (orig_size - len(stub))
    data[lib_off: lib_off+orig_size] = stub_padded

    crc = zlib.crc32(stub_padded) & 0xFFFFFFFF
    struct.pack_into('<I', data, ho + 14, crc)
    # Central dir
    pos = bytes(data).find(b'PK\x01\x02', lib_off + orig_size)
    while pos >= 0:
        nl = struct.unpack_from('<H', data, pos + 28)[0]
        if bytes(data[pos+46: pos+46+nl]) == b'lib/arm64-v8a/libxigncode.so':
            struct.pack_into('<I', data, pos + 16, crc)
            break
        pos = bytes(data).find(b'PK\x01\x02', pos + 1)

    apk_path.write_bytes(data)
    print(f"  [XC] {orig_size} -> {len(stub)} bytes (padded to {orig_size})")


def sign(apk_path):
    subprocess.run([
        APKSIGNER, "sign",
        "--ks", str(KEYSTORE),
        "--ks-key-alias", "androiddebugkey",
        "--ks-pass", "pass:android",
        "--v1-signing-enabled", "true",
        "--v2-signing-enabled", "true",
        str(apk_path)
    ], check=True, capture_output=True)
    print(f"  [SIGN] {apk_path.name}")


def main():
    for name, path in ORIG_APKS.items():
        if not path.exists():
            print(f"ERROR: {name} not found at {path}")
            sys.exit(1)

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    # Copy originals
    outputs = {}
    for name, src in ORIG_APKS.items():
        dst = WORK / src.name
        shutil.copy2(src, dst)
        outputs[name] = dst

    print("=== Patching libil2cpp (SSL + lobby-NRE stubs) ===")
    pcount = patch_apk(outputs["config"])
    print(f"  {pcount} patches applied")

    print("\n=== Injecting XC stub ===")
    inject_xc_stub(outputs["config"])

    print("\n=== Signing ===")
    for name, apk in outputs.items():
        aligned = apk.with_name(apk.stem + "_aligned" + apk.suffix)
        subprocess.run([ZIPALIGN, "-p", "-f", "4", str(apk), str(aligned)], check=True, capture_output=True)
        shutil.move(str(aligned), str(apk))
        sign(apk)

    print("\n=== Installing ===")
    import os as _os
    _adb_serial = _os.environ.get("ADB_SERIAL", "emulator-5554")
    cmd = ["adb", "-s", _adb_serial, "install-multiple", "--no-incremental",
           str(outputs["base"]),
           str(outputs["config"]),
           str(outputs["base_assets"])]
    print(f"  {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"  stdout: {r.stdout}")
    print(f"  stderr: {r.stderr}")
    if r.returncode == 0:
        print("  SUCCESS")
    else:
        print(f"  FAILED (rc={r.returncode})")
        sys.exit(1)


if __name__ == '__main__':
    main()
