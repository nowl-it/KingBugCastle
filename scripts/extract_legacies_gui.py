#!/usr/bin/env python3
"""
GUI extractor for KGC Legacies (유산 / Legacy / Relic) art.

In the game data the Legacy asset prefix is "Artifact" (Artifact_<id>).

Run with the venv that has UnityPy + Pillow:
    ~/Code/kgc/api/.venv/bin/python scripts/extract_legacies_gui.py

Pick image types, hit "Quet / Demo" to preview thumbnails, untick any you
don't want, choose an export folder, then "Export da chon".
"""

from kgc_asset_gui import AssetType, ExtractConfig, run

# Legacy art is fragmented across sprites/characters/prefabs bundles:
# Artifact_<id> = the legacy art (sizes vary 29x26 .. 540x540), some are
# animated spritesheets (Artifact_<id> 240x80 + frames _0.._5). The
# Artifact_Icon_<id>a/b sprites are tiny UI decoration (9x3) - not the
# legacy art - so they are intentionally not offered here.
_BUNDLES = ["sprites_assets_all", "characters_assets_all", "prefabs_assets_all", "artifacts"]

TYPES = [
    AssetType("art", "Art (chinh)", r"Artifact_\d+", _BUNDLES),
    AssetType("art_var", "Art variant (_NN/_99)", r"Artifact_\d+_\w+", _BUNDLES),
]

if __name__ == "__main__":
    run(ExtractConfig("KGC - Extract Legacies (Artifact)", TYPES))
