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
packer `.so` from that version's `config.arm64_v8a.apk` plus this recipe.
It is no longer called `libaledatic.so` - see the next section.

---

## v171.0.01: NEO repack, names rotated, payload no longer compressed

Released 2026-07-22, one day after the 2026_07_21 master-data patch. It is an
**anti-cheat-only release: zero gameplay content changed.** Evidence, all three
independent:

- **Addressables catalog**: 10,324 `m_InternalIds` in both builds, and the only
  differing entry is the prefabs bundle's own content-hash filename
  (`prefabs_assets_all_c4e16f42….bundle` → `…_e47d8bf5….bundle`). No asset added,
  removed, or renamed. That bundle is +17 bytes with an identical block table and
  the same Unity `2022.3.62f3` - a rebuild artifact, not new content.
- **global-metadata.dat** (+16 B): exactly four string changes, listed below.
- **CDN**: still `2026_07_21`, same xml bundle etag `bd378814…`.

### What actually changed

| | v171.0.00 | v171.0.01 |
|---|---|---|
| Packer lib | `libaledatic.so`, 25 MB | `librolineng.so`, **114,492,014 B** |
| NEO data blob (base apk) | `assets/usinisse.wio` | `assets/kisessta.fis` |
| XIGNCODE exports | - | `ZCWAVE_GetCookie2`, `ZCWAVE_SetUserInfo` |
| Backend endpoint | `/auth/xcdSeed` | + `/auth/xcdSeed?version=` |
| Unity package build hash | `1.0.0+f8109562…` | `1.0.0+253f024e…` |

Both packer libs carry `SONAME = libappsign4a.so`, so the on-disk filename is
rotated per build - **never key an unpack script off the filename**; match the
SONAME, or just take the one `.so` in the config split that has no `libunity`/
`libmain`/Firebase name.

The renamed asset and lib are *not* in `global-metadata.dat` (they live in the
dex loader), which is why the metadata delta is only 16 bytes.

### The payload stopped being compressed

`librolineng.so` is one 111 MB `PT_LOAD` R segment at file offset `0x344000`
(`FileSiz 0x69ec26d`, ending exactly at EOF). Entropy sampled across it:

```
  0.0 MB  7.98   encrypted/packed header
  2-22 MB 3.0    low - structured tables (pointer arrays)
 24-95 MB 6.1-6.7  ARM64 machine code, in the clear
 97-102 MB 0.00  zero padding
```

`grep -ac` finds plaintext `il2cpp` (21), `UnityEngine` (30), `mscorlib` (13)
inside it. The old build was a 25 MB AES+LZMA blob at 7.99 entropy end to end.
So the AES-256-CBC → LZMA stage of this recipe appears to be **gone**, replaced
by a mostly-cleartext memory image. If a future build ever needs unpacking,
start by carving that segment - do not assume the five-layer chain still applies.

### Building the private client on v171.0.01 (done, boots)

*Superseded by the v171.1.00 section below - kept because the metadata analysis is
what explains why a mismatched lib/metadata pair fails silently.*

At the time, `server/build_v171_private.py` took the **v171.0.01** APKs. Two things
had to change; both were silent failures, not crashes, which is why "it just doesn't
run". (Both `apk/xapk_extracted_v17100/` and `apk/xapk_extracted_v1711/` are on disk
now - `./kgc-cli download -v <version> --arch arm64 -o apk/` re-fetches any of them.)

**1. The metadata is NOT drop-in compatible - this is the whole story.**
The "+16 B / 4 strings" delta above is real but badly understates it. The new
literal `/auth/xcdSeed?version=` was **inserted at stringLiteral index 1545 of
25730**, immediately after `/auth/xcdSeed` - an insert, not an append. Every
literal above it shifts index by one, i.e. **94% of all string literals move**.
`libil2cpp.so` has those indices compiled into its code, so the recovered
v171.0.00 lib resolves nearly every string to the wrong entry when it runs
against v171.0.01's `global-metadata.dat`: wrong URLs, wrong resource paths,
wrong localization keys. Nothing survives that.

Every other metadata section is byte-identical (`attributeData` differs at the
same size; the rest matches exactly once you account for the +16 B shift), so
the fix is to ship the matching metadata: `patchers/patch_metadata_swap.py`
splices `il2cpp/v171.0.00/global-metadata.dat` into `base_assets.apk` (STORED
entry, zero-padded to the stored size, CRC fixed in local header + central
directory) **before** `patch_hosts.py` / `patch_metadata_http.py` run.

**2. The NEO loader patch offsets do not shift by a constant.**
`libaledatic.so` maps `file == VMA`; `librolineng.so` maps `VMA == file - 0x4000`,
and the loader function itself grew, so its head and tail moved by *different*
deltas. Deriving the v171.0.01 offsets by adding a constant to the v171.0.00
ones produced 4 correct sites out of 12, silently skipped 4, and **applied 2 NOPs
to unrelated `b` instructions in a parser**. The old loop skipped mismatches
without complaining, which is how that went unnoticed.

Correct sites, matched 1:1 against v171.0.00 by call sequence:

| purpose | v171.0.00 `libaledatic.so` | v171.0.01 `librolineng.so` |
|---|---|---|
| integrity bail-outs (`bl` ; `tbnz w0,#31,<fail>`, last is `cbz x0`) | `3d2b8 3d2c0 3d2c8 3d2f8 3d484 3d4c8 3d4e4 3d4f4` | `437b0 437b8 437c0 437f0 43c28 43c6c 43c88 43c98` |
| payload-parser error returns (`mov w8,#-1` ; `str w8,[sp,#0x94]` ; `b`) | `e5728 e57d0 e57e8 e5870` | `12bd0c 12bdb4 12bdcc 12be54` |

The second group is now found by **pattern**, not offset: the 8-byte prefix
`08008012 e89700b9` occurs exactly 4x in both libs, at the same relative spacing
(+0, +0xa8, +0xc0, +0x148). The first group stays a table but now **raises** on a
byte mismatch. The loader is located by `SONAME = libappsign4a.so`, never by
filename.

Result: boots to the Terms-of-Service screen and on into the login flow, serving
`/player/get-login-scene-illust-data?version=171001` and the full CDN patch set.

`scripts/check_cdn_update.sh` now also watches the store version - the CDN folder
and the client release move independently, and this one was invisible to the
old folder-and-etag check.

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


---

## v171.1.00: TARA **v4** - SOLVED

Unpacked 2026-07-30 from the arm64 `libxenerene.so` (`SONAME = libappsign4a.so`).
Fully automated: `python3 server/patchers/unpack_neo.py <packer.so> <out.so>`
(`--self-check` runs it against `apk/xapk_extracted_v1711/` and asserts the result).

**Correcting the v171.0.01 note above:** "the payload stopped being compressed" was
measured on the payload *tail*. The head is still encrypted and there is still a TARA
container - it moved into the payload and went to version 4.

### Layout

| | value |
|---|---|
| payload segment | file `0x344000`, 111,072,093 B (last R-only `PT_LOAD`, runs to EOF) |
| TARA header | payload `+0x262`, magic `TARA`, **version 4** |
| encrypted head | payload `0x30e`-`0x15d294`, entropy 8.00 |
| cleartext tail | payload `0x15d294` onward (610-byte alignment gap after the ciphertext) |
| result | 113,836,232 B ELF, `SONAME = libil2cpp.so`, 241 `il2cpp_*` exports |

The payload is a **memory image**, not a copy of the on-disk ELF, so probes from the
v171.0.00 lib appear nowhere in it. Entropy in the tail is ~3.2 for the first ~35 MB
(pointer tables) and only reads as ARM64 code further in - an instruction-frequency
check scores 0.05% at tail+0, 72% at tail+40 MB, 77% at tail+80 MB.

### TARA v4 header

```
+0x00  magic "TARA"
+0x04  version = 4          (v3 = 3)
+0x08  0x19ae9a5e
+0x0c  rsa_len = 0x80
+0x10  comp   = 0x15cf86    compressed size
+0x14  usize  = 0x400000    decompressed size - the HEAD only, not the whole lib
+0x18  00 00 00 00 00       (v3 had LZMA props `5d 00 40 00 00` here)
+0x20  RSA block, rsa_len bytes
+0xa0  12-byte ChaCha20 nonce   (= tara + 0x20 + rsa_len)
+0xac  ciphertext, comp bytes
```

### The chain

1. **RSA-1024 public op** on `tara[0x20 : 0x20+rsa_len]` -> PKCS#1 v1.5 message whose
   last 32 bytes are the ChaCha20 key. As in v3 the key IS the target ELF's own first
   32 header bytes - the packer stashes the header it overwrote, so a key that looks
   like an ELF header is the success signal, not a bug.
2. **ChaCha20** (v3 used AES-256-CBC), nonce at `+0xa0`, ciphertext immediately after
   at `+0xac`. The decoder's call signature looks AEAD-shaped (`w4 = 0xc` for the nonce
   length) but there is **no tag between nonce and ciphertext** - assuming one shifts
   the stream by 16 bytes and LZ4 then fails.
3. **LZ4 block** decompress to `usize` (v3 used LZMA `FORMAT_ALONE`) -> the first 4 MB
   of the ELF.
4. Concatenate the cleartext tail. Its start is **not recorded anywhere** - find it by
   requiring that the section header table implied by the head actually parses.

### Finding the RSA key without hardcoding an offset

The 0x100-byte `N || E` blob moves every build (v3's writeup pinned `.rodata 0x2feca2`;
here it is `0x2428bc`). Walk `adrp`+`add` pairs in `.text` for targets inside `.rodata`
whose last 4 bytes are a big-endian 65537 after 125 zero bytes.

**Shape alone is not enough**: this build ships three blobs that all pass that test
(`0x24225e`, `0x242600`, `0x2428bc`) and only the last is the container key. Try each
and keep the one whose public op yields PKCS#1 padding AND an ELF-header key -
`unpack_neo.recover_key` does exactly that.

### How the decoder was located

Raw-scan `.text` for the `TARA` magic materialised as an immediate (`movz w9,#0x4154`
+ `movk w9,#0x4152,lsl#16`) - 3 hits, one per version decoder. The one whose version
compare is `cmp w10,#4` is v4 (`0x8c2ac`). From there the vtable slot `+0x38` at
`0x32d2f0` leads back through the factory at `0x8bdc8` to the orchestrator at
`0x97c30`, which is where the RSA blob is copied to the stack as `{ptr, 0x100}`.

The cipher is identified by its own constant: `0x1e2ff4` loads `expand 32-byte k`.

| | v3 (v171.0.00) | v4 (v171.1.00) |
|---|---|---|
| container | separate MFTL wrapper | TARA directly in the payload |
| stream cipher | AES-256-CBC, IV = 0 | ChaCha20, 12-byte nonce |
| compression | LZMA | LZ4 block |
| coverage | whole 113 MB image | first 4 MB; rest in cleartext |
| props field | LZMA props at `+0x18` | zeroed |

### What this changes for the build

`build_v171_private.py` now injects `il2cpp/v171.1.00/libil2cpp_v17110_ssl.so` when
building from `xapk_extracted_v1711` - the lib unpacked from that build's own packer.
It pairs with the metadata the APK already ships, so **`patch_metadata_swap.py` no
longer runs**. Set `KGC_FORCE_V17100=1` to fall back to the v171.0.00 lib + swap.

Every il2cpp offset is per-lib and was re-derived from `il2cpp/v171.1.00/dump.cs` by
exact class + signature match. All 10 NRE-stub prologues came back byte-identical to
the v171.0.00 set, which is the cross-check that the re-derivation landed on the same
methods; the SSL trio is in `make_v171_ssl_so.py` under version `171.1.00`.

`ShopItem.Init`'s patch site does NOT match by bytes across the two builds (the
immediates changed). It was matched by instruction shape instead - `adrp; ldr x8,[x8,#imm];
mov x22,x0; mov x0,x20; mov w1,wzr; ldr x2,[x8]; bl; cbz x0` - and the replacement's
`cbz` displacement recomputed against the new bail-out target.
