#!/usr/bin/env python3
"""
Regenerate il2cpp/v171.0.00/libil2cpp_v171_ssl.so from the pristine recovered
libil2cpp_v171.so + exactly the 3 SSL-bypass patches. Nothing else.

This file is the input build_v171_private.py injects into the APK, and it MUST
stay pristine. It rotted once (2026-07-19) after being hand-patched across
several sessions: 21 stray bytes, one of which overwrote `mov w8,#-2` with a
`b 0x3503ba8` inside Scene_Login.<CheckUseAssetBundle>d__79.MoveNext, producing
an infinite UniTask recursion and a stack-overflow SIGSEGV that looked exactly
like an engine bug. Two sessions were lost to it. Regenerate here instead of
patching in place, and the class of bug cannot come back.

    python3 server/patchers/make_v171_ssl_so.py [VERSION] [--check]

VERSION is a directory under il2cpp/ (default 171.1.00). --check verifies the
existing file instead of writing (exit 1 on mismatch).

NOTE: the offsets below are RAW FILE OFFSETS, not RVAs. Every other v171 patch
in this repo uses `RVA - 0x4000` (see AGENTS.md). Do not mix the two.
"""
import pathlib, sys

REPO = pathlib.Path(__file__).resolve().parents[2]

RET_TRUE = bytes.fromhex("20008052c0035fd6")  # mov w0,#1 ; ret

# Per-version: the 3 SSL entry points and a couple of untouched anchors. Offsets
# come from that version's own dump.cs (`RVA - 0x4000`); they do NOT carry across
# a version bump, and reusing them silently patches unrelated code.
VERSIONS = {
    "171.0.00": dict(
        src="libil2cpp_v171.so", dst="libil2cpp_v171_ssl.so",
        ssl=[(0x2CB68D8, "PinnedCertHandler.ValidateCertificate"),
             (0x596EF64, "UnityTlsProvider.ValidateCertificate"),
             (0x596D674, "MobileTlsContext.ValidateCertificate")],
        anchors=[(0x303C6C0, "fe0f1bf8", "GameManager.CheckFirebase prologue"),
                 (0x34FFB7C, "28008012", "CheckUseAssetBundle.MoveNext `mov w8,#-2`")],
    ),
    # Recovered by server/patchers/unpack_neo.py straight out of the v171.1.00
    # packer, so this pairs with the SHIPPED global-metadata.dat - no metadata
    # swap needed, unlike the v171.0.00 lib.
    "171.1.00": dict(
        src="libil2cpp_v17110.so", dst="libil2cpp_v17110_ssl.so",
        ssl=[(0x2CB6E24, "PinnedCertHandler.ValidateCertificate"),
             (0x59702A4, "UnityTlsProvider.ValidateCertificate"),
             (0x596E9B4, "MobileTlsContext.ValidateCertificate")],
        anchors=[(0x2CB6E24, "fe5fbda9", "PinnedCertHandler prologue (pre-patch)")],
    ),
    # Recovered by server/patchers/unpack_neo.py from the v172.0.00 packer
    # (libbeniolle.so). All 3 prologues byte-identical to v171.1.00, so the
    # method mapping is confirmed - only the offsets moved.
    "172.0.00": dict(
        src="libil2cpp_v172.so", dst="libil2cpp_v172_ssl.so",
        ssl=[(0x2CB9FB4, "PinnedCertHandler.ValidateCertificate"),
             (0x597A494, "UnityTlsProvider.ValidateCertificate"),
             (0x5978BA4, "MobileTlsContext.ValidateCertificate")],
        anchors=[(0x2CB9FB4, "fe5fbda9", "PinnedCertHandler prologue (pre-patch)")],
    ),
    # Recovered from the v172.0.01 packer (libpouricol.so). All 3 prologues
    # byte-identical again (fe5fbda9 / ff0302d1 / fe0f1ff8), only offsets moved.
    "172.0.01": dict(
        src="libil2cpp_v17201.so", dst="libil2cpp_v17201_ssl.so",
        ssl=[(0x2CBAEB0, "PinnedCertHandler.ValidateCertificate"),
             (0x597BDE8, "UnityTlsProvider.ValidateCertificate"),
             (0x597A4F8, "MobileTlsContext.ValidateCertificate")],
        anchors=[(0x2CBAEB0, "fe5fbda9", "PinnedCertHandler prologue (pre-patch)")],
    ),
}

VERSION = next((a for a in sys.argv[1:] if not a.startswith("-")), "171.1.00")
if VERSION not in VERSIONS:
    sys.exit(f"unknown version {VERSION}; known: {', '.join(VERSIONS)}")
_V = VERSIONS[VERSION]
SRC = REPO / "il2cpp" / f"v{VERSION}" / _V["src"]
DST = REPO / "il2cpp" / f"v{VERSION}" / _V["dst"]
SSL_PATCHES = _V["ssl"]
# An anchor that names a site we are about to patch is only meaningful pre-patch.
ANCHORS = [a for a in _V["anchors"] if a[0] not in {o for o, _ in SSL_PATCHES}]


def build():
    data = bytearray(SRC.read_bytes())
    for off, name in SSL_PATCHES:
        data[off:off + len(RET_TRUE)] = RET_TRUE
        print(f"  [+] {name} @ 0x{off:x} -> RET_TRUE")
    return bytes(data)


def check(data):
    ok = True
    for off, name in SSL_PATCHES:
        if data[off:off + len(RET_TRUE)] != RET_TRUE:
            print(f"  [!] MISSING ssl patch: {name} @ 0x{off:x}")
            ok = False
    for off, want, name in ANCHORS:
        got = data[off:off + len(want) // 2].hex()
        if got != want:
            print(f"  [!] CORRUPT: {name} @ 0x{off:x} = {got}, want {want}")
            ok = False
    # Anything else differing from pristine is rot. Skipped when the pristine lib
    # is not on disk - v171.0.00's was lost to a `git clean -fdx` and only the
    # patched copy survives, which is still worth the patch/anchor checks above.
    if not SRC.exists():
        print(f"  [~] {SRC.name} absent - skipping the stray-byte diff")
        return ok
    plain = SRC.read_bytes()
    patched = {o for off, _ in SSL_PATCHES for o in range(off, off + len(RET_TRUE))}
    stray = [i for i in range(len(plain)) if plain[i] != data[i] and i not in patched]
    if stray:
        print(f"  [!] {len(stray)} stray byte(s) vs pristine, first at 0x{stray[0]:x}")
        ok = False
    return ok


if __name__ == "__main__":
    if "--check" in sys.argv:
        if not DST.exists():
            sys.exit(f"{DST} missing - run without --check to build it")
        print(f"[*] Checking {DST.name}...")
        sys.exit(0 if check(DST.read_bytes()) else 1)
    print(f"[*] Building {DST.name} from {SRC.name}...")
    out = build()
    assert check(out), "freshly built file failed its own check"
    DST.write_bytes(out)
    print(f"[+] wrote {DST} ({len(out)} bytes)")
