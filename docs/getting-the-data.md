# Getting the data - APK, master data, game code

From an empty directory to two usable artifacts:

- **master data** - ~150 XML files (`Units`, `Skills`, `Stages`, `Strings_<locale>`, ...), the tables
  the client reads;
- **game code** - `il2cpp/<version>/{dump.cs, script.json, global-metadata.dat}`, the class skeleton
  and address index that explain what reads those tables.

Written as a runbook: every step has a command and a check that tells you it worked. It assumes you
are on the project's own scripts, all of which are version-agnostic - nothing here is hardcoded to a
particular patch.

Related: [cdn-master-data.md](cdn-master-data.md) (edit what you extracted and push it),
[mftl-extraction.md](mftl-extraction.md) (how the packer was reversed),
[api-and-crypto.md](api-and-crypto.md) (the AES request format used in step 0).

## Prerequisites

| Need | Why |
|---|---|
| `python3` + `UnityPy` + `pycryptodome` | read AssetBundles, decrypt containers |
| `dotnet` + Il2CppDumper (`/usr/share/il2cpp-dumper/`) | metadata -> `dump.cs` |
| `apkeep` (Google account for the Play path) | download a stock client package |
| `unzip`, `zipalign`-adjacent tooling | split the package |
| ~3 GB free disk | a stock `.xapk` is ~1.1 GB |

## Step 0 - know which patch you are chasing

Content is gated by **min-version**: the API answers a different patch folder per client version.
`POST /auth/getPatchFolder` (AES body, see [api-and-crypto.md](api-and-crypto.md)) returns
`LIVE/<date>_<suffix>`.

Two traps:
- A sentinel version like `999.0.00` returns a folder that exists as a *pointer only* - every object
  in it is `NoSuchKey` until maintenance. A 404 is not a bug; it means "uploaded later".
- The `<suffix>` is not an identity. `2026_10_20_bhhtbJKhrR` and `2026_11_03_bhhtbJKhrR` share it and
  are a month apart. Key on the date, and on the object **etag** for republishes.

## Step 1 - get a stock client package

```bash
apkeep -l -a com.awesomepiece.castle                       # available versions
apkeep -a com.awesomepiece.castle@175.0.00 -d apk-pure \
       -o 'acknowledge_dangers=true,arch=arm64-v8a' apk/   # -> .xapk
```

- `apk-pure` needs `acknowledge_dangers=true`; `arch=` selects the ABI. It returns an `.xapk`
  (`base_assets.apk` + config splits + `manifest.json`).
- The Play path (`-d google-play`, account required) returns **split APKs** instead, not an `.xapk`.
- **Check `lib/<abi>/` before trusting the arch flag.** One release (175.0.00) shipped only
  `armeabi-v7a` through `apk-pure` regardless of the filter, while the arm64 libraries were only
  available as Play splits. If `lib/arm64-v8a` is missing, you have the wrong package, not a broken
  tool.

Verify: `unzip -l apk/*.xapk | grep -E 'lib/(arm64|armeabi)|base_assets'`.

## Step 2 - fetch the master-data bundle from the CDN

The APK carries only the *initial* content; every table the game actually uses is downloaded at boot:

```bash
# what folders exist (S3-style listing, no credentials needed)
curl -s 'https://kgc-cdn-1.awesomepiece.com/?prefix=patch/LIVE/&delimiter=/'
# the bundle itself
curl -o /tmp/xml_bundle https://kgc-cdn-1.awesomepiece.com/patch/LIVE/<folder>/ANDROID/xml
```

Three scripts wrap this, pick by need:

| Script | Behaviour |
|---|---|
| `scripts/check_cdn_update.sh` | daily cron: new folder or new etag -> notify |
| `scripts/grab_pending_patch.sh` | polls every few minutes, so it catches the upload *during* maintenance instead of the next morning (`--once` for cron, `INTERVAL=` to change the period) |
| `python3 server/builders/refresh_master_data.py` | full operator refresh: fetch, normalize, replay `local_mods`, rebuild the served bundle, bump `patchFolder` (`--dry-run`, `--no-bump`) |

Verify: HEAD the object and keep `etag` + `last-modified` + size. If you are chasing a republish of
the *same* folder, the etag is the only signal that anything changed.

## Step 3 - unwrap the container

Two formats, decided by the first 8 bytes:

| Client | Bundle | Action |
|---|---|---|
| ≤ 174.1 | `UnityFS\0` | none, feed to UnityPy |
| ≥ 175.0 | `KGCPXML1` | decrypt first |

The 175+ container is `PatchCrypto`:

```
offset 0   "KGCPXML1"            8 B magic
offset 8   flag byte             never read by the client, only skipped
offset 9   IV                    16 B
offset 25  ciphertext            AES-256-CBC / PKCS7
last 32    tag                   HMAC-SHA256(macKey, data[:len-32])

encKey = HMAC-SHA256(LiveKey, "KGC/Patch/ENC/v1")
macKey = HMAC-SHA256(LiveKey, "KGC/Patch/MAC/v1")
```

The 32-byte `LiveKey` is not in `libil2cpp.so`: the class builds it with
`RuntimeHelpers.InitializeArray`, so the bytes live in `global-metadata.dat`'s field-default heap.

```bash
python3 scripts/decrypt_kgcpxml1.py /tmp/xml_bundle -o /tmp/xml.unityfs
python3 scripts/decrypt_kgcpxml1.py /tmp/xml_bundle --learn il2cpp/<ver>/global-metadata.dat
```

Known keys are tabulated per build inside the script; `--learn` recovers a new one with an exact
oracle instead of guessing: CBC decrypts block-by-block, so if the plaintext starts with `UnityFS`
then `key = AES-Dec(candidate, C0) XOR IV` - scan every 32-byte window of the metadata and exactly
one candidate reproduces the magic. Plain `UnityFS` input is passed through untouched, so the script
is safe to run blindly.

Verify: output starts `UnityFS`, the HMAC validates, `len(out) == len(in) - 57` before pad removal.
`scripts/extract_xml.py` already calls this, so the rest of the pipeline did not have to change.

## Step 4 - extract the tables

```bash
python3 scripts/extract_xml.py /tmp/xml.unityfs xml_history/<date>
```

It walks the bundle's `TextAsset` objects and writes each one out by name. A current client yields
about **150 files, 143 of them `.xml`**.

Verify (both matter):

```bash
ls xml_history/<date>/*.xml | wc -l                          # ~143, never 0
python3 - <<'PY'
import glob, xml.etree.ElementTree as ET
bad = [f for f in glob.glob('xml_history/<date>/*.xml') if not ET.parse(f)]
print(len(glob.glob('xml_history/<date>/*.xml')), 'parsed,', len(bad), 'bad')
PY
```

Snapshot discipline: `xml_history/<date>` is **immutable** - it is the diff base, never edited.
What the server serves is `server/xml_live/`, rebuilt from a pristine snapshot plus the replayable
`server/local_mods/` (`server/builders/rebase_xml_live.py`). Editing a snapshot instead of a mod
means the next refresh silently throws your change away.

## Step 5 - read the tables

A question like "what does unit X do at tier 3" is answered by walking three files:

```
Units.xml    row Id=X              -> skill ids, stats, sprite names
Skills.xml   Inherit="id" chain    -> the tier's actual numbers
Buffs.xml    buff id               -> what the effect does
```

Structural facts that cost the most time if unknown:

- **Skills are chains, not rows.** A tier is a `Skill` that inherits another via `Inherit="id"`,
  often through `TransformSkill` / `BuffAtCastSkill`. A wrong `Inherit` produces a tier that quietly
  uses the wrong base stats - no error anywhere.
- **Text is keyed.** `UnitName_10810` is resolved through the `Localizer` at runtime; grep
  `Strings_EN_US.xml` / `Strings_VI.xml` for the key, not the unit.
- **Never put an XML comment in a `Strings_*.xml`.** One `<!-- -->` makes `Localizer.ParseTextAsset`
  drop the whole locale and every label renders as its raw key.
- **`MinVersion` is the content gate.** A row that exists but never appears is usually gated here
  (see [content-unlock.md](content-unlock.md)).

Diffing two snapshots is the fastest way to learn what a patch changed:

```bash
python3 scripts/xml_rowdiff.py xml_history/<old> xml_history/<new> [--filter Skill] [--top 20]
python3 scripts/cdn_diff_report.py ...        # same thing, as an HTML report
```

## Step 6 - recover the game code

| Client | `libil2cpp.so` | `global-metadata.dat` |
|---|---|---|
| ≤ 170 | plain file in `lib/arm64-v8a/` | plain file in `assets/bin/Data/Managed/Metadata/` |
| 171 - 174 | packed inside the anti-cheat loader | plain |
| 175+ | packed | **encrypted stub** (4 KB, magic `baa74702dfc5b6dd`, not `af1bb1fa`) |

From v171 the file is not shipped at all: at startup a loader decrypts it into memory. The loader's
**filename rotates every build** (`libaledatic`, `librolineng`, `libxenerene`, `libbisedich`,
`liberallisi`, ...) but its `SONAME` is stable:

```bash
$ readelf -d lib/arm64-v8a/lib*.so | grep SONAME
  SONAME  [libappsign4a.so]          <- this is the loader
```

Unpack chain: RSA-1024 key block -> ChaCha20 stream -> LZ4 payload (TARA v3/v4 depending on build),
plus NOPing the loader's own integrity and parser guards. The full derivation is in
[mftl-extraction.md](mftl-extraction.md); the tool is `server/patchers/unpack_neo.py`
(**ELF64 only** - an `armeabi-v7a`-only package fails here with a `struct.error`).

One-shot driver:

```bash
python3 scripts/dump_version.py apk/com.awesomepiece.castle@175.0.00.xapk --tag v175.0.00
```

It finds the packer by heuristic, unpacks, runs Il2CppDumper and writes
`il2cpp/<tag>/{dump.cs, script.json, global-metadata.dat, il2cpp.h, DummyDll/}`.

Two Il2CppDumper quirks that look like failures and are not:

- it **aborts before writing anything when stdin/stdout is redirected** - run it under a pty:
  `script -qec "dotnet Il2CppDumper.dll <lib> <metadata> <out>" /dev/null`;
- v6.7 **crashes at the final "Press any key"** *after* the files are written. Judge success by
  `dump.cs` existing and being the expected size, not by the exit code.

v175 also encrypts the metadata, so there is no offline `dump.cs` for it from the APK alone: the
code path is arm64 Play split -> unpack -> static disassembly of the container routine, or a runtime
hook that grabs the plaintext after the client decrypts it.

## Step 7 - read `dump.cs`

`dump.cs` is a C# skeleton: class names, **field offsets**, method signatures, and an `RVA:` line per
method. It is an index, not source. The four address conventions:

| You have | Meaning |
|---|---|
| `script.json` `ScriptMethod[].Address` | **RVA** (same space as tombstone `pc`) |
| file offset | **RVA - 0x4000**, for `libil2cpp.so` only |
| runtime address | `dlpi_addr` (`dl_iterate_phdr`) + symbol VMA |
| `dump.cs` `Offset:` | already equals RVA - 0x4000; verify once against a known patch |

Helper tools: `tools/il2cpp_disasm.py --meta` (disassemble one class, label every `bl` and every
`adrp/ldr` pair through `script.json`), `tools/il2cpp_slots.py`, `tools/il2cpp_litxref.py`,
`tools/bl_callers.py` (find callers by scanning `BL` immediates).

Verify: patch a method you can identify unambiguously, then confirm the bytes changed at exactly one
site and nowhere else. A patched library that differs by 21 stray bytes has already cost this
project two sessions of misdiagnosis.

## Step 8 - keep it repeatable

- `xml_history/<date>` per patch, `il2cpp/<version>` per client. Both immutable.
- New version? Steps 1, 2, 6 and you are current. Nothing else is version-specific.
- Republish of an existing folder? The etag tells you; `rebase_xml_live.py` rebuilds `xml_live` from
  the new pristine set and replays the mods.

## What still does not work

- **Clients after 175**: unknown. ExecuteArch and the metadata encryption are new; assume each bump
  moves offsets and re-derive rather than adding a delta.
- **iOS**: its bundle/key path was never confirmed to share the Android `LiveKey`.
- **The 1-byte flag at offset 8 of the container** is never read by the client. Probably a format
  version or a key id for a build that ships a non-live key.
- `apk-pure` may hand you a 32-bit-only package (step 1). That is a package problem, not a tooling
  one.

No credentials, tokens or player data appear on this page; the API hosts listed are the game's own
public endpoints.
