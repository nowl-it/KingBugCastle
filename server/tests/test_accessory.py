import copy
import pathlib
import sys
import tempfile
import pytest

_SERVER = pathlib.Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "players.db"
playerdb.init()

import accessory
from common import now_iso


@pytest.fixture
def clean_state():
    st = {
        "gold": 500000,
        "cash": 1000,
        "accessories": [
            {
                "id": 1,
                "accountId": 1,
                "unitId": 0,
                "slot": 0,
                "type": 1,  # Necklace
                "rarity": 3,
                "level": 1,
                "exp": 0,
                "synergy": 1,
                "state": 0,
                "data": {
                    "mainStat": "AtkPer",
                    "subStats": [
                        {"key": "AttackSpeedPer", "value": 2.5},
                        {"key": "BaseDef", "value": 40.0},
                    ],
                },
                "subStats": ["AttackSpeedPer", "BaseDef"],
                "subStatScores": [2.5, 2.0],
                "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
                "createdAt": now_iso(0),
                "updatedAt": now_iso(0),
                "usedThemeList": [],
                "isEarlyAccessModeTestAccessory": False,
            },
            {
                "id": 2,
                "accountId": 1,
                "unitId": 0,
                "slot": 1,
                "type": 2,  # Bracelet
                "rarity": 3,
                "level": 1,
                "exp": 0,
                "synergy": 1,
                "state": 0,
                "data": {
                    "mainStat": "BaseDef",
                    "subStats": [
                        {"key": "BaseDef", "value": 40.0},
                    ],
                },
                "subStats": ["BaseDef"],
                "subStatScores": [2.0],
                "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
                "createdAt": now_iso(0),
                "updatedAt": now_iso(0),
                "usedThemeList": [],
                "isEarlyAccessModeTestAccessory": False,
            },
            {
                "id": 3,
                "accountId": 1,
                "unitId": 0,
                "slot": 0,
                "type": 1,  # Another Necklace
                "rarity": 3,
                "level": 1,
                "exp": 0,
                "synergy": 2,
                "state": 1,  # Locked
                "data": {
                    "mainStat": "AtkPer",
                    "subStats": [
                        {"key": "AtkPer", "value": 3.0},
                    ],
                },
                "subStats": ["AtkPer"],
                "subStatScores": [3.0],
                "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
                "createdAt": now_iso(0),
                "updatedAt": now_iso(0),
                "usedThemeList": [],
                "isEarlyAccessModeTestAccessory": False,
            },
        ],
        "inventory": {
            "itemIds": [4000, 4100, 4101, 4200],
            "counts": [10, 10, 5, 5],
        },
        "accessoryPresets": [
            {"id": i, "slotName": f"Preset {i+1}", "accessories": []} for i in range(10)
        ],
    }
    return st


def test_accessory_inventory(clean_state):
    res = accessory.r_accessory_inventory({}, clean_state)
    assert "accessories" in res
    assert len(res["accessories"]) == 3
    assert res["accessories"][0]["id"] == 1


def test_accessory_equip_and_release(clean_state):
    # 1. Equip accessory 1 (Necklace) to unit 10000
    res = accessory.r_accessory_equip({"targetIds": [1], "unitId": 10000}, clean_state)
    acc1 = next(a for a in res["accessories"] if a["id"] == 1)
    assert acc1["unitId"] == 10000

    # 2. Equip accessory 3 (also Necklace) to unit 10000 -> acc1 should be unequipped
    res = accessory.r_accessory_equip({"targetIds": [3], "unitId": 10000}, clean_state)
    acc1 = next(a for a in res["accessories"] if a["id"] == 1)
    acc3 = next(a for a in res["accessories"] if a["id"] == 3)
    assert acc1["unitId"] == 0
    assert acc3["unitId"] == 10000

    # 3. Release equip on acc3
    res = accessory.r_accessory_release({"targetId": 3}, clean_state)
    acc3 = next(a for a in res["accessories"] if a["id"] == 3)
    assert acc3["unitId"] == 0


def test_accessory_add_exp_and_level_up(clean_state):
    # Accessory 1 is level 1, exp 0.
    # Level 2 needs 45 exp, 60 gold.
    # Consume 1x 4100 (gives 150 exp).
    prev_gold = clean_state["gold"]
    res = accessory.r_accessory_add_exp({
        "targetId": 1,
        "expItems": [{"id": 4100, "count": 1}],
    }, clean_state)

    acc1 = next(a for a in res["accessories"] if a["id"] == 1)
    assert acc1["level"] >= 2
    # Verify stone 4100 was deducted from inventory (was 10, now 9)
    inv_4100 = next(c for i, c in zip(clean_state["inventory"]["itemIds"], clean_state["inventory"]["counts"]) if i == 4100)
    assert inv_4100 == 9
    assert clean_state["gold"] < prev_gold


def test_accessory_dismantle(clean_state):
    # Acc 2 is level 1, unequipped, unlocked.
    # Acc 3 is locked (state=1).
    res = accessory.r_accessory_dismantle({"accessoryIds": [2, 3]}, clean_state)

    # Acc 2 should be deleted, Acc 3 should NOT be deleted
    assert 2 in res["deletedAccessories"]
    assert 3 not in res["deletedAccessories"]
    assert len(res["accessories"]) == 2
    assert not any(a["id"] == 2 for a in res["accessories"])
    assert any(a["id"] == 3 for a in res["accessories"])

    # Verify shards (4000) reward was granted (was 10, now at least 11)
    inv_4000 = next(c for i, c in zip(clean_state["inventory"]["itemIds"], clean_state["inventory"]["counts"]) if i == 4000)
    assert inv_4000 >= 11


def test_accessory_set_state(clean_state):
    # Acc 1 is state 0 (unlocked). Lock it.
    res = accessory.r_accessory_set_state({"targetIds": [1], "state": 1}, clean_state)
    acc1 = next(a for a in res["accessories"] if a["id"] == 1)
    assert acc1["state"] == 1

    # Unlock it
    res = accessory.r_accessory_set_state({"targetIds": [1], "state": 0}, clean_state)
    acc1 = next(a for a in res["accessories"] if a["id"] == 1)
    assert acc1["state"] == 0


def test_accessory_change_sub_stat(clean_state):
    # Acc 1 has AttackSpeedPer (2.5) and BaseDef (40.0). Reroll BaseDef.
    prev_cnt = next(c for i, c in zip(clean_state["inventory"]["itemIds"], clean_state["inventory"]["counts"]) if i == 4200)
    res = accessory.r_accessory_change_sub_stat({
        "accessoryId": 1,
        "targetSubStat": "BaseDef",
        "itemId": 4200,
    }, clean_state)

    acc1 = next(a for a in res["accessories"] if a["id"] == 1)
    assert "BaseDef" not in acc1["subStats"]
    assert len(acc1["subStats"]) == 2
    # Verify stone 4200 was deducted
    new_cnt = next(c for i, c in zip(clean_state["inventory"]["itemIds"], clean_state["inventory"]["counts"]) if i == 4200)
    assert new_cnt == prev_cnt - 1


def test_accessory_merge_duplicate_substats(clean_state):
    # Production bug: preset-seeded accessories carried 7 duplicate key
    # entries in data.subStats (one per tier line). The client renders
    # data.subStats, so changing one copy left the rest as "extra" stats.
    st = copy.deepcopy(clean_state)
    st["accessories"].append({
        "id": 99,
        "accountId": 1,
        "unitId": 0,
        "slot": 9,
        "type": 1,
        "rarity": 3,
        "level": 20,
        "exp": 0,
        "synergy": 0,
        "state": 0,
        "data": {
            "mainStat": "AtkPer",
            "subStats": [
                {"key": "BaseDefDen", "value": 4.0},
                {"key": "BaseDefDen", "value": 4.0},
                {"key": "BaseDefDen", "value": 4.0},
                {"key": "BaseDefDen", "value": 4.0},
                {"key": "BaseDefDen", "value": 4.0},
                {"key": "BaseDefDen", "value": 4.0},
                {"key": "BaseDefDen", "value": 2.0},
                {"key": "BaseDef", "value": 80.0},
            ],
        },
        "subStats": ["BaseDefDen", "BaseDef"],
        "subStatScores": [26.0, 4.0],
        "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
        "createdAt": now_iso(0),
        "updatedAt": now_iso(0),
        "usedThemeList": [],
        "isEarlyAccessModeTestAccessory": False,
    })
    accessory.ensure_accessory_state(st)
    acc = next(a for a in st["accessories"] if a["id"] == 99)
    keys = [e["key"] for e in acc["data"]["subStats"]]
    assert len(keys) == len(set(keys)) == 2
    den = next(e for e in acc["data"]["subStats"] if e["key"] == "BaseDefDen")
    assert den["value"] == 26.0

    res = accessory.r_accessory_change_sub_stat({
        "accessoryId": 99,
        "targetSubStat": "BaseDefDen",
        "itemId": 8400,
    }, st)
    acc = next(a for a in res["accessories"] if a["id"] == 99)
    data_keys = [e["key"] for e in acc["data"]["subStats"]]
    assert data_keys == ["AtkPer", "BaseDef"]
    assert "BaseDefDen" not in data_keys


def test_accessory_presets(clean_state):
    # 1. Fetch presets
    res = accessory.r_accessory_preset_list({}, clean_state)
    assert len(res["presets"]) == 10

    # 2. Set accessories for preset 0
    res = accessory.r_accessory_set_preset({"presetId": 0, "targetIds": [1, 2]}, clean_state)
    p0 = next(p for p in res["presets"] if p["id"] == 0)
    assert p0["accessories"] == [1, 2]

    # 3. Set name for preset 0
    res = accessory.r_accessory_set_preset_name({"presetId": 0, "presetName": "PvP Build"}, clean_state)
    p0 = next(p for p in res["presets"] if p["id"] == 0)
    assert p0["slotName"] == "PvP Build"
