#!/usr/bin/env python3
"""
Rename the app display label inside a (split) base APK to a new label for EVERY
locale. The app_name string resource has per-locale overrides (ko/ja/zh/fr/...),
so a single in-place byte swap only fixes one locale; we decode with apktool,
set every app_name value, and rebuild. Package name is left unchanged.

Usage: python3 patch_rename.py <base_apk> ["New Label"]
Default new label: "King Bug Castle". Rebuilds the APK in place (unsigned).
"""
import sys, subprocess, tempfile, shutil, pathlib, re

APK = pathlib.Path(sys.argv[1]).resolve()
NEW = sys.argv[2] if len(sys.argv) > 2 else "King Bug Castle"

work = pathlib.Path(tempfile.mkdtemp(prefix="rename_"))
dec = work / "dec"
try:
    # -s: don't decode dex (faster, no smali rebuild risk; base code stays verbatim)
    subprocess.run(["apktool", "d", "-s", "-f", str(APK), "-o", str(dec)],
                   check=True, stdout=subprocess.DEVNULL)

    pat = re.compile(r'(<string name="app_name">).*?(</string>)', re.S)
    repl = r'\g<1>' + NEW.replace('\\', r'\\') + r'\g<2>'
    hits = 0
    for f in (dec / "res").rglob("strings.xml"):
        txt = f.read_text(encoding="utf-8")
        new, n = pat.subn(repl, txt)
        if n:
            f.write_text(new, encoding="utf-8")
            hits += n
    assert hits >= 1, "app_name not found in any strings.xml"
    print(f"[+] set app_name -> {NEW!r} in {hits} locale value(s)")

    out = work / "rebuilt.apk"
    subprocess.run(["apktool", "b", str(dec), "-o", str(out)],
                   check=True, stdout=subprocess.DEVNULL)
    shutil.copy(out, APK)
    print(f"[+] rebuilt: {APK}")
finally:
    shutil.rmtree(work, ignore_errors=True)
