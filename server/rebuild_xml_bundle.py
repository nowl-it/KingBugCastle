#!/usr/bin/env python3
"""
Rebuild the CDN xml AssetBundle by replacing each TextAsset's m_Script
with the corresponding file from server/xml_live.

Usage: python3 rebuild_xml_bundle.py [xml_dir] [bundle_path]
  Defaults: xml_dir  = ../server/xml_live
            bundle   = real_cdn/xml

CRITICAL GOTCHA (found 2026-07-05, cost ~10 failed attempts to isolate):
Strings_VI.xml / Strings_EN_US.xml must NOT contain XML comments (<!-- -->)
anywhere. The game's Localizer.ParseTextAsset apparently mis-handles comment
nodes while iterating <String> children - any comment present causes EVERY
entry to silently fail to register in the runtime dictionary (Localize()
falls back to returning the raw key), even for entries that existed in the
pristine file and worked before. This is NOT a size/delta issue - a 1.7KB
batch with zero comments worked fine; a much smaller edit WITH a comment
failed. Skills.xml/Units.xml/ActiveSkills.xml are unaffected (they're read
by a different, more tolerant parser) - comments there are fine.
After editing server/xml_live/Strings_*.xml, always grep for '<!--'
before running this script.

After running: restart uvicorn (server.py caches real_cdn/ file bytes at
import time - see _CDN_FILES in server.py) and clear the device's
UnityCache (files/UnityCache under the app's external data dir) before
the next launch, or the client will keep using its previously-cached copy.
"""
import sys, pathlib, shutil

try:
    import UnityPy
except ImportError:
    print("[ERROR] UnityPy not found: pip install UnityPy", file=sys.stderr)
    sys.exit(1)

ROOT = pathlib.Path(__file__).parent
XML_DIR = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "xml_live"
BUNDLE  = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "real_cdn" / "xml"

assert XML_DIR.is_dir(), f"XML dir not found: {XML_DIR}"
assert BUNDLE.is_file(), f"Bundle not found: {BUNDLE}"

# Build lookup: name -> file content (try .xml first, then .txt)
xml_files = {}
for f in XML_DIR.iterdir():
    if f.is_file():
        xml_files[f.stem] = f  # stem = filename without extension

print(f"[*] XML dir: {XML_DIR} ({len(xml_files)} files)")
print(f"[*] Bundle:  {BUNDLE} ({BUNDLE.stat().st_size} bytes)")

# Guard: XML comments in Strings_*.xml break Localizer runtime registration
# (see module docstring). Refuse to proceed rather than silently ship a
# build where every string in that locale falls back to raw keys.
for locale_name in ("Strings_VI", "Strings_EN_US"):
    f = xml_files.get(locale_name)
    if f is not None and "<!--" in f.read_text(encoding="utf-8"):
        print(f"[ERROR] {f} contains an XML comment (<!--) - this breaks "
              f"Localizer runtime registration for the WHOLE locale. Remove "
              f"all comments before rebuilding.", file=sys.stderr)
        sys.exit(1)

# Backup original
backup = BUNDLE.with_suffix(".bak")
if not backup.exists():
    shutil.copy2(BUNDLE, backup)
    print(f"[*] Backup:  {backup}")

env = UnityPy.load(str(BUNDLE))
replaced = 0
skipped = []

for obj in env.objects:
    if obj.type.name != "TextAsset":
        continue
    data = obj.read()
    name = getattr(data, "m_Name", "") or ""
    if not name:
        continue

    src = xml_files.get(name)
    if src is None:
        skipped.append(name)
        continue

    new_content = src.read_bytes()

    # UnityPy TextAsset: m_Script is str in this bundle version
    # Decode bytes to str, stripping BOM if present
    try:
        text = new_content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = new_content.decode("utf-8", "surrogateescape")

    data.m_Script = text
    data.save()
    replaced += 1

if skipped:
    print(f"[!] {len(skipped)} assets had no matching file: {skipped[:10]}")

# Save modified bundle preserving each block's original compression.
# NOTE: packer="lz4" was tried first and is UNVERIFIED against the real
# client - it also bloats the bundle (4.4MB pristine -> 7.7MB with lz4 vs
# ~3.9MB with "original"). "original" is what every confirmed-working test
# this session actually used - don't change back without re-testing in-game.
new_data = env.file.save(packer="original")
BUNDLE.write_bytes(new_data)
new_size = BUNDLE.stat().st_size

print(f"[+] Replaced {replaced} TextAssets")
print(f"[+] Bundle written: {BUNDLE} ({new_size} bytes)")

# Also update AssetHash.txt if it exists (MD5 + size)
asset_hash_file = BUNDLE.parent / "AssetHash.txt"
if asset_hash_file.exists():
    import hashlib
    md5 = hashlib.md5(new_data).hexdigest()
    lines = asset_hash_file.read_text().splitlines()
    new_lines = []
    for line in lines:
        if line.startswith("xml:"):
            new_lines.append(f"xml:{md5}_{new_size}")
            print(f"[+] AssetHash.txt: xml:{md5}_{new_size}")
        else:
            new_lines.append(line)
    asset_hash_file.write_text("\n".join(new_lines) + "\n")
