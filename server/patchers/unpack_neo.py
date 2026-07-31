#!/usr/bin/env python3
"""Recover libil2cpp.so from a XIGNCODE NEO packer (TARA v4 container).

The APK ships no `libil2cpp.so`; the game code lives inside the packer's payload
segment. This walks the container back to a linkable ELF, entirely offline - no
device, no root, no emulation.

    python3 unpack_neo.py <packer.so> <out.so>
    python3 unpack_neo.py --self-check

## The chain (v171.1.00, TARA **v4**)

1. Locate the payload: the last `PT_LOAD`, R-only, running to EOF.
2. Find `TARA` inside it. Header:

       +0x00 magic "TARA"      +0x10 comp   (compressed size)
       +0x04 version (4)       +0x14 usize  (decompressed size - the HEAD only)
       +0x0c rsa_len (0x80)    +0x20 RSA block, rsa_len bytes

3. **RSA-1024 public op** on the RSA block recovers a PKCS#1 v1.5 message whose
   last 32 bytes are the ChaCha20 key. The key IS the target ELF's own first 32
   header bytes - that is correct, not a bug: the packer stashes the header it
   overwrote. The 0x100-byte `N || E` blob is in `.rodata`, found by walking
   the code (see `find_rsa_blob`) rather than by a hardcoded offset, because it
   moves every build.
4. **ChaCha20** (not AES - v3 used AES-256-CBC): nonce is the 12 bytes at
   `tara + 0x20 + rsa_len`, ciphertext the `comp` bytes after the 16-byte tag.
5. **LZ4 block** decompress to `usize` - v3 used LZMA. This yields only the first
   `usize` bytes of the ELF.
6. The REST of the ELF is already in the clear, immediately after the ciphertext,
   past a small alignment gap. The gap is found by validating the section header
   table rather than assumed (it was 610 bytes here, and there is no field for it).

## What changed from v3 (v171.0.00), all of it silent

| | v3 | v4 |
|---|---|---|
| container | separate MFTL wrapper | TARA directly in the payload |
| stream cipher | AES-256-CBC, IV=0 | ChaCha20, 12-byte nonce |
| compression | LZMA (`FORMAT_ALONE`) | LZ4 block |
| coverage | whole 113 MB image | first 4 MB only; rest in cleartext |
| props field | LZMA props at +0x18 | zeroed |

Trusting the v3 recipe on a v4 container fails at step 4 with plausible-looking
garbage, which is why each stage below asserts on its own output.
"""
import pathlib
import struct
import sys

# --- ELF helpers --------------------------------------------------------------

def _phdrs(data):
    e_phoff, = struct.unpack_from('<Q', data, 32)
    e_phentsize, e_phnum = struct.unpack_from('<HH', data, 54)
    out = []
    for i in range(e_phnum):
        p = data[e_phoff + i * e_phentsize:][:e_phentsize]
        p_type, p_flags = struct.unpack_from('<II', p, 0)
        p_off, p_va, _, p_fsz, p_msz, _ = struct.unpack_from('<QQQQQQ', p, 8)
        out.append(dict(type=p_type, flags=p_flags, off=p_off, va=p_va,
                        fsz=p_fsz, msz=p_msz))
    return out


def _section(data, name_wanted):
    """(file_offset, va, size) of a section, by name."""
    e_shoff, = struct.unpack_from('<Q', data, 40)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', data, 58)
    strtab = data[e_shoff + e_shstrndx * e_shentsize:][:e_shentsize]
    str_off, str_size = struct.unpack_from('<QQ', strtab, 24)
    names = data[str_off:str_off + str_size]
    for i in range(e_shnum):
        sh = data[e_shoff + i * e_shentsize:][:e_shentsize]
        sh_name, = struct.unpack_from('<I', sh, 0)
        end = names.index(b'\0', sh_name)
        if names[sh_name:end] == name_wanted:
            sh_va, sh_off, sh_size = struct.unpack_from('<QQQ', sh, 16)
            return sh_off, sh_va, sh_size
    raise KeyError(name_wanted)


def find_payload(data):
    """The packed payload: the last R-only PT_LOAD, which runs to EOF."""
    loads = [p for p in _phdrs(data) if p['type'] == 1 and p['flags'] == 4]
    if not loads:
        raise SystemExit("no read-only PT_LOAD - not a NEO packer?")
    p = max(loads, key=lambda p: p['off'])
    return p['off'], p['fsz']


# --- RSA public key -----------------------------------------------------------

def rsa_blob_candidates(data):
    """Every 0x100-byte `N || E` blob the code points at, in address order.

    Hardcoding a `.rodata` offset does not survive a packer rebuild (this moved
    between every v171 build). The orchestrator copies the blob to the stack and
    passes `{ptr, 0x100}`, so it shows up as an adrp+add pair into `.rodata`.

    Shape alone is NOT enough to pick the right one: this build ships three blobs
    that all look like RSA-1024 with E=65537 (0x24225e, 0x242600, 0x2428bc) and
    only the last is the container key. So this yields all of them and the caller
    decides by trying the decrypt - see `recover_key`.
    """
    text_off, text_va, text_size = _section(data, b'.text')
    ro_off, ro_va, ro_size = _section(data, b'.rodata')
    code = data[text_off:text_off + text_size]

    seen, out = set(), []
    for i in range(0, len(code) - 8, 4):
        w = struct.unpack_from('<I', code, i)[0]
        if (w & 0x9f000000) != 0x90000000:        # adrp
            continue
        rd = w & 0x1f
        imm = (((w >> 5) & 0x7ffff) << 2) | ((w >> 29) & 3)
        if imm & (1 << 20):
            imm -= (1 << 21)
        w2 = struct.unpack_from('<I', code, i + 4)[0]
        if (w2 & 0xffc00000) != 0x91000000:       # add imm
            continue
        if (w2 & 0x1f) != rd or ((w2 >> 5) & 0x1f) != rd:
            continue
        target = (((text_va + i) & ~0xfff) + (imm << 12)) + ((w2 >> 10) & 0xfff)
        if not (ro_va <= target < ro_va + ro_size - 0x100):
            continue
        if target in seen:
            continue
        seen.add(target)
        blob = data[target - ro_va + ro_off:][:0x100]
        if blob[128:-3] == b'\0' * 125 and blob[-3:] == b'\x01\x00\x01':
            n = int.from_bytes(blob[:128], 'big')
            if n.bit_length() >= 1000:
                out.append((target, n, 65537))
    if not out:
        raise SystemExit("no RSA public-key blob found - packer layout changed")
    return out


def recover_key(data, rsa_block):
    """The ChaCha20 key, by trying each candidate blob's public op.

    A correct key is self-evident twice over: the message carries PKCS#1 v1.5
    padding, and the 32 bytes it wraps ARE the target ELF's own first 32 header
    bytes (the packer stashes the header it overwrote). A wrong blob fails both.
    """
    tried = []
    for va, n, e in rsa_blob_candidates(data):
        msg = pow(int.from_bytes(rsa_block, 'big'), e, n).to_bytes(len(rsa_block), 'big')
        if msg[:2] == b'\x00\x02' and msg[-32:][:4] == b'\x7fELF':
            return va, msg[-32:]
        tried.append(f"{va:#x} (pad {msg[:2].hex()})")
    raise SystemExit("no candidate RSA blob decrypts the container; tried "
                     + ", ".join(tried))


# --- TARA ---------------------------------------------------------------------

def parse_tara(payload):
    at = payload.find(b'TARA')
    if at < 0:
        raise SystemExit("no TARA container in the payload")
    ver, = struct.unpack_from('<I', payload, at + 4)
    rsa_len, = struct.unpack_from('<I', payload, at + 0x0c)
    comp, = struct.unpack_from('<I', payload, at + 0x10)
    usize, = struct.unpack_from('<I', payload, at + 0x14)
    if ver != 4:
        raise SystemExit(f"TARA version {ver} - this script implements v4 only "
                         f"(see docs/mftl-extraction.md for the v3 chain)")
    return dict(at=at, ver=ver, rsa_len=rsa_len, comp=comp, usize=usize)


def unpack(packer_path):
    from Crypto.Cipher import ChaCha20
    import lz4.block

    data = pathlib.Path(packer_path).read_bytes()
    pay_off, pay_len = find_payload(data)
    payload = data[pay_off:pay_off + pay_len]
    t = parse_tara(payload)
    at, rsa_len, comp, usize = t['at'], t['rsa_len'], t['comp'], t['usize']

    _, key = recover_key(data, payload[at + 0x20:at + 0x20 + rsa_len])

    # The decoder computes `x3 = (tara+0x20) + rsa_len` for the nonce and
    # `x6 = x3 + 0xc` for the ciphertext, i.e. they are adjacent - there is no
    # tag between them despite the AEAD-shaped call signature.
    nonce_at = at + 0x20 + rsa_len
    nonce = payload[nonce_at:nonce_at + 12]
    ct_at = nonce_at + 12
    stream = ChaCha20.new(key=key, nonce=nonce).decrypt(payload[ct_at:ct_at + comp])
    head = lz4.block.decompress(stream, uncompressed_size=usize)
    if head[:4] != b'\x7fELF':
        raise SystemExit("LZ4 output is not an ELF - container format changed")

    # Total size comes from the section header table in the head we just decoded.
    e_shoff, = struct.unpack_from('<Q', head, 40)
    e_shentsize, e_shnum = struct.unpack_from('<HH', head, 58)
    total = e_shoff + e_shnum * e_shentsize

    # The rest of the image sits in the clear after the ciphertext, past an
    # alignment gap that no header records. Find it by requiring that the section
    # header table it implies actually parses.
    tail_start = _find_tail(payload, head, ct_at + comp, total, e_shoff, e_shnum,
                            e_shentsize)
    out = head + payload[tail_start:][:total - len(head)]
    if len(out) != total:
        raise SystemExit(f"assembled {len(out)} bytes, expected {total}")
    return out


def _find_tail(payload, head, earliest, total, e_shoff, e_shnum, e_shentsize):
    need = total - len(head)
    idx = e_shoff - len(head)
    for start in range(earliest, earliest + 0x1000):
        tail = payload[start:]
        if len(tail) < need or idx + e_shnum * e_shentsize > len(tail):
            continue
        if tail[idx:idx + e_shentsize] != b'\0' * e_shentsize:
            continue                              # SHT[0] is always all-zero
        for i in range(1, e_shnum):
            sh = tail[idx + i * e_shentsize:][:e_shentsize]
            sh_name, sh_type = struct.unpack_from('<II', sh, 0)
            sh_off, sh_size = struct.unpack_from('<QQ', sh, 24)
            if sh_name > 0x1000 or sh_off > total or sh_size > total:
                break
        else:
            return start
    raise SystemExit("could not locate the cleartext tail")


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--self-check":
        return _self_check()
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    out = unpack(sys.argv[1])
    pathlib.Path(sys.argv[2]).write_bytes(out)
    print(f"[+] {sys.argv[2]}: {len(out)} bytes")


def _self_check():
    """Run against the v171.1.00 packer if it is on disk, else just parse-test."""
    repo = pathlib.Path(__file__).resolve().parents[2]
    apk = repo / "apk" / "xapk_extracted_v1711" / "config.arm64_v8a.apk"
    if not apk.exists():
        print(f"skip: {apk} not present")
        return
    import zipfile
    with zipfile.ZipFile(apk) as z:
        name = next(n for n in z.namelist()
                    if n.startswith("lib/arm64-v8a/") and n.endswith(".so")
                    and b"libappsign4a.so" in z.read(n)[:0x10000])
        blob = z.read(name)
    tmp = pathlib.Path("/tmp/_neo_selfcheck.so")
    tmp.write_bytes(blob)
    try:
        out = unpack(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    assert out[:4] == b'\x7fELF', "not an ELF"
    assert struct.unpack_from('<H', out, 18)[0] == 0xb7, "not AArch64"
    assert b'il2cpp_init' in out, "no il2cpp exports - wrong payload"
    assert b'libil2cpp.so' in out[:0x8000000], "SONAME missing"
    print(f"unpack_neo self-check ok ({len(out)} bytes from {name})")


if __name__ == "__main__":
    main()
