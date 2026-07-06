#!/usr/bin/env python3
"""
Rename the package ID inside an APK (base or split) so it can be installed
side-by-side with the real app. Decodes with apktool, replaces every literal
occurrence of the old package name in AndroidManifest.xml (package attr,
split attr, provider authorities, permission names), rebuilds in place.

Usage: python3 patch_package_id.py <apk> <old_pkg> <new_pkg>
"""
import sys, subprocess, tempfile, shutil, pathlib, re

APK = pathlib.Path(sys.argv[1]).resolve()
OLD = sys.argv[2]
NEW = sys.argv[3]

work = pathlib.Path(tempfile.mkdtemp(prefix="pkgid_"))
dec = work / "dec"
try:
    subprocess.run(["apktool", "d", "-s", "-f", str(APK), "-o", str(dec)],
                   check=True, stdout=subprocess.DEVNULL)

    manifest = dec / "AndroidManifest.xml"
    txt = manifest.read_text(encoding="utf-8")
    # Rename app identity (package=, provider authorities=, intent-filter data
    # scheme=) but NOT android:name=/android:value= occurrences - those are
    # references to compiled dex classes (e.g. MainActivity), which keep
    # their original FQN regardless of the manifest's declared package.
    pat = re.compile(r'(?<!android:name=")(?<!android:value=")' + re.escape(OLD))
    hits = len(pat.findall(txt))
    assert hits >= 1, f"{OLD!r} not found (outside class refs) in {manifest}"
    manifest.write_text(pat.sub(NEW, txt), encoding="utf-8")
    print(f"[+] {APK.name}: replaced {hits}x {OLD!r} -> {NEW!r} in AndroidManifest.xml (class refs left intact)")

    out = work / "rebuilt.apk"
    subprocess.run(["apktool", "b", str(dec), "-o", str(out)],
                   check=True, stdout=subprocess.DEVNULL)
    shutil.copy(out, APK)
    print(f"[+] rebuilt: {APK}")
finally:
    shutil.rmtree(work, ignore_errors=True)
