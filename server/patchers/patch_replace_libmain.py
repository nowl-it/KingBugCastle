#!/usr/bin/env python3
"""
Replace libmain.so with our wrapper that dlopen("libxigncode.so") first.
Original libmain.so gets renamed to libmain_real.so (our wrapper loads it).
"""
import sys, subprocess, tempfile, shutil, pathlib, zipfile

WRAPPER = pathlib.Path(__file__).resolve().parent.parent / "jni" / "libmain_wrapper.so"
APK = pathlib.Path(sys.argv[1]).resolve()

if not WRAPPER.exists():
    print(f"ERROR: wrapper not found at {WRAPPER}")
    sys.exit(1)

# The wrapper .so is committed prebuilt (arm64, ABI-stable) so users need no NDK.
# Only recompile if it's missing, or if KGC_REBUILD_NATIVE=1 is set (dev, after
# editing the .cpp). NDK path is auto-detected across OSes / versions.
import os
if not WRAPPER.exists() or os.environ.get("KGC_REBUILD_NATIVE"):
    src = WRAPPER.with_suffix(".cpp")
    ndk_root = os.environ.get("ANDROID_NDK_HOME") or os.environ.get("NDK_HOME")
    cc = None
    search = [pathlib.Path(ndk_root)] if ndk_root else sorted(
        (pathlib.Path.home() / "Android/Sdk/ndk").glob("*"), reverse=True)
    for nd in search:
        for host in ("linux-x86_64", "darwin-x86_64", "windows-x86_64"):
            cand = nd / "toolchains/llvm/prebuilt" / host / "bin"
            for exe in ("aarch64-linux-android21-clang", "aarch64-linux-android21-clang.cmd"):
                if (cand / exe).exists():
                    cc = cand / exe; break
            if cc: break
        if cc: break
    if not cc:
        print("ERROR: libmain_wrapper.so missing and no NDK found "
              "(set ANDROID_NDK_HOME). The prebuilt .so should be committed.")
        sys.exit(1)
    try:
        subprocess.run([str(cc), "-shared", "-fPIC", "-o", str(WRAPPER), str(src),
                        "-llog", "-ldl", "-Wl,--no-undefined"], check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("ERROR: NDK build failed"); sys.exit(1)

orig_size = 0
with zipfile.ZipFile(APK, "r") as z:
    info = z.getinfo("lib/arm64-v8a/libmain.so")
    orig_size = info.file_size

wrapper_data = WRAPPER.read_bytes()

# Read original libmain.so data
with zipfile.ZipFile(APK, "r") as z:
    orig_libmain = z.read("lib/arm64-v8a/libmain.so")

# Build new APK
tmp = pathlib.Path(tempfile.mktemp(suffix=".apk"))
with zipfile.ZipFile(APK, "r") as zin:
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            name = item.filename
            data = zin.read(name)

            if name == "lib/arm64-v8a/libmain.so":
                # Add our wrapper as libmain.so
                zout.writestr(
                    zipfile.ZipInfo("lib/arm64-v8a/libmain.so"),
                    wrapper_data
                )
                print(f"[+] replaced {name}: {orig_size}B -> {len(wrapper_data)}B")

                # Add original as libmain_real.so
                zout.writestr(
                    zipfile.ZipInfo("lib/arm64-v8a/libmain_real.so"),
                    orig_libmain
                )
                print(f"[+] added lib/arm64-v8a/libmain_real.so: {len(orig_libmain)}B")
            else:
                zout.writestr(item, data)

shutil.move(tmp, APK)
print(f"[+] updated: {APK}")
