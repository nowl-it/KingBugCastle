#!/usr/bin/env python3
"""
Patch global-metadata.dat: change https:// -> http:// in string literals.
Accepts either a standalone global-metadata.dat OR an APK (ZIP) containing it.

Usage: python3 patch_metadata_http.py <metadata_or_apk_path>
"""
import sys, struct, pathlib, zipfile, zlib

INPUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("global-metadata.dat")

# ---- detect APK (ZIP) vs raw metadata ----
IS_APK = False
APK_ENTRY = None
apk_data = None

if INPUT.suffix in ('.apk', '.zip') or INPUT.read_bytes()[:2] == b'PK':
    with zipfile.ZipFile(INPUT, 'r') as z:
        entries = z.namelist()
        for e in entries:
            if e.endswith('global-metadata.dat'):
                APK_ENTRY = e
                break
    if APK_ENTRY is None:
        print(f"[!] No global-metadata.dat found in {INPUT}")
        sys.exit(1)
    IS_APK = True
    print(f"[*] APK mode: patching {APK_ENTRY} inside {INPUT.name}")
    apk_data = bytearray(INPUT.read_bytes())
    # find entry data offset
    with zipfile.ZipFile(INPUT, 'r') as z:
        info = z.getinfo(APK_ENTRY)
    if info.compress_type != 0:
        print(f"[!] {APK_ENTRY} is compressed (type={info.compress_type}) — cannot in-place patch")
        sys.exit(1)
    hdr_off = info.header_offset
    fname_len = struct.unpack_from('<H', apk_data, hdr_off + 26)[0]
    extra_len = struct.unpack_from('<H', apk_data, hdr_off + 28)[0]
    meta_start = hdr_off + 30 + fname_len + extra_len
    meta_end = meta_start + info.file_size
    print(f"[*] metadata at APK offset 0x{meta_start:x}  len={info.file_size}")
    data = bytearray(apk_data[meta_start:meta_end])
else:
    data = bytearray(INPUT.read_bytes())

# ---- read il2cpp global-metadata header ----
sanity, version = struct.unpack_from('<II', data, 0)
assert sanity == 0xFAB11BAF, f"Bad sanity: {sanity:#x}"
print(f"[*] il2cpp metadata version: {version}")

# Header field offsets vary by version; for v24.1+ (Unity 2020+):
# offset  0: sanity (4)
# offset  4: version (4)
# offset  8: stringLiteralOffset (4), stringLiteralCount (4)   <-- v27+
# ...
# We'll search for all occurrences of "https://" in the stringLiteralData section
# and patch them + update the corresponding length fields.

# Locate the stringLiteral section by scanning the header.
# For il2cpp v24-v31, offsets appear around bytes 8-80 in the header.
# Find stringLiteralOffset and stringLiteralDataOffset by scanning for plausible ranges.

def read_section_offsets(data, version):
    """Return (strLitOff, strLitCount, strLitDataOff, strLitDataCount) from header."""
    # Header layout varies; use known layout for v27-v31 (Unity 2021-2024)
    # offset 8: stringLiteralOffset (int32)
    # offset 12: stringLiteralCount (int32)
    # offset 16: stringLiteralDataOffset (int32)
    # offset 20: stringLiteralDataCount (int32)
    # This works for most Unity 2020+ games.
    off = struct.unpack_from('<i', data, 8)[0]
    cnt = struct.unpack_from('<i', data, 12)[0]
    data_off = struct.unpack_from('<i', data, 16)[0]
    data_cnt = struct.unpack_from('<i', data, 20)[0]

    # Sanity: offsets should be > 0 and < file size
    sz = len(data)
    if 0 < off < sz and 0 < data_off < sz and cnt > 0:
        return off, cnt, data_off, data_cnt

    # Try offset 16 for older formats
    off = struct.unpack_from('<i', data, 16)[0]
    cnt = struct.unpack_from('<i', data, 20)[0]
    data_off = struct.unpack_from('<i', data, 24)[0]
    data_cnt = struct.unpack_from('<i', data, 28)[0]
    if 0 < off < sz and 0 < data_off < sz and cnt > 0:
        return off, cnt, data_off, data_cnt

    raise ValueError("Could not locate stringLiteral sections in header")

try:
    sl_off, sl_cnt, sl_data_off, sl_data_cnt = read_section_offsets(data, version)
    print(f"[*] stringLiteral: offset=0x{sl_off:x} count={sl_cnt}")
    print(f"[*] stringLiteralData: offset=0x{sl_data_off:x} count={sl_data_cnt}")

    HTTPS = b"https://"
    HTTP  = b"http://"
    patched = 0

    for i in range(sl_cnt):
        entry_off = sl_off + i * 8  # each entry is (uint32 length, int32 dataIndex)
        length = struct.unpack_from('<I', data, entry_off)[0]
        data_idx = struct.unpack_from('<i', data, entry_off + 4)[0]

        if data_idx < 0 or data_idx >= sl_data_cnt:
            continue
        abs_data = sl_data_off + data_idx
        if abs_data + length > len(data):
            continue

        snippet = bytes(data[abs_data: abs_data + min(8, length)])
        if snippet != HTTPS:
            continue

        # Found an https:// string - read full string
        full = bytes(data[abs_data: abs_data + length]).decode('utf-8', errors='replace')
        new_full = full.replace("https://", "http://", 1)
        new_bytes = new_full.encode('utf-8')
        new_len = len(new_bytes)

        # Write new string data (pad with \0 if shorter, which it is by 1 byte)
        data[abs_data: abs_data + new_len] = new_bytes
        # Zero out the 's' that was removed (1 byte shorter)
        if new_len < length:
            data[abs_data + new_len: abs_data + length] = b'\x00' * (length - new_len)
        # Update length field in stringLiteral header
        struct.pack_into('<I', data, entry_off, new_len)

        print(f"[+] [{i}] {full!r} -> {new_full!r}")
        patched += 1

    print(f"\n[+] Patched {patched} URL(s)")

except Exception as e:
    print(f"[!] Structured parse failed ({e}), falling back to raw byte search...")
    # Fallback: raw binary search for https:// followed by known hosts
    HOSTS = [
        b"axis-game.awesomepiece.com",
        b"kgc-k8s-1.awesomepiece.com",
        b"isekai-lobbyserver.awesomepiece.com",
        b"castle-infra-server-65408603887.asia-northeast3.run.app",
        b"kgc-cdn-1.awesomepiece.com",
    ]
    HTTPS = b"https://"
    HTTP  = b"http://\x00"  # same length, null-pad
    patched = 0
    pos = 0
    while True:
        pos = bytes(data).find(HTTPS, pos)
        if pos == -1:
            break
        # check if followed by a known host
        for host in HOSTS:
            if bytes(data[pos+8: pos+8+len(host)]) == host:
                print(f"[+] raw patch at 0x{pos:x}: https://{host.decode()} -> http://\\0{host.decode()}")
                data[pos: pos+8] = HTTP
                patched += 1
                break
        pos += 1
    print(f"[+] Raw patched {patched} occurrence(s)")

if IS_APK:
    # write patched metadata back into APK data
    apk_data[meta_start:meta_end] = data
    # update CRC-32 in local header and central directory
    new_crc = zlib.crc32(bytes(data)) & 0xFFFFFFFF
    struct.pack_into('<I', apk_data, info.header_offset + 14, new_crc)
    cd_sig = b'PK\x01\x02'
    target = APK_ENTRY.encode()
    pos = meta_end
    while pos < len(apk_data) - 4:
        if apk_data[pos:pos+4] == b'PK\x01\x02':
            fn_len = struct.unpack_from('<H', apk_data, pos + 28)[0]
            fn = bytes(apk_data[pos+46:pos+46+fn_len])
            if fn == target:
                struct.pack_into('<I', apk_data, pos + 16, new_crc)
                print(f"[+] CRC updated: 0x{new_crc:08x}")
                break
        pos += 1
    INPUT.write_bytes(apk_data)
    print(f"[+] Written: {INPUT}")
else:
    INPUT.write_bytes(data)
    print(f"[+] Written: {INPUT}")
