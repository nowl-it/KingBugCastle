#!/usr/bin/env python3
"""
Build the "King Bug Castle" (com.nowl.castle) variant - same v170.1.00
SSL+NRE patches as rebuild_arm64.py, but renamed so it installs side-by-side
with the real com.awesomepiece.castle instead of replacing it. Reuses
ALL_PATCHES/patch_apk/inject_xc_stub from rebuild_arm64.py so the two never
drift out of sync on a version bump - only rename this file's own new steps.
"""

import sys, pathlib, subprocess, shutil, os

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from rebuild_arm64 import patch_apk, inject_xc_stub, sign, ZIPALIGN

XAPK = pathlib.Path("/home/nowl/Code/kgc/.deploy/xapk_extracted")
WORK = pathlib.Path("/home/nowl/Code/kgc/.rebuild_mod")
PATCHERS = pathlib.Path("/home/nowl/Code/kgc/server/patchers")

OLD_PKG = "com.awesomepiece.castle"
NEW_PKG = "com.nowl.castle"
NEW_LABEL = "King Bug Castle"

ORIG_APKS = {
    "base": XAPK / "com.awesomepiece.castle.apk",
    "config": XAPK / "config.arm64_v8a.apk",
    "base_assets": XAPK / "base_assets.apk",
}


def main():
    for name, path in ORIG_APKS.items():
        if not path.exists():
            print(f"ERROR: {name} not found at {path}")
            sys.exit(1)

    WORK.mkdir(parents=True, exist_ok=True)
    outputs = {name: WORK / src.name for name, src in ORIG_APKS.items()}
    for name, dst in outputs.items():
        if not dst.exists():
            shutil.copy2(ORIG_APKS[name], dst)

    print("=== Renaming label -> King Bug Castle ===")
    subprocess.run([sys.executable, str(PATCHERS / "patch_rename.py"),
                    str(outputs["base"]), NEW_LABEL], check=True)

    print("\n=== Renaming package id -> com.nowl.castle (base, apktool) ===")
    subprocess.run([sys.executable, str(PATCHERS / "patch_package_id.py"),
                     str(outputs["base"]), OLD_PKG, NEW_PKG], check=True)

    print("\n=== Renaming package id -> com.nowl.castle (config/base_assets, light) ===")
    for name in ("config", "base_assets"):
        subprocess.run([sys.executable, str(PATCHERS / "patch_package_id_light.py"),
                         str(outputs[name]), OLD_PKG, NEW_PKG], check=True)

    print("\n=== Patching libil2cpp (SSL + lobby-NRE stubs, v170.1.00 offsets) ===")
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

    print("\n=== Installing (side-by-side, not -r) ===")
    _adb_serial = os.environ.get("ADB_SERIAL", "emulator-5554")
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
