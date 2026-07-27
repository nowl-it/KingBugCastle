#!/usr/bin/env python3
"""
Replace PreStrings GUID files' m_Script with the full Strings_XX.xml content.
This makes PreInitialize load ALL strings, bypassing the CDN-dependent LoadStrings call.
"""
import sys, os, io, zipfile, pathlib
import UnityPy

APK = pathlib.Path(sys.argv[1])
XML_DIR = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path(__file__).resolve().parent.parent / "xml_live"

# Map locale codes to their asset names
LOCALE_NAMES = {
    "AR": "PreStrings_AR",
    "DE": "PreStrings_DE",
    "EN_US": "PreStrings_EN_US",
    "ES_LA": "PreStrings_ES_LA",
    "FR": "PreStrings_FR",
    "JA": "PreStrings_JA",
    "KR": "PreStrings_KR",
    "PT_BR": "PreStrings_PT_BR",
    "RU": "PreStrings_RU",
    "TH": "PreStrings_TH",
    "VI": "PreStrings_VI",
    "ZH_CH": "PreStrings_ZH_CH",
    "ZH_TW": "PreStrings_ZH_TW",
}

# Find the GUID files in the APK that contain PreStrings TextAssets
print("[*] Scanning APK for PreStrings GUID files...")
guid_map = {}  # locale -> (zip_entry_name, UnityPy_env, UnityPy_obj)
with zipfile.ZipFile(APK, 'r') as z:
    for n in z.namelist():
        if not n.startswith('assets/bin/Data/') or not len(n.split('/')[-1]) == 32:
            continue
        if '.' in n.split('/')[-1] or '-' in n.split('/')[-1]:
            continue  # not a GUID file
        try:
            raw = z.read(n)
            env = UnityPy.load(io.BytesIO(raw))
        except:
            continue
        for obj in env.objects:
            if obj.type.name != 'TextAsset':
                continue
            data = obj.read()
            nm = getattr(data, 'm_Name', '') or ''
            if not nm.startswith('PreStrings_'):
                continue
            locale = nm[len('PreStrings_'):]
            if locale in LOCALE_NAMES:
                guid_map[locale] = (n, env, obj, data)
                print(f"  Found: {n} -> {nm}")

print(f"\n[*] Found {len(guid_map)} PreStrings files")

changed = 0
for locale, (entry_name, env, obj, data) in guid_map.items():
    xml_path = XML_DIR / f"Strings_{locale}.xml"
    if not xml_path.exists():
        print(f"  [!] {xml_path} not found, skipping {locale}")
        continue
    full_xml = xml_path.read_bytes()
    print(f"  [{locale}] Replacing {len(data.m_Script)} bytes with {len(full_xml)} bytes...")

    # Get raw serialized data, replace the m_Script portion
    raw_data = bytearray(obj.get_raw_data())
    nm_len = int.from_bytes(raw_data[0:4], 'little')
    after_name = 4 + nm_len
    # Build new raw data
    new_raw = bytearray()
    new_raw.extend(raw_data[0:4])
    new_raw.extend(raw_data[4:4+nm_len])
    while len(new_raw) % 4 != 0:
        new_raw.append(0)
    new_raw.extend(len(full_xml).to_bytes(4, 'little'))
    new_raw.extend(full_xml)
    while len(new_raw) % 4 != 0:
        new_raw.append(0)
    obj.set_raw_data(bytes(new_raw))
    changed += 1

if changed == 0:
    print("[=] No PreStrings files modified")
else:
    print(f"[+] Modified {changed} PreStrings file(s)")

# Save changes back to APK
tmp = APK.with_suffix(".prestrings.tmp")
with zipfile.ZipFile(APK, 'r') as zin, zipfile.ZipFile(tmp, 'w') as zout:
    all_bytes = {}
    for n in zin.namelist():
        raw = zin.read(n)
        all_bytes[n] = raw
    # Update modified GUID files
    for locale, (entry_name, env, obj, data) in guid_map.items():
        xml_path = XML_DIR / f"Strings_{locale}.xml"
        if not xml_path.exists():
            continue
        new_file = env.file.save()
        all_bytes[entry_name] = new_file
        print(f"  [>] Updated {entry_name} ({len(new_file)} bytes)")
    for info in zin.infolist():
        body = all_bytes.get(info.filename, zin.read(info.filename))
        zinfo = zipfile.ZipInfo(info.filename, date_time=info.date_time)
        zinfo.compress_type = info.compress_type
        zinfo.external_attr = info.external_attr
        zinfo.internal_attr = info.internal_attr
        zinfo.create_system = info.create_system
        zout.writestr(zinfo, body)
os.replace(tmp, APK)
print(f"\n[=] Patched APK written: {APK}")
