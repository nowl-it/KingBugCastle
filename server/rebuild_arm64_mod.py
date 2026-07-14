#!/usr/bin/env python3
"""
Build the "King Bug Castle" (com.nowl.castle) variant - same v170.1.00
SSL+NRE patches as rebuild_arm64.py, but renamed so it installs side-by-side
with the real com.awesomepiece.castle instead of replacing it. Reuses
ALL_PATCHES/patch_apk/inject_xc_stub from rebuild_arm64.py so the two never
drift out of sync on a version bump - only rename this file's own new steps.
"""

import sys, pathlib, subprocess, shutil, os, json, zipfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from rebuild_arm64 import patch_apk, inject_xc_stub, sign, ZIPALIGN

# Auto-derive from repo root (see rebuild_arm64.py). Env-overridable.
REPO = pathlib.Path(os.environ.get("KGC_ROOT") or pathlib.Path(__file__).resolve().parents[1])
XAPK = pathlib.Path(os.environ.get("KGC_XAPK") or REPO / "apk" / "xapk_extracted")
WORK = pathlib.Path(os.environ.get("KGC_WORK") or REPO / ".rebuild_mod")
PATCHERS = REPO / "server" / "patchers"
SHARE_OUT = REPO / "KingBugCastle.xapk"

OLD_PKG = "com.awesomepiece.castle"
NEW_PKG = "com.nowl.castle"
NEW_LABEL = "King Bug Castle"


def build_xapk(outputs, host):
    """Package the 3 signed APKs into a shareable .xapk (APKPure format) that points at
    `host`. Standard split-APK installers (APKPure, SAI) read manifest.json + install all
    parts. No per-device config - the metadata host-rebind (patch_hosts) already baked the
    server address in."""
    src_manifest = json.loads((XAPK / "manifest.json").read_text())
    src_manifest["package_name"] = NEW_PKG
    src_manifest["name"] = NEW_LABEL
    src_manifest.pop("locales_name", None)
    src_manifest["split_apks"] = [
        {"file": "com.awesomepiece.castle.apk", "id": "base"},
        {"file": "config.arm64_v8a.apk", "id": "config.arm64_v8a"},
        {"file": "base_assets.apk", "id": "base_assets"},
    ]
    src_manifest["total_size"] = sum(outputs[n].stat().st_size for n in outputs)
    src_manifest["_server_host"] = host
    if SHARE_OUT.exists():
        SHARE_OUT.unlink()
    with zipfile.ZipFile(SHARE_OUT, "w", zipfile.ZIP_STORED) as z:
        z.writestr("manifest.json", json.dumps(src_manifest, ensure_ascii=False, indent=1))
        icon = XAPK / "icon.png"
        if icon.exists():
            z.writestr("icon.png", icon.read_bytes())  # writestr avoids pre-1980 mtime reject
        for name, apk in outputs.items():
            zi = zipfile.ZipInfo(apk.name)  # force a valid timestamp; stream the 900MB file
            with apk.open("rb") as fsrc, z.open(zi, "w") as fdst:
                shutil.copyfileobj(fsrc, fdst, length=8 * 1024 * 1024)
    print(f"\n=== Shareable XAPK written: {SHARE_OUT} ({SHARE_OUT.stat().st_size/1e6:.0f} MB) ===")
    print(f"    package: {NEW_PKG}  ·  server host baked in: {host}")
    print(f"    Players install with APKPure / SAI (Split APKs Installer). No config needed.")

ORIG_APKS = {
    "base": XAPK / "com.awesomepiece.castle.apk",
    "config": XAPK / "config.arm64_v8a.apk",
    "base_assets": XAPK / "base_assets.apk",
}


def main():
    # Share mode: bake a server host into the APK + package a .xapk instead of installing.
    #   SHARE_HOST=1.2.3.4 python3 rebuild_arm64_mod.py --share
    #   python3 rebuild_arm64_mod.py --share --host kgc.example.com
    args = sys.argv[1:]
    share = "--share" in args
    host = os.environ.get("SHARE_HOST")
    if "--host" in args:
        host = args[args.index("--host") + 1]
    if share and not host:
        print("ERROR: --share needs a server host: --host <ip-or-domain> or SHARE_HOST=<...>")
        sys.exit(1)

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

    print("\n=== Forcing extractNativeLibs=true (so System.loadLibrary can find libxigncode.so) ===")
    subprocess.run([sys.executable, str(PATCHERS / "patch_extract_native.py"),
                    str(outputs["base"])], check=True)

    print("\n=== Patching libil2cpp (SSL + lobby-NRE stubs, v170.1.00 offsets) ===")
    pcount = patch_apk(outputs["config"])
    print(f"  {pcount} patches applied")

    print("\n=== Injecting XC stub ===")
    inject_xc_stub(outputs["config"])

    print("\n=== Replacing libmain.so with dlopen wrapper (loads libxigncode via JNI_OnLoad) ===")
    subprocess.run([sys.executable, str(PATCHERS / "patch_replace_libmain.py"),
                    str(outputs["config"])], check=True)

    if host:
        print(f"\n=== Rebinding backend hosts -> {host} (so remote players reach YOUR server) ===")
        subprocess.run([sys.executable, str(PATCHERS / "patch_hosts.py"),
                        str(outputs["base_assets"]), host], check=True)

    print("\n=== Signing ===")
    for name, apk in outputs.items():
        aligned = apk.with_name(apk.stem + "_aligned" + apk.suffix)
        subprocess.run([ZIPALIGN, "-p", "-f", "4", str(apk), str(aligned)], check=True, capture_output=True)
        shutil.move(str(aligned), str(apk))
        sign(apk)

    if share:
        build_xapk(outputs, host)
        return

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
