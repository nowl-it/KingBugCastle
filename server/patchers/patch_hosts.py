#!/usr/bin/env python3
"""
Rebind KGC backend hostnames inside global-metadata.dat to YOUR server host, so a
shared client talks to your server with NO per-device /etc/hosts edit and NO adb
reverse. This is what makes the XAPK work for remote players.

All 5 backend hosts (axis-game / kgc-k8s-1 / isekai-lobbyserver / kgc-cdn-1 /
castle-infra) live only in global-metadata.dat (NOT libil2cpp.so). Each is an
il2cpp string literal (uint32 length + int32 dataIndex, string bytes at
stringLiteralDataOffset + dataIndex). We replace the host substring in-place,
zero-pad the freed tail, and update the literal's length field - the same shrink
mechanism as patch_metadata_http.py. Scheme is left as-is (https): the SSL-bypass
byte patches make the client accept any cert, so you serve TLS on :443 with the
self-signed cert. All hosts collapse to ONE target - server.py already answers
every path + the CDN under /patch (that's how the local all-hosts->127.0.0.1 setup
already works).

Target must be <= 26 chars (shortest original host) so every literal shrinks. An
IPv4 (<=15) always fits; a domain must be <= 26 chars. No port - the client uses
the default 443, so expose your server on 443 (forward if needed).

Usage: python3 patch_hosts.py <base_assets.apk> <target_host>
       e.g. python3 patch_hosts.py base_assets.apk 203.0.113.7
       e.g. python3 patch_hosts.py base_assets.apk kgc.example.com
"""
import sys
import struct
import pathlib
import zipfile
import zlib

HOSTS = [
    b"castle-infra-server-65408603887.asia-northeast3.run.app",  # longest first (avoid partial)
    b"isekai-lobbyserver.awesomepiece.com",
    b"axis-game.awesomepiece.com",
    b"kgc-k8s-1.awesomepiece.com",
    b"kgc-cdn-1.awesomepiece.com",
]
MAXLEN = min(len(h) for h in HOSTS)  # 26


def _section_offsets(data):
    """(stringLiteralOffset, count, dataOffset, dataCount) from the il2cpp header."""
    sz = len(data)
    for base in (8, 16):
        off = struct.unpack_from('<i', data, base)[0]
        cnt = struct.unpack_from('<i', data, base + 4)[0]
        doff = struct.unpack_from('<i', data, base + 8)[0]
        dcnt = struct.unpack_from('<i', data, base + 12)[0]
        if 0 < off < sz and 0 < doff < sz and cnt > 0:
            return off, cnt, doff, dcnt
    raise ValueError("could not locate stringLiteral sections in metadata header")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    apk = pathlib.Path(sys.argv[1])
    target = sys.argv[2].strip().encode()
    if len(target) > MAXLEN:
        sys.exit(f"[!] target host '{target.decode()}' is {len(target)} chars > {MAXLEN} limit "
                 f"(shortest original host). Use an IPv4 or a domain <= {MAXLEN} chars.")
    if b"/" in target or b":" in target:
        sys.exit("[!] target must be a bare host (no scheme, no port, no path)")

    with zipfile.ZipFile(apk) as z:
        entry = next((e for e in z.namelist() if e.endswith("global-metadata.dat")), None)
        if entry is None:
            sys.exit(f"[!] no global-metadata.dat in {apk}")
        info = z.getinfo(entry)
    if info.compress_type != 0:
        sys.exit(f"[!] {entry} is compressed - cannot in-place patch")

    apk_data = bytearray(apk.read_bytes())
    hdr = info.header_offset
    fn_len = struct.unpack_from('<H', apk_data, hdr + 26)[0]
    ex_len = struct.unpack_from('<H', apk_data, hdr + 28)[0]
    ms = hdr + 30 + fn_len + ex_len
    me = ms + info.file_size
    data = bytearray(apk_data[ms:me])

    sl_off, sl_cnt, sl_doff, sl_dcnt = _section_offsets(data)
    patched = 0
    for i in range(sl_cnt):
        eo = sl_off + i * 8
        length = struct.unpack_from('<I', data, eo)[0]
        di = struct.unpack_from('<i', data, eo + 4)[0]
        if di < 0 or di >= sl_dcnt or length == 0:
            continue
        a = sl_doff + di
        if a + length > len(data):
            continue
        s = bytes(data[a:a + length])
        if not any(h in s for h in HOSTS):
            continue
        ns = s
        for h in HOSTS:
            ns = ns.replace(h, target)
        nl = len(ns)
        data[a:a + nl] = ns
        if nl < length:
            data[a + nl:a + length] = b'\x00' * (length - nl)
        struct.pack_into('<I', data, eo, nl)
        patched += 1
        print(f"[+] [{i}] {s.decode('utf-8', 'replace')!r} -> {ns.decode('utf-8', 'replace')!r}")

    if not patched:
        sys.exit("[!] no backend host literals found - metadata layout unexpected, aborting")

    apk_data[ms:me] = data
    new_crc = zlib.crc32(bytes(data)) & 0xFFFFFFFF
    struct.pack_into('<I', apk_data, hdr + 14, new_crc)  # local header CRC
    tgt = entry.encode()
    pos = me
    while pos < len(apk_data) - 4:
        if apk_data[pos:pos + 4] == b'PK\x01\x02':
            l = struct.unpack_from('<H', apk_data, pos + 28)[0]
            if bytes(apk_data[pos + 46:pos + 46 + l]) == tgt:
                struct.pack_into('<I', apk_data, pos + 16, new_crc)  # central dir CRC
                break
        pos += 1
    apk.write_bytes(apk_data)
    print(f"[+] rebound {patched} literal(s) -> {target.decode()}  (CRC {new_crc:#010x})")
    print(f"[+] wrote {apk}")


if __name__ == "__main__":
    main()
