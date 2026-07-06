#!/usr/bin/env python3
"""
GUI extractor for KGC Treasures (보구 / bao cu) art.

Run with the venv that has UnityPy + Pillow:
    ~/Code/kgc/api/.venv/bin/python scripts/extract_treasures_gui.py

Pick image types, hit "Quet / Demo" to preview thumbnails, untick any you
don't want, choose an export folder, then "Export da chon".
"""

from kgc_asset_gui import AssetType, ExtractConfig, run

TYPES = [
    AssetType("icon", "Icon (nho)", r"TreasureIcon_\d+",
              ["sprites_assets_all", "treasureicon"]),
    AssetType("skillicon", "Skill Icon", r"TreasureSkillIcon_\d+",
              ["sprites_assets_all", "treasureskillicon"]),
    AssetType("illust", "Illust (art)", r"TreasureIllust_\d+",
              ["illusts_assets_all"]),
    AssetType("illust_bg", "Illust BG", r"TreasureIllust_\d+_BG",
              ["illusts_assets_all"]),
    AssetType("card", "Card Illust", r"TreasureCardIllust_\d+",
              ["illusts_assets_all", "treasurecardillust"]),
    AssetType("card02", "Card Illust 02", r"TreasureCardIllust_\d+_02",
              ["illusts_assets_all", "treasurecardillust"]),
]

if __name__ == "__main__":
    run(ExtractConfig("KGC - Extract Treasures (Bao cu)", TYPES))
