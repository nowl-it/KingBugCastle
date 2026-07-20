"""Delete existing crystals and grant every (weapon, main_altar, sub_altar) combo.
Main=15, sub=14 (main strictly higher so GetMaxBuildingIdx picks the right one).
Run: python3 grant_rift_crystals.py
"""
import sys
sys.path.insert(0, "/home/nowl/Code/kgc/server")
import playerdb

UID = "dev-0001"
ALL_RIFT_WEAPON_IDS = [10000, 11000, 12000, 13000, 14000, 15000]
ALTAR_COUNT = 9

def make_crystal(cid, weapon_id, main_idx, sub_idx):
    levels = [0] * ALTAR_COUNT
    levels[main_idx] = 15
    levels[sub_idx] = 14  # strictly lower so GetMaxBuildingIdx picks main
    return {
        "id": cid, "weaponId": weapon_id, "mainBuildingIdx": main_idx,
        "buildingLevels": levels, "rarity": 5, "ceilCount": 0, "state": 0,
        "createdAt": "2026-07-20T12:00:00.000Z",
        "updatedAt": "2026-07-20T12:00:00.000Z",
    }

def main():
    st = playerdb.load(UID)
    old_count = len(st.get("riftCrystals", []))
    st["riftCrystals"] = []

    cid = 1
    crystals = []
    for wid in ALL_RIFT_WEAPON_IDS:
        for main_idx in range(ALTAR_COUNT):
            for sub_idx in range(ALTAR_COUNT):
                if sub_idx == main_idx:
                    continue
                crystals.append(make_crystal(cid, wid, main_idx, sub_idx))
                cid += 1

    st["riftCrystals"] = crystals
    playerdb.save(UID, st)
    total = len(ALL_RIFT_WEAPON_IDS) * ALTAR_COUNT * (ALTAR_COUNT - 1)
    print(f"Deleted {old_count} old crystals")
    print(f"Created {len(crystals)} crystals ({len(ALL_RIFT_WEAPON_IDS)} weapons × {ALTAR_COUNT} main × {ALTAR_COUNT-1} sub)")

if __name__ == "__main__":
    main()
