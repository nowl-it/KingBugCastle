#!/usr/bin/env python3
"""Extract all bảo cụ (Treasure) assets from KGC v169.1.04 into ~/Downloads/baoCu/"""

import os
import re
import shutil
from pathlib import Path
from PIL import Image

UNITY_BASE = Path("/home/nowl/Code/kgc/unity/v169.1.04/169.1.04/UnityProject/ExportedProject/Assets")
XML_DIR = Path("/home/nowl/Code/kgc/unity/v169.1.04/xml_extracted")
TEXTURE_DIR = UNITY_BASE / "Texture2D"
TREASURE_UI = UNITY_BASE / "02_UI/UI_Treasure"
OUT = Path.home() / "Downloads/baoCu"

# Sprite atlases
ATLASES = {
    "TreasureIcon": TEXTURE_DIR / "sactx-0-1024x512-Uncompressed-TreasureIcon-4ef30a3d.png",
    "TreasureSkillIcon": TEXTURE_DIR / "sactx-0-512x256-Uncompressed-TreasureSkillIcon-e8d4de60.png",
    "TreasureCardIllust": TEXTURE_DIR / "sactx-0-2048x2048-Uncompressed-TreasureCardIllust-b73bfc77.png",
}

# Sprite atlas GUID -> atlas key mapping (for lookup)
ATLAS_GUIDS = {
    "a93b55a0684a704439e7167f2d3be2f9": "TreasureIcon",
    "831cb409d62d26646b1cbf95d7402cd8": "TreasureSkillIcon",
    "b73bfc77": "TreasureCardIllust",  # partial, may need update
}

def parse_sprite_rect(asset_path):
    """Parse x, y, width, height from a Unity Sprite .asset file."""
    text = Path(asset_path).read_text(errors='replace')
    def get_val(key):
        m = re.search(rf'{key}:\s*([\d.]+)', text)
        return float(m.group(1)) if m else None
    # Find m_Rect block
    m = re.search(r'm_Rect:.*?x:\s*([\d.]+).*?y:\s*([\d.]+).*?width:\s*([\d.]+).*?height:\s*([\d.]+)', text, re.DOTALL)
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)))

def get_atlas_guid(asset_path):
    """Extract texture GUID from Sprite .asset file."""
    text = Path(asset_path).read_text(errors='replace')
    m = re.search(r'texture:\s*\{fileID:\s*\d+,\s*guid:\s*([a-f0-9]+)', text)
    return m.group(1) if m else None

def crop_sprite(atlas_img, rect, out_path):
    """Crop sprite from atlas. Unity Y is flipped (bottom-left origin)."""
    x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    atlas_h = atlas_img.height
    # Unity: y=0 is bottom. PIL: y=0 is top. Flip y.
    top = atlas_h - y - h
    left = x
    cropped = atlas_img.crop((left, top, left + w, top + h))
    cropped.save(out_path, "PNG")

def extract_sprites_from_dir(asset_dir, out_dir, atlas_path, prefix):
    """Extract all sprites from a directory of .asset files."""
    if not atlas_path.exists():
        print(f"  [WARN] Atlas not found: {atlas_path}")
        return 0
    atlas = Image.open(atlas_path).convert("RGBA")
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for asset_file in sorted(Path(asset_dir).glob("*.asset")):
        rect = parse_sprite_rect(asset_file)
        if not rect:
            print(f"  [SKIP] No rect in {asset_file.name}")
            continue
        name = asset_file.stem
        out_path = out_dir / f"{name}.png"
        try:
            crop_sprite(atlas, rect, out_path)
            count += 1
        except Exception as e:
            print(f"  [ERR] {name}: {e}")
    return count

def copy_pngs(src_dir, out_dir, pattern="*.png"):
    """Copy all PNG files from src_dir to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for p in sorted(Path(src_dir).glob(pattern)):
        shutil.copy2(p, out_dir / p.name)
        count += 1
    return count

def copy_xml_files(xml_dir, out_dir, names):
    """Copy specific XML files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for name in names:
        src = Path(xml_dir) / name
        if src.exists():
            shutil.copy2(src, out_dir / name)
            count += 1
        else:
            print(f"  [MISS] {name}")
    return count

def main():
    print(f"Output: {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. TreasureIcon (sprite atlas crop)
    print("\n[1/6] TreasureIcon (crop from atlas)...")
    n = extract_sprites_from_dir(
        TREASURE_UI / "TreasureIcon",
        OUT / "icons",
        ATLASES["TreasureIcon"],
        "TreasureIcon"
    )
    print(f"  -> {n} icons")

    # 2. TreasureSkillIcon (sprite atlas crop)
    print("\n[2/6] TreasureSkillIcon (crop from atlas)...")
    n = extract_sprites_from_dir(
        TREASURE_UI / "TreasureSkillIcon",
        OUT / "skill_icons",
        ATLASES["TreasureSkillIcon"],
        "TreasureSkillIcon"
    )
    print(f"  -> {n} skill icons")

    # 3. TreasureIllust (PNG files)
    print("\n[3/6] TreasureIllust (direct PNG)...")
    n = copy_pngs(TREASURE_UI / "TreasureIllust", OUT / "illust")
    print(f"  -> {n} illust PNGs")

    # 4. TreasureCard (PNG files)
    print("\n[4/6] TreasureCard (direct PNG)...")
    n = copy_pngs(TREASURE_UI / "TreasureCard", OUT / "card")
    print(f"  -> {n} card PNGs")

    # 5. TreasureFrame_Big (PNG files for UI frames)
    print("\n[5/6] TreasureFrame (UI frames)...")
    n = copy_pngs(TREASURE_UI / "TreasureFrame_Big", OUT / "frames")
    print(f"  -> {n} frame PNGs")

    # 6. XML data
    print("\n[6/6] XML config data...")
    xml_files = [
        "Treasures.xml",
        "TreasureBuffDatas.xml",
        "TreasureConstants.xml",
        "TreasureCardIllust.xml" if (XML_DIR / "TreasureCardIllust.xml").exists() else None,
    ]
    xml_files = [f for f in xml_files if f]
    n = copy_xml_files(XML_DIR, OUT / "xml", xml_files)
    print(f"  -> {n} XML files")

    # Summary
    print("\n=== Done ===")
    total = sum(1 for _ in OUT.rglob("*") if _.is_file())
    print(f"Total files: {total}")
    print(f"Saved to: {OUT}")

    # Print directory tree
    for d in sorted(OUT.iterdir()):
        if d.is_dir():
            cnt = len(list(d.glob("*")))
            print(f"  {d.name}/  ({cnt} files)")

if __name__ == "__main__":
    main()
