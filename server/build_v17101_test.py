#!/usr/bin/env python3
"""Quick test build for v171.0.01 on redroid.

Starts servers if not running, patches APKs with host rebinding +
XIGNCODE stub replacement. NEO loader (libgabriel.so) left untouched.

Usage: KGC_SKIP_PACKAGE=y python3 server/build_v17101_test.py
"""

import sys, subprocess, shutil, pathlib, os, zipfile, json, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from rebuild_arm64 import sign, ZIPALIGN

REPO = pathlib.Path(__file__).resolve().parents[1]
XAPK = REPO / "apk" / "xapk_extracted_v17101"
WORK = REPO / ".rebuild_v17101"
PATCHERS = REPO / "server" / "patchers"

OLD_PKG = "com.awesomepiece.castle"
NEW_PKG = "com.nowl.castle"
NEW_LABEL = "King Bug Castle v17101"
SHARE_HOST = os.environ.get("SHARE_HOST", "127.0.0.1")

ORIG_APKS = {
    "base": XAPK / "com.awesomepiece.castle.apk",
    "config": XAPK / "config.arm64_v8a.apk",
    "base_assets": XAPK / "base_assets.apk",
}

def replace_xigncode(apk_path):
    print(f"[*] Replacing libxigncode.so with stub in {apk_path.name}...")
    stub_data = (REPO / "server" / "xigncode_stub" / "arm64" / "libxigncode.so").read_bytes()
    tmp = pathlib.Path(tempfile.mktemp(suffix=".apk"))
    patched_count = 0
    with zipfile.ZipFile(apk_path, "r") as zin:
        with zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "lib/arm64-v8a/libxigncode.so":
                    orig_size = len(data)
                    stub_padded = bytearray(stub_data)
                    stub_padded.extend(b'\0' * (orig_size - len(stub_padded)))
                    data = bytes(stub_padded)
                    patched_count += 1
                new_item = zipfile.ZipInfo(item.filename, item.date_time)
                new_item.compress_type = item.compress_type
                zout.writestr(new_item, data)
    shutil.move(tmp, apk_path)
    print(f"  [+] patched {patched_count} xigncode copies")

def main():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    outputs = {name: WORK / src.name for name, src in ORIG_APKS.items()}
    for name, dst in outputs.items():
        shutil.copy2(ORIG_APKS[name], dst)

    skip_pkg = os.environ.get("KGC_SKIP_PACKAGE")
    if not skip_pkg:
        base_apk = outputs["base"]

        print("[+] Renaming label -> King Bug Castle v17101...")
        subprocess.run([sys.executable, str(PATCHERS / "patch_rename.py"),
                        str(base_apk), NEW_LABEL], check=True)

        print(f"[+] Renaming package id -> {NEW_PKG} (base)...")
        subprocess.run([sys.executable, str(PATCHERS / "patch_package_id.py"),
                        str(base_apk), OLD_PKG, NEW_PKG], check=True)

        print(f"[+] Renaming package id -> {NEW_PKG} (config/base_assets)...")
        for name in ("config", "base_assets"):
            subprocess.run([sys.executable, str(PATCHERS / "patch_package_id_light.py"),
                            str(outputs[name]), OLD_PKG, NEW_PKG], check=True)

        print("[+] Injecting Firebase/meta-data/cleartext into manifest...")
        dec = WORK / "dec_base"
        subprocess.run(["apktool", "d", "-s", "-f", str(base_apk), "-o", str(dec)],
                       check=True, stdout=subprocess.DEVNULL)

        manifest = dec / "AndroidManifest.xml"
        txt = manifest.read_text(encoding="utf-8")

        # Re-enable FirebaseInitProvider
        txt = txt.replace(
            '<provider android:authorities="com.nowl.castle.firebaseinitprovider" android:directBootAware="true" android:exported="false" android:initOrder="100" android:name="com.google.firebase.provider.FirebaseInitProvider" android:enabled="false"/>',
            '<provider android:authorities="com.nowl.castle.firebaseinitprovider" android:directBootAware="true" android:exported="false" android:initOrder="100" android:name="com.google.firebase.provider.FirebaseInitProvider"/>')
        meta = ('<meta-data android:name="firebase_analytics_collection_deactivated" android:value="true"/>'
                '<meta-data android:name="google_analytics_adid_collection_enabled" android:value="false"/>')
        if meta not in txt:
            txt = txt.replace("</application>", meta + "</application>", 1)
        if "usesCleartextTraffic" not in txt:
            txt = txt.replace("<application ", '<application android:usesCleartextTraffic="true" ', 1)
        manifest.write_text(txt, encoding="utf-8")

        out = WORK / "rebuilt_base.apk"
        subprocess.run(["apktool", "b", str(dec), "-o", str(out)],
                       check=True, stdout=subprocess.DEVNULL)
        shutil.copy(out, base_apk)

        print("[+] Forcing extractNativeLibs=true...")
        subprocess.run([sys.executable, str(PATCHERS / "patch_extract_native.py"),
                        str(base_apk)], check=True)
    else:
        print("[!] Skipping package rename (KGC_SKIP_PACKAGE=y)")

    config_apk = outputs["config"]

    # XIGNCODE stub replacement
    replace_xigncode(config_apk)

    # Host rebinding
    print(f"\n[+] Rebinding backend hosts -> {SHARE_HOST}...")
    subprocess.run([sys.executable, str(PATCHERS / "patch_hosts.py"),
                    str(outputs["base_assets"]), SHARE_HOST], check=True)

    print("[+] Converting backend URLs https -> http...")
    subprocess.run([sys.executable, str(PATCHERS / "patch_metadata_http.py"),
                    str(outputs["base_assets"])], check=True)

    print(f"[+] Rebinding leftover hosts -> {SHARE_HOST}...")
    subprocess.run([sys.executable, str(PATCHERS / "patch_leftover_hosts.py"),
                    str(outputs["base_assets"]), SHARE_HOST], check=True)

    print("\n=== Signing ===")
    for name, apk in outputs.items():
        aligned = apk.with_name(apk.stem + "_aligned" + apk.suffix)
        subprocess.run([ZIPALIGN, "-p", "-f", "4", str(apk), str(aligned)],
                       check=True, capture_output=True)
        shutil.move(str(aligned), str(apk))
        sign(apk)

    print("\n=== Uninstalling previous ===")
    subprocess.run(["adb", "-s", "localhost:5555", "uninstall", NEW_PKG],
                   capture_output=True)

    print("\n=== Installing to Device ===")
    cmd = ["adb", "-s", "localhost:5555", "install-multiple", "--no-incremental",
           str(outputs["base"]), str(outputs["config"]), str(outputs["base_assets"])]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        print("SUCCESS")
    else:
        print("FAILED", r.stderr)

if __name__ == '__main__':
    main()
