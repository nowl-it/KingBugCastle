#!/usr/bin/env python3
"""
Rename the package ID inside a split APK's AndroidManifest.xml without
apktool (split manifests lack full resource context, so aapt2 link fails
on rebuild). Edits the binary AXML string-pool entry in place - shrinks
the UTF-16 string + its length prefix and zero-pads the freed tail so no
other string-pool offset shifts - then rewrites the whole zip, copying
every other entry's raw bytes verbatim (cheap: assets are ZIP_STORED).

Usage: python3 patch_package_id_light.py <apk> <old_pkg> <new_pkg>
"""
import sys, zipfile, struct, pathlib, shutil

APK = pathlib.Path(sys.argv[1]).resolve()
OLD = sys.argv[2]
NEW = sys.argv[3]
assert len(NEW) <= len(OLD), "light patcher only shrinks/keeps length equal"


def patch_axml(data: bytes) -> bytes:
    old_u16 = OLD.encode("utf-16-le")
    new_u16 = NEW.encode("utf-16-le")
    pad = len(old_u16) - len(new_u16)
    replacement = struct.pack("<H", len(NEW)) + new_u16 + b"\x00\x00" + b"\x00" * pad

    out = bytearray(data)
    hits = 0
    pos = 0
    while True:
        pos = bytes(out).find(old_u16, pos)
        if pos < 0:
            break
        prefix = struct.unpack_from("<H", out, pos - 2)[0]
        if prefix == len(OLD):
            slot_start = pos - 2
            slot_len = 2 + len(old_u16) + 2  # len-prefix + chars + NUL terminator
            out[slot_start: slot_start + slot_len] = replacement
            hits += 1
        pos += 1
    assert hits >= 1, f"{OLD!r} not found as a length-prefixed UTF-16 string"
    print(f"[+] AndroidManifest.xml: patched {hits}x string-pool entr(y/ies)")
    return bytes(out)


def main():
    tmp = APK.with_suffix(APK.suffix + ".tmp")
    with zipfile.ZipFile(APK) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "AndroidManifest.xml":
                data = patch_axml(data)
            zout.writestr(info, data)
    shutil.move(str(tmp), str(APK))
    print(f"[+] rebuilt: {APK}")


if __name__ == "__main__":
    main()
