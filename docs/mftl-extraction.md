# MFTL/NEO Extraction: libil2cpp.so Recovery

## Overview

King God Castle v171 uses **XIGNCODE NEO** packer to encrypt `libil2cpp.so`. The
packer's loader is `libaledatic.so` (24 MB), which has the real `libil2cpp.so`
appended as an **MFTL** (MessagePack-encapsulated encrypted payload).

The extraction has two layers, **both SOLVED** - fully offline, deterministic,
no device / root / RAM-dump:
- **Layer 1**: AES-256-CBC → produces a **TARA v3** container
- **Layer 2**: RSA-1024 public op recovers the AES-256 key → AES-256-CBC → LZMA
  → the real `libil2cpp.so`

The recovered lib lives at `il2cpp/v171.0.00/libil2cpp_v171.so` (unpatched) and
`libil2cpp_v171_ssl.so` (the +14-patch build input for `server/build_v171_private.py`).
The one-off unpack scripts were removed after they did their job; the full recipe
below reproduces them, and [[project_v171_neo_layer2_algo]] in memory carries it too.

---

## MFTL Structure

```
libaledatic.so (25 MB)
├── normal ELF code (JNI_OnLoad, init_array, etc.)
├── [MFTL Directory @ 0x17d6ec0]
│   ├── "MFTL" magic
│   ├── version = 1
│   ├── payload_offset = 0x2f3cd0
│   ├── payload_size = 0x14e3190 (21,901,712 bytes)
│   └── footer_offset = 0x17d6e60
├── [MFTL Payload @ 0x2f3cd0]
│   └── AES-256-CBC encrypted data (21,901,712 bytes)
│       CRC32 overlay: 0x67f5d115 (stored ASCII before header)
└── [MFTL Footer @ 0x17d6e60]
    ├── field1 = 0x6cac9791
    ├── filename = "libil2cpp.so\0"
    ├── IV (16 bytes, disguised as MD5 hash)
    │   └── c4 10 00 00 ... c4 10 00 00
    │   └── actual: 254297ba46d6da17d7cb478856ae26ed
    └── Key (32 bytes, disguised as SHA256 hash)
        └── c4 20 00 00 ... c4 20 00 00
        └── actual: fe46f640513e53ddfd72cc84ce4bd7af44c1bebdb8c1c452a57080e73aa26459
```

### Footer binary format

| Offset | Size | Field |
|---|---|---|
| 0x00 | 4 | field1 (0x6cac9791) |
| 0x04 | 12 | filename "libil2cpp.so\0" |
| 0x10 | 2+16 | c4 10 [len] + IV (16 bytes) |
| 0x22 | 2+32 | c4 20 [len] + Key (32 bytes) |

---

## Layer 1: AES-256-CBC Decryption

The key discovery was that the footer fields labeled as "MD5" and "SHA256" hashes
are actually the **AES-256 key and IV**:

- **AES Key**: `fe46f640513e53ddfd72cc84ce4bd7af44c1bebdb8c1c452a57080e73aa26459`
- **AES IV**: `254297ba46d6da17d7cb478856ae26ed`

Decrypt payload at `0x2f3cd0` with AES-256-CBC → produces a **TARA container**
(magic `TARA`, version 3, compressed size ~22 MB, decompressed size 113,831,168).

### Recipe

Decrypt payload at file `0x2f3cd0`, size `0x14e3190`, of the original
`config.arm64_v8a.apk` → `lib/arm64-v8a/libaledatic.so` with AES-256-CBC using
the MFTL key/IV above → `libil2cpp_tara.bin` (21,901,712 B).

---

## TARA Container Format

```
TARA Container (22 MB after AES decrypt)
├── [Header @ 0x00]
│   ├── magic = "TARA" (4 bytes)
│   ├── version = 3 (4 bytes, LE)
│   ├── unknown[2] = 0x0100
│   ├── compressed_size = 0x...(4 bytes, LE)
│   ├── decompressed_size = 0x6C8C000 (113,831,168 = 4 bytes, LE)
│   └── padding[6]
├── [Body @ 0x18]
│   ├── LZMA properties = 5d 00 40 00 00
│   │   └── dict_size = 0x4000 (16 KB)
│   └── LZMA compressed data (NEO-obfuscated!)
└── [... rest of body]
```

The decompressed size (113,831,168) **exactly matches** the recovered
`libil2cpp_v171.so`.

---

## Layer 2: TARA v3 → libil2cpp.so (SOLVED)

The dict=0x4000 LZMA header at `[0x18]` is real; the stream just isn't plain
LZMA - it's AES-256-CBC ciphertext, and the AES key is recovered by an RSA
public-key operation baked into the container.

### TARA v3 layout (`libil2cpp_tara.bin`, 21,901,712 B)

| Offset | Field |
|---|---|
| `[0x00]` | magic `TARA` |
| `[0x04]` | version = 3 |
| `[0x10]` | compressed size (`0x14e30e8`) |
| `[0x14]` | decompressed size (`0x6c8ed00` = 113,831,168) |
| `[0x18]` | LZMA props, 5 bytes (`5d 00 40 00 00`) |
| `[0x20:0xa0]` | 0x80-byte RSA-1024 block (ciphertext of the key material) |
| `[0xa0:]` | AES-256-CBC ciphertext of the LZMA stream |

### The master key is an RSA-1024 PUBLIC key

At `.rodata 0x2feca2` (Ghidra base 0x100000) sits a 0x100-byte blob = N (128 B)
|| E (128 B, = 65537). The orchestrator `FUN_0018e498` copies it to the stack and
passes descriptor `{containerPtr, containerSize, &blob, 0x100}` with `param_4=1`
(the 2-way public split; `param_4=0` would be the 9-way private split).

### The recovery, step by step

1. **RSA public op** on `tara[0x20:0xa0]` → recovers **32 bytes**. The twist:
   that key IS libil2cpp's own first 32 ELF header bytes
   (`7f454c46 02010100 ...0300 b700 01000000 049f750200000000`), so it doubles as
   the header stash written back after decrypt. A key that looks like an ELF
   header is correct, not a bug.
2. **AES-256-CBC, IV = 16 zero bytes**, over `tara[0xa0 : 0xa0 + align16(comp_size)]`
   → the LZMA stream (byte0 == 0x00 confirms).
3. **LZMA**: Python `lzma.LZMADecompressor(format=FORMAT_ALONE)` on
   `props5 + struct.pack('<Q', usize) + stream` → the 113,831,168-byte ELF.

Once step 1's 32 bytes are known, steps 2-3 are ~10 s of pure Python - no
emulation. In the RE session the key was lifted by hooking the inner mbedtls
AES-CBC at `0x15a6d0` in a Unicorn run and reading x2/x3, avoiding emulating the
21.9 MB decrypt.

### Key addresses (v171 libaledatic.so, Ghidra base 0x100000)

| Addr | Role |
|---|---|
| `0x18e498` | orchestrator; builds descriptor, holds the RSA pubkey blob |
| `0x185bfc` | TARA version dispatcher (vtable slot +0x38 of vtable `0x3e1c58`) |
| `0x185974` / `0x185780` | TARA v3 / v2 decoders |
| `0x157238` | key init, 2-way split (N,E) = RSA public (param_4=1, live path) |
| `0x15a6d0` | mbedtls AES-CBC `(src, len, key, keylen, out, outlen, ivptr)` |
| `0x1544b4` | 7-zip LzmaDecode |
| `0x2feca2` | **the RSA-1024 public key blob (0x100 B)** |

### AES keys involved

| Key | Type | Value | Purpose |
|---|---|---|---|
| Config Key (16B) | AES-128 | `037ab239700797e192d873b498596137` | init_array setup, anti-debug |
| MFTL Key (32B) | AES-256 | `fe46f640513e53ddfd72cc84ce4bd7af44c1bebdb8c1c452a57080e73aa26459` | Layer-1 payload decrypt |
| MFTL IV (16B) | AES-256 | `254297ba46d6da17d7cb478856ae26ed` | Layer-1 payload decrypt |
| Layer-2 AES key (32B) | AES-256 | recovered per-container via the RSA op above (= the ELF header) | TARA stream decrypt |

### Method lesson (matters more than the addresses)

"FUN_X has NO static xrefs, NEO dispatches everything via computed pointers" was
**wrong** - a Ghidra auto-analysis artifact mistaken for anti-analysis, which cost
hours of blind key-guessing. What worked in minutes: raw-scan `.text` for BL/B
encodings (decode imm26, compute target) instead of trusting Ghidra xrefs, and
scan `.rela.dyn` addends for vtable slots using **link-time RVAs (base 0)**, not
Ghidra VAs. Apply that before ever concluding a packer is "statically unreachable".

### What Worked

| Step | Tool | Result |
|---|---|---|
| Il2CppDumper | `Il2CppDumper libil2cpp_v171.so global-metadata.dat output_dir` | ✅ dump.cs (43 MB), 146 DummyDlls (27 MB), il2cpp.h, script.json |
| AssetRipper | `AssetRipper --cli -i extracted_assets/ -o unity_project/` | ✅ 650 MB Unity project, 4,445 .cs scripts (stubs), 6 scenes, 65 prefabs, 29 shaders |

---

## Where the artifacts live now

The one-off unpack scripts and 2 GB of intermediates (Unicorn venv, TARA blob,
AssetRipper project, decoded ELFs, input APKs) were cleaned up once the recipe
was proven. What's kept:

```
il2cpp/v171.0.00/
├── libil2cpp_v171.so         recovered ELF, unpatched (113 MB)
├── libil2cpp_v171_ssl.so     + 14 patches; build input for build_v171_private.py
├── dump.cs                   Il2CppDumper type dump (offset reference)
├── script.json               full script map
└── global-metadata.dat       v171 metadata (Il2CppDumper input)
```

`scratchpad/` is now gone entirely; live-edited master data moved to
`server/xml_live/` (server source, unrelated to NEO).

Re-running the unpack on a future NEO build only needs the original
`libaledatic.so` from that version's `config.arm64_v8a.apk` plus this recipe.

---

## Key Findings Summary

1. **MFTL footer at 0x17d6e60** contains the AES key disguised as SHA256,
   IV disguised as MD5
2. **CRC32 before payload header** = `0x67f5d115` (stored as ASCII hex)
3. **Layer 1 AES key** is the SHA256 field, NOT the config key
4. **TARA decompressed size (113,831,168)** matches deployed SO exactly
5. **LZMA dict=0x4000** is real; the stream is AES-256-CBC ciphertext, not raw LZMA
6. **NEO deobfuscation** is genuine, not a fake transform
7. **Layer 2 master key** is an RSA-1024 PUBLIC key at `.rodata 0x2feca2`; its
   public op recovers the AES-256 key, which equals the target ELF's own header
8. The whole chain is offline + deterministic - no device, root, or RAM dump needed
