"""Rift crystals must be nameable and cover every altar.

Two defects the client renders instead of rejecting, so only a test catches them:

  * `rarity` 0 is `ResourceRiftWeaponConstant.CrystalRarity.None`. The name goes through
    `RiftCrystalNameFormat` = "{1} Rift Crystal of {0}" with {1} =
    `RiftCrystalNameKeyword_<rarity>` - and `RiftCrystalNameKeyword_None` exists in no
    locale, so the panel prints the raw key.
  * `buildingLevels` is one level per altar, and `RiftCrystalModel.GetMaxBuildingIdx`
    (v171 RVA 0x2CCA1B4) walks the whole list returning the index of the largest value.
    A list shorter than the altar count can only ever return an index inside itself, so
    every crystal named itself after altar 0.
"""
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import server


def strings():
    return {e.get("Key"): e.text
            for e in ET.parse(server.XML_DIR / "Strings_EN_US.xml").getroot().findall("String")
            if e.get("Key")}


def argmax(levels):
    """Mirror of GetMaxBuildingIdx: first index holding the maximum, -1 if empty."""
    best, best_i = -1, -1
    for i, v in enumerate(levels):
        if v > best:
            best, best_i = v, i
    return best_i


def main():
    s = strings()

    # Numeric suffixes only - BuildingName_Normal ("Default Altar") is not an altar slot.
    altars = [k for k in s if re.fullmatch(r"BuildingName_\d+", k)]
    assert server.RIFT_BUILDING_COUNT == len(altars), \
        f"altar count from Buildings.xml ({server.RIFT_BUILDING_COUNT}) disagrees with " \
        f"BuildingName_<n> strings ({len(altars)})"

    assert s.get("RiftCrystalNameFormat"), "RiftCrystalNameFormat missing"
    for rarity, name in server.RIFT_CRYSTAL_RARITIES.items():
        key = f"RiftCrystalNameKeyword_{name}"
        assert s.get(key), f"rarity {rarity} maps to {key}, which has no string"
    assert not s.get("RiftCrystalNameKeyword_None"), \
        "RiftCrystalNameKeyword_None now exists - rarity 0 may no longer be broken"

    crystals = server.DEFAULT_RIFT_CRYSTALS
    assert crystals, "no default rift crystals"
    seen_main = set()
    for c in crystals:
        assert c["rarity"] in server.RIFT_CRYSTAL_RARITIES, \
            f"crystal {c['id']} rarity {c['rarity']} has no name keyword"
        assert len(c["buildingLevels"]) == server.RIFT_BUILDING_COUNT, \
            f"crystal {c['id']}: {len(c['buildingLevels'])} levels for " \
            f"{server.RIFT_BUILDING_COUNT} altars"
        assert max(c["buildingLevels"]) <= server.RIFT_BUILDING_MAX_LEVEL, \
            f"crystal {c['id']} exceeds the altar level cap"
        assert argmax(c["buildingLevels"]) == c["mainBuildingIdx"], \
            f"crystal {c['id']}: GetMaxBuildingIdx would say " \
            f"{argmax(c['buildingLevels'])}, mainBuildingIdx says {c['mainBuildingIdx']}"
        seen_main.add(c["mainBuildingIdx"])
    assert len(seen_main) == len(crystals), \
        f"crystals share altars ({sorted(seen_main)}) - they would all read the same"

    # Repair path: exactly the shape found in the live save before the fix.
    legacy = [{"id": 1, "weaponId": 10000, "mainBuildingIdx": 0, "buildingLevels": [0, 0, 0],
               "rarity": 0, "ceilCount": 0, "state": 0}]
    assert server._repair_rift_crystals(legacy) is True, "legacy crystal not detected"
    fixed = legacy[0]
    assert fixed["rarity"] in server.RIFT_CRYSTAL_RARITIES
    assert len(fixed["buildingLevels"]) == server.RIFT_BUILDING_COUNT
    assert argmax(fixed["buildingLevels"]) == fixed["mainBuildingIdx"]
    assert server._repair_rift_crystals(legacy) is False, "repair is not idempotent"

    name = s["RiftCrystalNameFormat"].replace(
        "{1}", s[f"RiftCrystalNameKeyword_{server.RIFT_CRYSTAL_RARITIES[fixed['rarity']]}"]).replace(
        "{0}", (s.get(f"BuildingName_{fixed['mainBuildingIdx']}") or "").replace("Altar of ", ""))
    print(f"ok: {len(crystals)} crystals, {server.RIFT_BUILDING_COUNT} altars, "
          f"repaired legacy renders as {name!r}")


if __name__ == "__main__":
    main()
