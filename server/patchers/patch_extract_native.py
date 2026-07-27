#!/usr/bin/env python3
"""
Set android:extractNativeLibs=true in the decoded AndroidManifest so that
System.loadLibrary() can find libxigncode.so in the native lib directory.
extractNativeLibs=false (Unity default) stores all .so inside the APK zip;
Java's loadLibrary requires them extracted on some Android versions.
"""
import sys, subprocess, tempfile, shutil, pathlib

APK = pathlib.Path(sys.argv[1]).resolve()

work = pathlib.Path(tempfile.mkdtemp(prefix="extnat_"))
dec = work / "dec"
try:
    subprocess.run(["apktool", "d", "-s", "-f", str(APK), "-o", str(dec)],
                   check=True, stdout=subprocess.DEVNULL)

    manifest = dec / "AndroidManifest.xml"
    txt = manifest.read_text(encoding="utf-8")

    # extractNativeLibs=false -> true
    # Format: android:extractNativeLibs(0x010104ea)=(type 0x12)0x0
    # After decompile by apktool it appears as: android:extractNativeLibs="false"
    txt = txt.replace('android:extractNativeLibs="false"', 'android:extractNativeLibs="true"')
    hits = txt.count('android:extractNativeLibs="true"')
    if hits == 0:
        # Try adding it if not present (add to <application> tag)
        txt = txt.replace('<application', '<application android:extractNativeLibs="true"', 1)
        print(f"[+] {APK.name}: added android:extractNativeLibs=true to <application>")
    else:
        print(f"[+] {APK.name}: set android:extractNativeLibs=true ({hits}x)")

    manifest.write_text(txt, encoding="utf-8")

    out = work / "rebuilt.apk"
    subprocess.run(["apktool", "b", str(dec), "-o", str(out)],
                   check=True, stdout=subprocess.DEVNULL)
    shutil.copy(out, APK)
    print(f"[+] rebuilt: {APK}")
finally:
    shutil.rmtree(work, ignore_errors=True)
