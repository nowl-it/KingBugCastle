#!/usr/bin/env python3
"""Extract relic/treasure/accessory/skin webp art from the v172.0.01 APK bundles.

Outputs to webui-next/public/assets/{relics,treasures,accessories,skins}/<id>.webp.
Run: python3 cli/extract_game_data_art.py <apk-dir-or-extracted-dir>
"""
import os
import sys
import re
import io
import xml.etree.ElementTree as ET

import UnityPy
from PIL import Image

from bundle_extract import extract_android_bundles

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
XML = os.path.join(REPO, "server", "xml_live")
OUT = os.path.join(REPO, "server", "webui-next", "public", "assets")

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "apk", "xapk_extracted_v17201")
BUNDLE_DIR = "/tmp/opencode/kgc_all"

if not os.path.isdir(BUNDLE_DIR) or not os.listdir(BUNDLE_DIR):
    apk = os.path.join(SRC, "base_assets.apk")
    extract_android_bundles(apk, BUNDLE_DIR)

env = UnityPy.load(BUNDLE_DIR)
sprites = {}
for obj in env.objects:
    if obj.type.name == "Sprite":
        sprites[obj.read().m_Name] = obj
print("sprites loaded:", len(sprites))


def save(sprite_name, outdir, fname, size=256):
    obj = sprites.get(sprite_name)
    if not obj:
        return False
    try:
        img = obj.read().image
    except Exception as e:
        print(f"  skip {sprite_name}: {e}")
        return False
    img = img.convert("RGBA")
    img.thumbnail((size, size), Image.LANCZOS)
    os.makedirs(outdir, exist_ok=True)
    img.save(os.path.join(outdir, fname), "WEBP", quality=85)
    return True


def walk(fname):
    return ET.parse(os.path.join(XML, fname)).getroot()


# --- relics: Artifact_Icon_<id> (shared icons possible) ----------------------
n = 0
for el in walk("Artifacts.xml"):
    sp = el.findtext("Sprite")
    if sp and save(sp, os.path.join(OUT, "relics"), f"{el.get('ID')}.webp"):
        n += 1
print("relics:", n)

# --- treasures: TreasureIcon_<id> --------------------------------------------
n = 0
for el in walk("Treasures.xml"):
    if save(f"TreasureIcon_{el.get('ID')}", os.path.join(OUT, "treasures"), f"{el.get('ID')}.webp"):
        n += 1
print("treasures:", n)

# --- accessories: AccessoryIcon_<TypeName>_Default ----------------------------
TYPE_NAMES = {1: "Necklace", 2: "Bracelet", 3: "Ring", 4: "Earring"}
n = 0
for el in walk("FixedAccessoryPresets.xml"):
    t = TYPE_NAMES.get(int(el.findtext("Type") or 0))
    if t and save(f"AccessoryIcon_{t}_Default", os.path.join(OUT, "accessories"), f"{el.get('ID')}.webp"):
        n += 1
print("accessories:", n)

# --- skins: per-skin <Sprite> -------------------------------------------------
n = 0
for el in walk("Skins.xml"):
    sp = el.findtext("Sprite")
    if sp and save(sp, os.path.join(OUT, "skins"), f"{el.get('ID')}.webp"):
        n += 1
print("skins:", n)
