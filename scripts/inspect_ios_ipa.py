#!/usr/bin/env python3
"""Inspect an iOS .ipa and answer one question before any mod work:

    Is the game's IL2CPP code patchable bytes-in-place, or does it need a
    decrypted dump first?

Two facts decide it:
  1. where the IL2CPP code lives (main binary vs Frameworks/GameAssembly.dylib),
  2. that binary's LC_ENCRYPTION_INFO_64 cryptid (1 = FairPlay-encrypted).

FairPlay normally encrypts only the main executable, so a Unity build whose game
code sits in an unencrypted dylib can be patched and re-signed with ESign without
any decryption step. This script tells you which case you are in, and prints the
RVA -> file-offset relation for the binary you will patch.

Usage:
  python3 scripts/inspect_ios_ipa.py [app.ipa]     # no arg: searches usual dirs
  python3 scripts/inspect_ios_ipa.py --selftest

Stdlib only. Does not modify anything.
"""
import os
import struct
import sys
import tempfile
import zipfile
import plistlib
from pathlib import Path

# --- Mach-O constants -------------------------------------------------------
THIN64_LE = b"\xcf\xfa\xed\xfe"
THIN32_LE = b"\xce\xfa\xed\xfe"
FAT32_BE = b"\xca\xfe\xba\xbe"
FAT64_BE = b"\xca\xfe\xba\xbf"

LC_SEGMENT = 0x1
LC_SEGMENT_64 = 0x19
LC_ENCRYPTION_INFO = 0x21
LC_ENCRYPTION_INFO_64 = 0x2C

CPU = {
    0x0100000C: "arm64",
    0x0200000C: "arm64_32",
    0x0000000C: "armv7",
    0x01000007: "x86_64",
    0x00000007: "i386",
}

# Strings that only exist in a binary containing IL2CPP-generated game code.
# "global-metadata.dat" is referenced by the Unity player itself, so it is only a
# weak hint - the strong ones live in the generated code.
IL2CPP_STRONG = (b"il2cpp_init", b"Il2CppCodeRegistration")
IL2CPP_WEAK = (b"global-metadata.dat",)


def _parse_thin(buf, off):
    """Parse one thin Mach-O at `off`. Returns dict or None if not a Mach-O."""
    magic = buf[off:off + 4]
    is64 = magic == THIN64_LE
    if not is64 and magic != THIN32_LE:
        return None
    if is64:
        hdr = struct.unpack_from("<8I", buf, off)
        p = off + 32
    else:
        hdr = struct.unpack_from("<7I", buf, off)
        p = off + 28
    cputype, ncmds = hdr[1], hdr[4]

    info = {"arch": CPU.get(cputype, f"cpu=0x{cputype:x}"), "cryptid": None,
            "text_vmaddr": None, "text_fileoff": None, "size": None}
    for _ in range(ncmds):
        if p + 8 > len(buf):
            break
        cmd, cmdsize = struct.unpack_from("<II", buf, p)
        if cmdsize < 8:
            break
        if cmd in (LC_ENCRYPTION_INFO, LC_ENCRYPTION_INFO_64) and cmdsize >= 20:
            _, _, cryptid = struct.unpack_from("<III", buf, p + 8)
            info["cryptid"] = cryptid
        elif cmd == LC_SEGMENT_64 and cmdsize >= 72:
            name = buf[p + 8:p + 24].rstrip(b"\0").decode("ascii", "replace")
            vmaddr, _vmsize, fileoff, filesize = struct.unpack_from("<4Q", buf, p + 24)
            if name == "__TEXT":
                info["text_vmaddr"], info["text_fileoff"], info["size"] = vmaddr, fileoff, filesize
        elif cmd == LC_SEGMENT and cmdsize >= 56:
            name = buf[p + 8:p + 24].rstrip(b"\0").decode("ascii", "replace")
            vmaddr, _vmsize, fileoff, filesize = struct.unpack_from("<4I", buf, p + 24)
            if name == "__TEXT":
                info["text_vmaddr"], info["text_fileoff"], info["size"] = vmaddr, fileoff, filesize
        p += cmdsize
    return info


def parse_macho(buf):
    """Entries: one per architecture. Raises ValueError if not a Mach-O at all."""
    magic = buf[:4]
    if magic in (FAT32_BE, FAT64_BE):
        n = struct.unpack_from(">I", buf, 4)[0]
        entries = []
        is64 = magic == FAT64_BE
        step = 32 if is64 else 20
        for i in range(n):
            p = 8 + i * step
            if is64:
                _cpu, _sub, off, size = struct.unpack_from(">IIQQ", buf, p)
            else:
                _cpu, _sub, off, size = struct.unpack_from(">IIII", buf, p)
            sub = parse_macho(buf[off:off + size])
            entries.extend(sub)
        return entries
    thin = _parse_thin(buf, 0)
    if thin is None:
        raise ValueError("not a Mach-O")
    return [thin]


def _il2cpp_markers(blob):
    """-> (all markers found, has_strong_marker)"""
    strong = [m.decode() for m in IL2CPP_STRONG if m in blob]
    weak = [m.decode() for m in IL2CPP_WEAK if m in blob]
    return strong + weak, bool(strong)


def inspect_ipa(path):
    """-> dict(bundle, version, exe, metadata, binaries=[...], verdict)"""
    out = {"path": str(path), "bundle": None, "version": None, "exe": None,
           "metadata": None, "binaries": [], "errors": []}
    with zipfile.ZipFile(path) as zf:
        app_roots = {n.split("/")[1] for n in zf.namelist()
                     if n.startswith("Payload/") and n.count("/") >= 2}
        if len(app_roots) != 1:
            raise SystemExit(f"expected one Payload/*.app, found {sorted(app_roots)}")
        app = f"Payload/{next(iter(app_roots))}/"

        info_path = app + "Info.plist"
        if info_path in zf.namelist():
            info = plistlib.loads(zf.read(info_path))
            out["bundle"] = info.get("CFBundleIdentifier")
            out["version"] = info.get("CFBundleShortVersionString")
            out["exe"] = info.get("CFBundleExecutable")

        names = zf.namelist()

        # IL2CPP metadata (always plain bytes, never encrypted).
        for n in names:
            if n.endswith("global-metadata.dat"):
                out["metadata"] = {"entry": n, "size": zf.getinfo(n).file_size}

        # Every file big enough to be a binary; classify by magic.
        for n in names:
            if not n.startswith(app) or n.endswith("/"):
                continue
            if "_CodeSignature" in n or n.endswith((".plist", ".png", ".json", ".dat")):
                continue
            zinfo = zf.getinfo(n)
            if zinfo.file_size < 4096:
                continue
            with zf.open(n) as fh:
                prefix = fh.read(4)
            if prefix not in (THIN64_LE, THIN32_LE, FAT32_BE, FAT64_BE):
                continue
            blob = zf.read(n)
            try:
                archs = parse_macho(blob)
            except ValueError as e:
                out["errors"].append(f"{n}: {e}")
                continue
            markers, strong = _il2cpp_markers(blob)
            for a in archs:
                a.update(entry=n, markers=markers, strong=strong,
                         is_exec=Path(n).name == (out["exe"] or ""),
                         name=Path(n).name)
                out["binaries"].append(a)

    out["verdict"] = _verdict(out)
    return out


def _verdict(res):
    strong = [b for b in res["binaries"] if b["strong"]]
    code = strong or [b for b in res["binaries"] if b["markers"] or b["name"] in
                      ("GameAssembly", "UnityFramework", "GameAssembly.dylib")]
    if not code:
        return "UNKNOWN: no binary carrying IL2CPP markers was found"
    encrypted = [b for b in code if b["cryptid"] == 1]
    if not encrypted:
        return "PATCHABLE: IL2CPP binary is not FairPlay-encrypted - patch bytes and re-sign, no decryption needed"
    if len(encrypted) == len(code):
        return "NEEDS DECRYPTION: the IL2CPP binary is FairPlay-encrypted (cryptid=1) - ESign cannot help"
    return "PARTIAL: some IL2CPP-carrying binaries are encrypted - patch the unencrypted one only"


def report(res):
    print(f"IPA      {res['path']}")
    print(f"bundle   {res['bundle']}  version {res['version']}")
    print(f"exe      {res['exe']}")
    if res["metadata"]:
        mb = res["metadata"]["size"] / 1e6
        print(f"metadata {res['metadata']['entry']}  ({mb:.1f} MB)")
    else:
        print("metadata MISSING (not an IL2CPP app?)")
    print("\nMACH-O")
    for b in res["binaries"]:
        enc = {None: "?", 0: "plain", 1: "ENCRYPTED"}.get(b["cryptid"], str(b["cryptid"]))
        mark = ",".join(b["markers"]) or "-"
        print(f"  {b['name']:<34} {b['arch']:<8} cryptid={b['cryptid']} ({enc:<9}) "
              f"text=0x{b['text_vmaddr'] or 0:x}+{b['text_fileoff']}  il2cpp:[{mark}]")
    for e in res["errors"]:
        print(f"  ! {e}")
    code = [b for b in res["binaries"] if b["strong"]] or \
           [b for b in res["binaries"] if b["markers"]]
    if code:
        c = code[0]
        print(f"\nRVA -> file offset for {c['name']}: "
              f"file = RVA - 0x{c['text_vmaddr']:x} + {c['text_fileoff']}")
    print(f"\nVERDICT  {res['verdict']}")


# --- self-test --------------------------------------------------------------
def _mk_thin(cryptid, markers=()):
    """Minimal 64-bit arm64 Mach-O: header + __TEXT + LC_ENCRYPTION_INFO_64."""
    seg = struct.pack("<II16s4Q4I", LC_SEGMENT_64, 72, b"__TEXT".ljust(16, b"\0"),
                      0x100000000, 0x1000, 0, 0x1000, 5, 5, 0, 0)
    enc = struct.pack("<IIIIII", LC_ENCRYPTION_INFO_64, 24, 0x4000, 0x100, cryptid, 0)
    hdr = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, 2, len(seg) + len(enc), 0, 0)
    body = b"\0" * 64 + b"".join(m + b"\0" for m in markers)
    return hdr + seg + enc + body + b"\0" * 8192


def _mk_ipa(dirpath, name, exe_bytes, extra=None):
    app = Path(dirpath) / f"{name}.app"
    app.mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps(
        {"CFBundleIdentifier": "com.awesomepiece.castle",
         "CFBundleShortVersionString": "174.0.00", "CFBundleExecutable": name}))
    (app / name).write_bytes(exe_bytes)
    meta = app / "Data" / "Managed" / "Metadata"
    meta.mkdir(parents=True)
    (meta / "global-metadata.dat").write_bytes(b"x" * 8192)
    for rel, blob in (extra or {}).items():
        p = app / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
    ipa = Path(dirpath) / f"{name}.ipa"
    with zipfile.ZipFile(ipa, "w") as zf:
        for p in app.rglob("*"):
            zf.write(p, "Payload/" + str(p.relative_to(dirpath)))
    return ipa


def selftest():
    with tempfile.TemporaryDirectory() as td:
        enc = inspect_ipa(_mk_ipa(td, "Game", _mk_thin(1, (b"il2cpp_init",))))
        assert "NEEDS DECRYPTION" in enc["verdict"], enc["verdict"]
        assert enc["binaries"][0]["cryptid"] == 1
        assert enc["binaries"][0]["text_vmaddr"] == 0x100000000

        plain = inspect_ipa(_mk_ipa(Path(td) / "b", "Game",
                                    _mk_thin(0, (b"il2cpp_init",))))
        assert "PATCHABLE" in plain["verdict"], plain["verdict"]
        assert plain["metadata"]["size"] == 8192

        # The realistic Unity-iOS shape: encrypted main binary that only mentions
        # global-metadata.dat, plus an unencrypted UnityFramework holding the code.
        uni = inspect_ipa(_mk_ipa(
            Path(td) / "c", "KingGodCastle",
            _mk_thin(1, (b"global-metadata.dat",)),
            {"Frameworks/UnityFramework.framework/UnityFramework":
             _mk_thin(0, (b"il2cpp_init", b"Il2CppCodeRegistration"))}))
        assert "PATCHABLE" in uni["verdict"], uni["verdict"]
        print("selftest ok: encrypted->NEEDS DECRYPTION, plain->PATCHABLE, "
              "encrypted-main+plain-framework->PATCHABLE")
    return 0


# --- main -------------------------------------------------------------------
def _find_ipa():
    here = Path.cwd()
    cands = []
    for d in (here, here / "apk", Path.home() / "Downloads", Path("/tmp/opencode")):
        if d.is_dir():
            cands += sorted(d.glob("*.ipa"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def main(argv):
    if "--selftest" in argv:
        return selftest()
    arg = next((a for a in argv[1:] if not a.startswith("-")), None)
    ipa = Path(arg) if arg else _find_ipa()
    if ipa is None:
        print("No .ipa given or found in cwd / apk / ~/Downloads / /tmp/opencode.")
        print("Get one with:  ipatool download --bundle-id com.awesomepiece.castle")
        print("(needs an authenticated Apple ID that has the app in its library)")
        return 2
    report(inspect_ipa(ipa))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
