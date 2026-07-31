#!/usr/bin/env python3
"""
Swap the global-metadata.dat inside an APK for a different one.

Why this exists: v171.0.01 inserted one string literal ("/auth/xcdSeed?version=")
at stringLiteral index 1545 of 25730 - an INSERT, not an append - so every literal
from 1545 on shifts index by one. libil2cpp.so has those indices baked into its
code, so the v171.0.00 lib we inject can only run against the v171.0.00 metadata.
Everything else in the two metadata files is byte-identical except attributeData
(same size) and the +8/+8 the new literal costs.

The entry is STORED, so we splice it in place and fix the CRC in both the local
header and the central directory - the same mechanism patch_metadata_http.py uses.
The replacement is zero-padded up to the original stored size; il2cpp addresses
every section through the header, so trailing bytes are inert.

Usage: python3 patch_metadata_swap.py <apk> <replacement_global-metadata.dat>
"""
import sys, struct, pathlib, zipfile, zlib

APK = pathlib.Path(sys.argv[1])
NEW = pathlib.Path(sys.argv[2])

with zipfile.ZipFile(APK, "r") as z:
    entry = next((e for e in z.namelist() if e.endswith("global-metadata.dat")), None)
    if entry is None:
        sys.exit(f"[!] no global-metadata.dat in {APK}")
    info = z.getinfo(entry)

if info.compress_type != 0:
    sys.exit(f"[!] {entry} is compressed (type={info.compress_type}) - cannot splice in place")

new = bytearray(NEW.read_bytes())
sanity, version = struct.unpack_from("<II", new, 0)
if sanity != 0xFAB11BAF:
    sys.exit(f"[!] {NEW} is not il2cpp metadata (sanity {sanity:#x})")
if len(new) > info.file_size:
    sys.exit(f"[!] replacement is {len(new) - info.file_size} B larger than the stored entry "
             f"({len(new)} > {info.file_size}) - cannot splice without rewriting the zip")
pad = info.file_size - len(new)
new.extend(b"\0" * pad)

apk = bytearray(APK.read_bytes())
hdr = info.header_offset
name_len, extra_len = struct.unpack_from("<HH", apk, hdr + 26)
start = hdr + 30 + name_len + extra_len
apk[start:start + info.file_size] = new

crc = zlib.crc32(bytes(new)) & 0xFFFFFFFF
struct.pack_into("<I", apk, hdr + 14, crc)
tgt = entry.encode()
pos = start + info.file_size
while True:
    pos = apk.find(b"PK\x01\x02", pos)
    if pos < 0:
        sys.exit(f"[!] central directory entry for {entry} not found - CRC left stale")
    n = struct.unpack_from("<H", apk, pos + 28)[0]
    if bytes(apk[pos + 46:pos + 46 + n]) == tgt:
        struct.pack_into("<I", apk, pos + 16, crc)
        break
    pos += 1

APK.write_bytes(apk)
print(f"[+] swapped {entry} <- {NEW.name} (metadata v{version}, "
      f"{len(new) - pad} B + {pad} B pad, crc 0x{crc:08x})")
