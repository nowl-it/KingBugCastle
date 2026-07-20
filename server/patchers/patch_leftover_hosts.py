#!/usr/bin/env python3
"""
Raw-rebind ANY remaining real backend-host URL in an APK's global-metadata.dat to
http://127.0.0.1 (path preserved), null-padded to the original byte length so no
metadata offset shifts.

patch_hosts.py only scans the stringLiteral TABLE; it cannot reach host strings stored
as field/parameter default values (the "vestigial" copies). Those are what make the v171
client still reach the real castle-infra service-discovery host + real CDN at runtime, so
it must go through this raw pass too. Same-length in-place edit -> only CRC needs fixing.

Usage: python3 patch_leftover_hosts.py <base_assets.apk> [target]   (target default 127.0.0.1)
"""
import sys, struct, zipfile, zlib, pathlib

APK = pathlib.Path(sys.argv[1])
TARGET = (sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1").encode()

HOSTS = [
    b"castle-infra-server-65408603887.asia-northeast3.run.app",
    b"isekai-lobbyserver.awesomepiece.com",
    b"axis-game.awesomepiece.com",
    b"kgc-k8s-1.awesomepiece.com",
    b"kgc-cdn-1.awesomepiece.com",
]

with zipfile.ZipFile(APK) as z:
    entry = next(e for e in z.namelist() if e.endswith("global-metadata.dat"))
    info = z.getinfo(entry)
assert info.compress_type == 0, f"{entry} is compressed - cannot in-place patch"

apk = bytearray(APK.read_bytes())
hdr = info.header_offset
fn = struct.unpack_from("<H", apk, hdr + 26)[0]
ex = struct.unpack_from("<H", apk, hdr + 28)[0]
ms = hdr + 30 + fn + ex
me = ms + info.file_size
data = apk[ms:me]

patched = 0
for host in HOSTS:
    pos = 0
    while True:
        p = data.find(host, pos)
        if p < 0:
            break
        # walk back over an immediately-preceding "https://" or "http://" scheme
        scheme_start = p
        for scheme in (b"https://", b"http://"):
            if data[p - len(scheme):p] == scheme:
                scheme_start = p - len(scheme)
                break
        # the URL runs until NUL or a non-URL byte
        end = p + len(host)
        while end < len(data) and data[end] not in (0,) and 0x21 <= data[end] < 0x7f:
            end += 1
        old = bytes(data[scheme_start:end])
        # keep whatever path followed the host (e.g. "/patch/")
        path = old[old.find(host) + len(host):]
        new = b"http://" + TARGET + path
        if len(new) > (end - scheme_start):
            pos = end
            continue  # replacement wouldn't fit; leave it
        data[scheme_start:scheme_start + len(new)] = new
        data[scheme_start + len(new):end] = b"\x00" * (end - scheme_start - len(new))
        print(f"[+] {old.decode('utf-8','replace')!r} -> {new.decode()!r}")
        patched += 1
        pos = end

if patched == 0:
    print("[=] no leftover real-host URLs found (already clean)")
    sys.exit(0)

apk[ms:me] = data
crc = zlib.crc32(bytes(data)) & 0xFFFFFFFF
struct.pack_into("<I", apk, hdr + 14, crc)
tgt = entry.encode()
pos = me
while pos < len(apk) - 4:
    if apk[pos:pos + 4] == b"PK\x01\x02":
        l = struct.unpack_from("<H", apk, pos + 28)[0]
        if bytes(apk[pos + 46:pos + 46 + l]) == tgt:
            struct.pack_into("<I", apk, pos + 16, crc)
            break
    pos += 1
APK.write_bytes(apk)
print(f"[+] rebound {patched} leftover URL(s); CRC {crc:#010x}")
