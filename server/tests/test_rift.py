"""Comprehensive test suite for Rift Weapons and Rift Crystals subsystem.

Tests every client operation, formula, cost deduction, probability, pity counter,
and state mutation.
"""
import copy
import pathlib
import sys
import tempfile

_SERVER = pathlib.Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "players.db"
playerdb.init()

from tests.seed import one_account
one_account()

import server
import rift


def _fresh_state():
    st = server.load_state()
    rift.ensure_rift_state(st)
    st["riftWeapons"] = [rift.make_rift_weapon(i + 1, rwid) for i, rwid in enumerate(rift.ALL_RIFT_WEAPON_IDS)]
    st["gold"] = 1_000_000
    st["cash"] = 10_000
    st["heart"] = 500
    st["riftGauge"] = 500
    # Seed player with 50,000 Dust
    inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
    if rift.DUST_ITEM_ID in inv["itemIds"]:
        idx = inv["itemIds"].index(rift.DUST_ITEM_ID)
        inv["counts"][idx] = 50_000
    else:
        inv["itemIds"].append(rift.DUST_ITEM_ID)
        inv["counts"].append(50_000)
    server.save_state(st)
    return st


def test_inventory_fetch():
    st = _fresh_state()
    res = rift.r_rift_weapon_inventory({}, st)
    assert "riftWeapons" in res
    assert len(res["riftWeapons"]) >= 6
    assert "equippedWeapons" in res

    c_res = rift.r_rift_crystal_inventory({}, st)
    assert "riftCrystals" in c_res
    assert len(c_res["riftCrystals"]) >= 6
    print("ok test_inventory_fetch")


def test_equip_and_release():
    st = _fresh_state()
    weapons = st["riftWeapons"]
    w1_id = weapons[0]["id"]  # weaponId 10000 -> Slot 0
    w2_id = weapons[1]["id"]  # weaponId 11000 -> Slot 1

    # Add a second Lance (weaponId 10000) with new ID to test slot 0 replacement
    w3 = copy.deepcopy(weapons[0])
    w3["id"] = 999
    st["riftWeapons"].append(w3)
    w3_id = 999

    # Equip weapon 1 (Lance) at preset 0 -> goes to slot 0
    res = rift.r_rift_weapon_equip({"riftWeaponId": w1_id, "equipPreset": 0}, st)
    assert w1_id in res["equippedWeaponIds"]
    assert st["equippedRiftWeapons"][0][0]["riftWeaponId"] == w1_id
    assert st["equippedRiftWeapons"][0][0]["index"] == 0

    # Equip weapon 2 (Mask) at preset 0 -> goes to slot 1 (both equipped!)
    res2 = rift.r_rift_weapon_equip({"riftWeaponId": w2_id, "equipPreset": 0}, st)
    assert w1_id in res2["equippedWeaponIds"]
    assert w2_id in res2["equippedWeaponIds"]
    assert len(st["equippedRiftWeapons"][0]) == 2

    # Equip weapon 3 (another Lance) at preset 0 -> replaces weapon 1 in slot 0
    res3 = rift.r_rift_weapon_equip({"riftWeaponId": w3_id, "equipPreset": 0}, st)
    assert w3_id in res3["equippedWeaponIds"]
    assert w2_id in res3["equippedWeaponIds"]
    assert w1_id not in res3["equippedWeaponIds"]
    assert len(st["equippedRiftWeapons"][0]) == 2

    # Release weapon 2
    res4 = rift.r_rift_weapon_release_equip({"riftWeaponId": w2_id, "equipPreset": 0}, st)
    assert w2_id not in res4["equippedWeaponIds"]
    assert w3_id in res4["equippedWeaponIds"]
    assert len(st["equippedRiftWeapons"][0]) == 1

    print("ok test_equip_and_release")


def test_weapon_upgrade_levels_and_costs():
    st = _fresh_state()
    weapon = st["riftWeapons"][0]
    weapon["level"] = 1
    weapon["rarity"] = 2  # Special (max lv 40)
    weapon["broken"] = False
    server.save_state(st)

    init_gold = st["gold"]
    init_dust = server._item_count(st, rift.DUST_ITEM_ID)

    # Upgrade Level 1 -> 2 (100% success rate in constants)
    res = rift.r_rift_weapon_upgrade({"riftWeaponId": weapon["id"], "useCash": False}, st)
    assert res["upgradeState"] == 0  # 0 = Success (ResourceRiftWeaponConstant.UpgradeState.SUCCESS)
    assert weapon["level"] == 2
    assert st["gold"] < init_gold
    assert server._item_count(st, rift.DUST_ITEM_ID) < init_dust

    print("ok test_weapon_upgrade_levels_and_costs")


def test_cash_protection_upgrade():
    st = _fresh_state()
    weapon = st["riftWeapons"][0]
    weapon["level"] = 21  # Level 21 has broken chance
    weapon["rarity"] = 2
    weapon["broken"] = False
    server.save_state(st)

    init_cash = st["cash"]
    # Upgrade with Cash protection (useCash=True)
    res = rift.r_rift_weapon_upgrade({"riftWeaponId": weapon["id"], "useCash": True}, st)
    assert res["upgradeState"] in (0, 1)  # Can only be fail or success, never broken
    assert not weapon["broken"]
    assert st["cash"] < init_cash

    print("ok test_cash_protection_upgrade")


def test_substat_reroll():
    st = _fresh_state()
    weapon = st["riftWeapons"][0]
    weapon["subStat"] = [0, 10, 20]
    weapon["buildingIndexes"] = [0, 1, -1]
    server.save_state(st)

    init_gold = st["gold"]
    res = rift.r_rift_weapon_reroll({"riftWeaponId": weapon["id"], "targetIdx": 0}, st)
    assert st["gold"] < init_gold
    # Substat for slot 0 should be updated
    assert isinstance(weapon["subStat"][0], int)
    print("ok test_substat_reroll")


def test_weapon_dismantle():
    st = _fresh_state()
    # Create two temporary weapons to dismantle
    w1 = rift.make_rift_weapon(901, 10000, rarity=1)  # Common
    w2 = rift.make_rift_weapon(902, 11000, rarity=2)  # Rare
    st["riftWeapons"].extend([w1, w2])
    server.save_state(st)

    init_dust = server._item_count(st, rift.DUST_ITEM_ID)
    res = rift.r_rift_weapon_dismantle({"dismantleRiftWeaponIds": [901, 902]}, st)
    assert 901 in res["deletedRiftWeapons"]
    assert 902 in res["deletedRiftWeapons"]
    # Common (40) + Rare (200) = 240 dust granted
    assert server._item_count(st, rift.DUST_ITEM_ID) == init_dust + 240
    # Weapons should be removed from state
    assert not any(w["id"] in (901, 902) for w in st["riftWeapons"])

    print("ok test_weapon_dismantle")


def test_weapon_reset():
    st = _fresh_state()
    weapon = st["riftWeapons"][0]
    weapon["level"] = 35
    weapon["broken"] = True
    server.save_state(st)

    init_cash = st["cash"]
    res = rift.r_rift_weapon_reset_weapon({"riftWeaponId": weapon["id"]}, st)
    assert st["cash"] == init_cash - 250
    assert weapon["level"] == 15
    assert not weapon["broken"]

    print("ok test_weapon_reset")


def test_crystal_charge_and_pity():
    st = _fresh_state()
    # Create a crystal with pity ceil = 1 (guaranteed Special!)
    c = rift.make_rift_crystal(888, 12000, main_idx=3, rarity=5)
    c["ceilCount"] = 1
    st["riftCrystals"].append(c)
    server.save_state(st)

    init_weapons_count = len(st["riftWeapons"])
    res = rift.r_rift_crystal_charge({"crystalId": 888}, st)
    # Crystal is NOT deleted on normal charge
    assert len(res["deletedCrystals"]) == 0
    assert any(c["id"] == 888 for c in st["riftCrystals"])
    # Response returns ONLY newly crafted weapons (for popup animation)
    assert len(res["riftWeapons"]) == 1
    crafted = res["riftWeapons"][0]
    assert crafted["weaponId"] == 12000
    assert crafted["buildingIndexes"][0] == 3  # Main altar matches crystal mainBuildingIdx
    assert len(crafted["buildingIndexes"]) == 3
    assert crafted["buildingIndexes"][2] == -1  # 3rd is -1 for GetNameStr() and slot 3
    assert len(st["riftWeapons"]) == init_weapons_count + 1

    print("ok test_crystal_charge_and_pity")


def test_crystal_destroy():
    st = _fresh_state()
    c = rift.make_rift_crystal(777, 13000, rarity=3)  # Rare crystal
    st["riftCrystals"].append(c)
    server.save_state(st)

    init_dust = server._item_count(st, rift.DUST_ITEM_ID)
    init_heart = st["heart"]

    # Destroy with useHeart=True (bonus dust)
    res = rift.r_rift_crystal_destroy({"crystalId": 777, "useHeart": True}, st)
    assert 777 in res["deletedCrystals"]
    assert st["heart"] == init_heart - 15
    # Rare crystal base 120 * 2.0 = 240 dust
    assert server._item_count(st, rift.DUST_ITEM_ID) == init_dust + 240

    print("ok test_crystal_destroy")


def test_buy_gauge():
    st = _fresh_state()
    st["riftGauge"] = 200
    init_cash = st["cash"]
    server.save_state(st)

    res = rift.r_rift_buy_gauge({}, st)
    assert res["riftGauge"] == 300
    assert st["cash"] < init_cash

    print("ok test_buy_gauge")


def test_wiki_archive():
    st = _fresh_state()
    res1 = rift.r_rift_archive({"archiveId": 10000}, st)
    assert 10000 in st["riftWeaponArchives"]

    res2 = rift.r_rift_archive_delete({"archiveId": 10000}, st)
    assert 10000 not in st["riftWeaponArchives"]

    print("ok test_wiki_archive")


def main():
    test_inventory_fetch()
    test_equip_and_release()
    test_weapon_upgrade_levels_and_costs()
    test_cash_protection_upgrade()
    test_substat_reroll()
    test_weapon_dismantle()
    test_weapon_reset()
    test_crystal_charge_and_pity()
    test_crystal_destroy()
    test_buy_gauge()
    test_wiki_archive()
    print("\nALL RIFT TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
