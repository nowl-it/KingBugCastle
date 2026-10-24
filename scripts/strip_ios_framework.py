#!/usr/bin/env python3
"""Strip an embedded .framework from an iOS .ipa without decrypting anything.

Why: iOS anti-cheat (xigncode) kills the process at dyld-init time when the app
is re-signed (docs/dev-notes.md §74). This removes the framework so we can learn
whether the game boots without it.

What it does, per Mach-O that links the framework:
  * rewrites LC_LOAD_DYLIB -> LC_LOAD_WEAK_DYLIB (0xC -> 0x80000018) so dyld
    silently skips the missing library instead of aborting,
  * drops every Payload/*.app/Frameworks/<name>.framework/ entry.

Load commands live in the Mach-O header, which FairPlay does NOT encrypt, so an
encrypted App Store binary can be edited here without a decrypted dump.

Usage:
  python3 scripts/strip_ios_framework.py in.ipa out.ipa [--framework xigncode]
  python3 scripts/strip_ios_framework.py --selftest
"""
import struct
import sys
import zipfile
from pathlib import Path

THIN64 = b"\xcf\xfa\xed\xfe"
THIN32 = b"\xce\xfa\xed\xfe"
FAT32 = b"\xca\xfe\xba\xbe"
FAT64 = b"\xca\xfe\xba\xbf"

LC_LOAD_DYLIB = 0xC
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_SEGMENT = 0x1
LC_SEGMENT_64 = 0x19
DYLIB_CMDS = {0xC, 0x80000018, 0x8000001F, 0x20, 0x80000023}


def _thin_slices(buf):
    """-> list of (offset, size) covering each Mach-O image in buf."""
    magic = buf[:4]
    if magic in (FAT32, FAT64):
        n = struct.unpack_from(">I", buf, 4)[0]
        is64 = magic == FAT64
        step = 32 if is64 else 20
        out = []
        for i in range(n):
            p = 8 + i * step
            if is64:
                _c, _s, off, size = struct.unpack_from(">IIQQ", buf, p)
            else:
                _c, _s, off, size = struct.unpack_from(">IIII", buf, p)
            out.append((off, size))
        return out
    if magic in (THIN64, THIN32):
        return [(0, len(buf))]
    return []


def _patch_slice(buf, base, framework):
    """Weaken every dylib load command naming `framework`. -> list of paths patched."""
    is64 = buf[base:base + 4] == THIN64
    hdr = struct.unpack_from("<8I" if is64 else "<7I", buf, base)
    ncmds = hdr[4]
    p = base + (32 if is64 else 28)
    patched = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", buf, p)
        if cmdsize < 8:
            break
        if cmd in DYLIB_CMDS and cmdsize >= 24:
            name_off = struct.unpack_from("<I", buf, p + 8)[0]
            if 0 < name_off < cmdsize:
                raw = buf[p + name_off:p + cmdsize].split(b"\0", 1)[0]
                path = raw.decode("utf-8", "replace")
                if framework in path:
                    if cmd != LC_LOAD_WEAK_DYLIB:
                        struct.pack_into("<I", buf, p, LC_LOAD_WEAK_DYLIB)
                    patched.append(path)
        p += cmdsize
    return patched


def strip(ipa_in, ipa_out, framework="xigncode"):
    src = zipfile.ZipFile(ipa_in)
    dropped, patched = [], {}
    with zipfile.ZipFile(ipa_out, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as dst:
        for info in src.infolist():
            name = info.filename
            if f"/Frameworks/{framework}.framework/" in name:
                dropped.append(name)
                continue
            data = bytearray(src.read(name))
            if name.startswith("Payload/") and not name.endswith("/"):
                for off, size in _thin_slices(data):
                    hits = _patch_slice(data, off, framework)
                    if hits:
                        patched.setdefault(name, []).extend(hits)
            dst.writestr(name, data)
    return dropped, patched


# --- self-test --------------------------------------------------------------
def _mk_app(path, extra_dylib=None):
    """Minimal arm64 Mach-O; `extra_dylib` is an LC_LOAD_DYLIB path to link."""
    seg = struct.pack("<II16s4Q4I", LC_SEGMENT_64, 72, b"__TEXT".ljust(16, b"\0"),
                      0x100000000, 0x1000, 0, 0x1000, 5, 5, 0, 0)
    cmds = seg
    n = 1
    if extra_dylib:
        body = extra_dylib + b"\0"
        cmdsize = (24 + len(body) + 7) & ~7
        cmds += struct.pack("<IIIIII", LC_LOAD_DYLIB, cmdsize, 24, 0, 0x10000, 0x10000) \
            + body.ljust(cmdsize - 24, b"\0")
        n = 2
    hdr = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, n, len(cmds), 0, 0)
    return hdr + cmds + b"\0" * 8192


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        app = td / "Payload" / "Game.app"
        (app / "Frameworks" / "xigncode.framework").mkdir(parents=True)
        (app / "Info.plist").write_bytes(b"<plist/>")
        (app / "Frameworks" / "xigncode.framework" / "xigncode").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 8192)
        exe = _mk_app("Game", b"@rpath/xigncode.framework/xigncode")
        (app / "Game").write_bytes(exe)
        src = td / "in.ipa"
        with zipfile.ZipFile(src, "w") as z:
            for p in app.rglob("*"):
                z.write(p, "Payload/" + str(p.relative_to(td / "Payload")))
        out = td / "out.ipa"
        dropped, patched = strip(src, out, "xigncode")

        assert dropped, "framework entries were not dropped"
        assert patched, "dylib load command was not patched"
        b = zipfile.ZipFile(out).read("Payload/Game.app/Game")
        cmd = struct.unpack_from("<I", b, 32 + 72)[0]   # header + __TEXT cmd
        assert cmd == LC_LOAD_WEAK_DYLIB, hex(cmd)
        names = zipfile.ZipFile(out).namelist()
        assert not any("xigncode.framework" in n for n in names)
        print(f"selftest ok: dropped={len(dropped)} patched={patched}")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv[1:] if not a.startswith("--")]
    fw = "xigncode"
    if "--framework" in argv:
        fw = argv[argv.index("--framework") + 1]
    if len(args) < 2:
        print(__doc__)
        return 2
    dropped, patched = strip(args[0], args[1], fw)
    print(f"dropped {len(dropped)} entries under Frameworks/{fw}.framework/")
    for n, paths in patched.items():
        for p in paths:
            print(f"  weak-linked in {n}: {p}")
    if not patched:
        print("WARNING: no Mach-O linked the framework - it may be loaded via dlopen;"
              " the app will still try to find it at runtime")
    print(f"wrote {args[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
