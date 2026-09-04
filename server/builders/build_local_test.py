#!/usr/bin/env python3
"""
Build a local test APK with custom name for skin testing.
Usage: python3 build_local_test.py [app_name]
Default app name: "King Local Castle"
"""
import sys, subprocess, shutil, pathlib, os, tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
XAPK = REPO / "apk" / "xapk_extracted_v17201"
WORK = REPO / ".rebuild_local"

# Original and new package info
OLD_PKG = "com.awesomepiece.castle"
NEW_PKG = "com.nowl.castle"
APP_NAME = sys.argv[1] if len(sys.argv) > 1 else "King Local Castle"

APKS = {
    "base": XAPK / "com.awesomepiece.castle.apk",
    "config": XAPK / "config.arm64_v8a.apk",
    "base_assets": XAPK / "base_assets.apk",
}

def main():
    print(f"[*] Building local test APK: {APP_NAME}")
    print(f"[*] Package: {NEW_PKG}")
    
    # Clean work dir
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    
    # Step 1: Decompile base APK with apktool
    print("\n[1/4] Decompling base APK...")
    base_apk = APKS["base"]
    subprocess.run([
        "apktool", "d", "-f", "-o", str(WORK / "base_dec"),
        str(base_apk)
    ], check=True)
    
    # Step 2: Change app name in AndroidManifest.xml
    print("[2/4] Changing app name...")
    manifest = WORK / "base_dec" / "AndroidManifest.xml"
    content = manifest.read_text()
    
    # Change app label
    content = content.replace(
        'android:label="@string/app_name"',
        f'android:label="{APP_NAME}"'
    )
    manifest.write_text(content)
    
    # Also update strings.xml if needed
    strings_xml = WORK / "base_dec" / "res" / "values" / "strings.xml"
    if strings_xml.exists():
        strings_content = strings_xml.read_text()
        strings_content = strings_content.replace(
            '<string name="app_name">King God Castle</string>',
            f'<string name="app_name">{APP_NAME}</string>'
        )
        strings_xml.write_text(strings_content)
    
    # Step 3: Recompile base APK
    print("[3/4] Recompiling base APK...")
    subprocess.run([
        "apktool", "b", "-f", "-o", str(WORK / "base_modified.apk"),
        str(WORK / "base_dec")
    ], check=True)
    
    # Step 4: Sign the APK
    print("[4/4] Signing APK...")
    keystore = REPO / ".debug.keystore"
    if not keystore.exists():
        keystore = pathlib.Path.home() / ".android" / "debug.keystore"
    
    subprocess.run([
        "apksigner", "sign",
        "--ks", str(keystore),
        "--ks-pass", "pass:android",
        "--key-pass", "pass:android",
        str(WORK / "base_modified.apk")
    ], check=True)
    
    # Copy to output
    output = REPO / "apk" / f"KingLocalCastle.apk"
    shutil.copy(WORK / "base_modified.apk", output)
    
    print(f"\n[✓] Built: {output}")
    print(f"    Install: adb install {output}")
    print(f"    Package: {NEW_PKG}")
    print(f"    Name: {APP_NAME}")

if __name__ == "__main__":
    main()
