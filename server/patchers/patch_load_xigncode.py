#!/usr/bin/env python3
"""
Patch MainActivity smali to force-load libxigncode.so via System.loadLibrary.
The game skips XIGNCODE init on emulators; this bypasses that check.
"""
import sys, subprocess, tempfile, shutil, pathlib, re

APK = pathlib.Path(sys.argv[1]).resolve()

work = pathlib.Path(tempfile.mkdtemp(prefix="xignload_"))
dec = work / "dec"
try:
    subprocess.run(["apktool", "d", "-f", str(APK), "-o", str(dec)],
                   check=True, stdout=subprocess.DEVNULL)

    matches = list(dec.rglob("MainActivity.smali"))
    if not matches:
        print(f"ERROR: MainActivity.smali not found in {dec}")
        sys.exit(1)
    main_act = matches[0]

    txt = main_act.read_text(encoding="utf-8")

    if "loadLibrary" in txt and "xigncode" in txt:
        print(f"[+] {main_act.name}: already patched, skipping")
    else:
        pat = re.compile(r'(\.method .*onCreate\(Landroid/os/Bundle;\)V\s*\n\s*\.(?:locals|registers) \d+\s*\n)')
        m = pat.search(txt)
        if not m:
            print(f"ERROR: onCreate method not found in {main_act}")
            sys.exit(1)

        body = (
            '    const-string v0, "xigncode"\n'
            '    invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V\n'
        )
        pos = m.end()
        txt = txt[:pos] + body + txt[pos:]
        main_act.write_text(txt, encoding="utf-8")
        print(f"[+] {main_act.name}: injected System.loadLibrary(\"xigncode\") in onCreate")

    out = work / "rebuilt.apk"
    subprocess.run(["apktool", "b", str(dec), "-o", str(out)],
                   check=True, stdout=subprocess.DEVNULL)
    shutil.copy(out, APK)
    print(f"[+] rebuilt: {APK}")
finally:
    shutil.rmtree(work, ignore_errors=True)
