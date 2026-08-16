"""Rift Weapons (균열 장비) and Rift Crystals (균열 수정) Subsystem.

Implements all 15+ game client operations, crafting, enhancement, reroll, dismantling,
crystal charging with pity mechanics, gauge purchasing, deck equipping, archive/wiki,
and state persistence.

All formulas, costs, and probabilities are parsed directly from:
- `server/xml_live/RiftWeaponConstants.xml`
- `server/xml_live/RiftWeaponBuffs.xml`
- `server/xml_live/RiftWeapons.xml`
"""
import copy
import itertools
import random
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from common import admin_log, body_int, body_list, now_iso
from config import XML_DIR
from state import save_state

srv = None  # Live server module, injected via register()

DUST_ITEM_ID = 8000
ALL_RIFT_WEAPON_IDS = [10000, 11000, 12000, 13000, 14000, 15000]
RIFT_BUILDING_COUNT = 9  # 9 altars in Buildings.xml (indices 0..8)
RIFT_BUILDING_MAX_LEVEL = 15
RIFT_CRYSTAL_RARITIES = {1: "Common", 2: "UnCommon", 3: "Rare", 4: "Epic", 5: "Legendary"}

_cache = {}


def _parse_xml(xml_dir=XML_DIR):
    key = str(xml_dir)
    if key in _cache:
        return _cache[key]

    constants_path = Path(xml_dir) / "RiftWeaponConstants.xml"
    buffs_path = Path(xml_dir) / "RiftWeaponBuffs.xml"
    weapons_path = Path(xml_dir) / "RiftWeapons.xml"

    # 1. Level Cost Table
    level_costs = {}
    reroll_costs = {"Common": 1000, "Rare": 3000, "Special": 10000}
    dismantle_rewards = {"Common": 40, "Rare": 200, "Special": 500}
    crystal_data = {}
    gold_cost_ratio = 5
    gauge_buy_costs = [10, 20, 30, 30, 30, 30, 30, 30, 30, 30]
    gauge_buy_amount = 100
    gauge_max = 1000
    reset_cash_cost = 250
    reset_level = 15

    if constants_path.exists():
        root = ET.parse(constants_path).getroot()
        for cost in root.findall(".//LevelCost/Cost"):
            lvl = int(cost.attrib["Level"])
            level_costs[lvl] = {
                "success": float(cost.attrib.get("Success", 0)),
                "fail": float(cost.attrib.get("Fail", 0)),
                "down": float(cost.attrib.get("Down", 0)),
                "broken": float(cost.attrib.get("Broken", 0)),
                "dust": int(cost.attrib.get("Cost", 0)),
                "cash": int(cost.attrib.get("CashCost", -1)),
            }
        gcr = root.find(".//LevelCost/GoldCostRatio")
        if gcr is not None and gcr.text:
            gold_cost_ratio = int(gcr.text.strip())

        for rc in root.findall(".//RerollCost/Cost"):
            reroll_costs[rc.attrib["Rarity"]] = int(rc.attrib["GoldCost"])

        for dr in root.findall(".//DismantleRewards/DismantleReward"):
            rw = dr.find("Reward")
            if rw is not None:
                dismantle_rewards[dr.attrib["Rarity"]] = int(rw.attrib["Count"])

        for cd in root.findall(".//RiftCrystalData/CrystalData"):
            rarity = cd.attrib["Rarity"]
            dust_str = cd.attrib.get("Dust", "50~100")
            dust_parts = [int(x) for x in dust_str.split("~")]
            crystal_data[rarity] = {
                "common": float(cd.attrib.get("Common", 0)),
                "rare": float(cd.attrib.get("Rare", 0)),
                "special": float(cd.attrib.get("Special", 0)),
                "dust_min": dust_parts[0],
                "dust_max": dust_parts[1] if len(dust_parts) > 1 else dust_parts[0],
                "gauge": int(cd.attrib.get("Gauge", 20)),
                "ceil": int(cd.attrib.get("Ceil", "0")),
            }

        gbi = root.find(".//RiftGaugeBuyInformation")
        if gbi is not None and "Cost" in gbi.attrib:
            gauge_buy_costs = [int(x.strip()) for x in gbi.attrib["Cost"].split(",") if x.strip()]
            if gbi.text and gbi.text.strip():
                gauge_buy_amount = int(gbi.text.strip())

        gm = root.find(".//RiftGaugeMaxValue")
        if gm is not None and gm.text:
            gauge_max = int(gm.text.strip())

        rcc = root.find(".//RiftWeaponResetCashCost")
        if rcc is not None and rcc.text:
            reset_cash_cost = int(rcc.text.strip())

        rl = root.find(".//RiftWeaponResetLevel")
        if rl is not None and rl.text:
            reset_level = int(rl.text.strip())

    # 2. Altar Buff Pools
    altar_buffs = {}
    all_buff_ids = []
    if buffs_path.exists():
        root_b = ET.parse(buffs_path).getroot()
        for b in root_b.findall("BuffData"):
            b_id = int(b.attrib["ID"])
            all_buff_ids.append(b_id)
            bld_str = b.attrib.get("Building", "")
            if bld_str:
                blds = [int(x.strip()) for x in bld_str.split(",") if x.strip()]
                for bld in blds:
                    altar_buffs.setdefault(bld, []).append(b_id)

    # 3. Weapons
    weapons = ALL_RIFT_WEAPON_IDS
    if weapons_path.exists():
        root_w = ET.parse(weapons_path).getroot()
        w_ids = [int(rw.attrib["ID"]) for rw in root_w.findall("RiftWeapon") if "ID" in rw.attrib]
        if w_ids:
            weapons = w_ids

    data = {
        "level_costs": level_costs,
        "gold_cost_ratio": gold_cost_ratio,
        "reroll_costs": reroll_costs,
        "dismantle_rewards": dismantle_rewards,
        "crystal_data": crystal_data,
        "gauge_buy_costs": gauge_buy_costs,
        "gauge_buy_amount": gauge_buy_amount,
        "gauge_max": gauge_max,
        "reset_cash_cost": reset_cash_cost,
        "reset_level": reset_level,
        "altar_buffs": altar_buffs,
        "all_buff_ids": sorted(list(set(all_buff_ids))),
        "weapons": weapons,
    }
    _cache[key] = data
    return data


def _get_buff_options_for_altar(altar_idx, xml_dir=XML_DIR):
    data = _parse_xml(xml_dir)
    specific = data["altar_buffs"].get(altar_idx, [])
    wildcards = data["altar_buffs"].get(-1, [])
    pool = list(set(specific + wildcards))
    return pool if pool else data["all_buff_ids"]


def make_rift_weapon(i, rw_id, rarity=1, level=None, building_indexes=None, sub_stat=None, state=0):
    """Create a fully valid RiftWeaponModel.

    rarity uses the client enum: None=0, Common=1, Rare=2, Special=3.
    Starting levels from RiftWeaponConstants.xml:
      Common (1) -> Lv 1  (1 altar active)
      Rare (2)   -> Lv 5  (2 altars active)
      Special (3)-> Lv 15 (2 altars + 1 wildcard active)
    """
    rarity = max(1, min(3, rarity))
    if level is None:
        level = 15 if rarity == 3 else (5 if rarity == 2 else 1)

    if building_indexes is None or len(building_indexes) != 3 or building_indexes[2] != -1:
        # Pick 2 distinct altars (0..8) and -1 for slot 3
        # GetNameStr() checks buildingIndexes and skips < 0 (i.e. -1), matching exactly 2 altars!
        # Slot 3 accesses buildingIndexes[2] without throwing IndexOutOfRangeException.
        altars = list(range(RIFT_BUILDING_COUNT))
        random.shuffle(altars)
        building_indexes = [altars[0], altars[1], -1]

    if sub_stat is None or len(sub_stat) != 3:
        sub_stat = []
        for si in range(3):
            b_idx = building_indexes[si] if si < len(building_indexes) else -1
            pool = _get_buff_options_for_altar(b_idx)
            sub_stat.append(random.choice(pool) if pool else 0)

    now = now_iso(0)
    return {
        "id": i,
        "weaponId": rw_id,
        "buildingIndexes": building_indexes,
        "level": max(1, min(40, level)),
        "rarity": rarity,
        "broken": False,
        "subStat": sub_stat,
        "state": state,
        "createdAt": now,
        "updatedAt": now,
    }


def make_rift_crystal(i, rw_id, main_idx=None, rarity=1, building_levels=None, state=0):
    """Create a fully valid RiftCrystalModel."""
    data = _parse_xml()
    main_idx = (i % RIFT_BUILDING_COUNT) if main_idx is None else (main_idx % RIFT_BUILDING_COUNT)

    if building_levels is None or len(building_levels) != RIFT_BUILDING_COUNT:
        other_level = 10 if rarity >= 3 else 5
        main_level = 15 if rarity >= 4 else 12
        building_levels = [other_level] * RIFT_BUILDING_COUNT
        building_levels[main_idx] = main_level

    rarity = max(1, min(5, rarity))
    # ceilCount is the number of charges already performed towards pity (starts at 0)
    ceil_count = 0

    now = now_iso(0)
    return {
        "id": i,
        "weaponId": rw_id,
        "mainBuildingIdx": main_idx,
        "buildingLevels": building_levels,
        "rarity": rarity,
        "ceilCount": ceil_count,
        "state": state,
        "createdAt": now,
        "updatedAt": now,
    }


def make_all_legendary_crystals():
    """Generate the full set of 216 Legendary 2-altar crystals + 6 Universal All-Altar crystals."""
    crystals = []
    now = now_iso(0)

    # 1. 6 Universal All-Altar Crystals (all 9 altars at Max Lv. 15)
    for idx, w_id in enumerate(ALL_RIFT_WEAPON_IDS):
        crystal = {
            "id": idx + 1,
            "weaponId": w_id,
            "mainBuildingIdx": 0,
            "buildingLevels": [15] * RIFT_BUILDING_COUNT,
            "rarity": 5,  # Legendary (King God Rift Crystal)
            "ceilCount": 0,
            "state": 0,
            "createdAt": now,
            "updatedAt": now,
        }
        crystals.append(crystal)

    # 2. 216 Dedicated 2-Altar Crystals (36 combos per weapon)
    c_id = 100
    altar_pairs = list(itertools.combinations(range(RIFT_BUILDING_COUNT), 2))
    for w_id in ALL_RIFT_WEAPON_IDS:
        for a1, a2 in altar_pairs:
            b_levels = [0] * RIFT_BUILDING_COUNT
            b_levels[a1] = 15
            b_levels[a2] = 15
            crystal = {
                "id": c_id,
                "weaponId": w_id,
                "mainBuildingIdx": a1,
                "buildingLevels": b_levels,
                "rarity": 5,  # Legendary (King God Rift Crystal)
                "ceilCount": 0,
                "state": 0,
                "createdAt": now,
                "updatedAt": now,
            }
            crystals.append(crystal)
            c_id += 1
    return crystals


DEFAULT_RIFT_WEAPONS = [make_rift_weapon(i + 1, rwid) for i, rwid in enumerate(ALL_RIFT_WEAPON_IDS)]
DEFAULT_RIFT_CRYSTALS = [make_rift_crystal(i + 1, rwid, main_idx=i, rarity=(i % 5) + 1) for i, rwid in enumerate(ALL_RIFT_WEAPON_IDS)]


def _repair_rift_crystals(crystals):
    """Upgrade crystals saved before the shape was understood. Returns True if anything
    changed, so the caller can persist."""
    changed = False
    for c in crystals:
        if c.get("rarity") not in RIFT_CRYSTAL_RARITIES:
            c["rarity"] = 1
            changed = True
        levels = c.get("buildingLevels") or []
        if len(levels) != RIFT_BUILDING_COUNT:
            main = int(c.get("mainBuildingIdx", 0)) % max(RIFT_BUILDING_COUNT, 1)
            other = 5
            main_level = 15
            fixed = [min(int(v), RIFT_BUILDING_MAX_LEVEL) for v in levels[:RIFT_BUILDING_COUNT]]
            fixed += [other] * (RIFT_BUILDING_COUNT - len(fixed))
            fixed[main] = min(RIFT_BUILDING_MAX_LEVEL, max(main_level, fixed[main]))
            c["buildingLevels"] = fixed
            c["mainBuildingIdx"] = main
            changed = True
        else:
            for i in range(len(levels)):
                if levels[i] > RIFT_BUILDING_MAX_LEVEL:
                    levels[i] = RIFT_BUILDING_MAX_LEVEL
                    changed = True
    return changed


def _next_weapon_id(st):
    weapons = st.setdefault("riftWeapons", [])
    return max((w.get("id", 0) for w in weapons), default=0) + 1


def _next_crystal_id(st):
    crystals = st.setdefault("riftCrystals", [])
    return max((c.get("id", 0) for c in crystals), default=0) + 1


def ensure_rift_state(st):
    """Ensure all Rift state keys exist and are valid."""
    data = _parse_xml()
    changed = False

    # 1. Rift Weapons
    valid_weapon_ids = set()
    if "riftWeapons" not in st or not isinstance(st["riftWeapons"], list):
        st["riftWeapons"] = copy.deepcopy(DEFAULT_RIFT_WEAPONS)
        changed = True

    for w in st["riftWeapons"]:
        w_id = w.get("id")
        if w_id:
            valid_weapon_ids.add(w_id)
        r = w.get("rarity", 1)
        if r <= 0:
            w["rarity"] = 1
            changed = True
        elif r > 3:
            w["rarity"] = 3
            changed = True
        # Migrate buildingIndexes to [altar0, altar1, -1] (length 3, 3rd is -1)
        bi = w.get("buildingIndexes", [])
        if not isinstance(bi, list) or len(bi) != 3 or bi[2] != -1:
            a0 = bi[0] if isinstance(bi, list) and len(bi) > 0 and bi[0] >= 0 else 0
            a1 = bi[1] if isinstance(bi, list) and len(bi) > 1 and bi[1] >= 0 and bi[1] != a0 else (1 if a0 != 1 else 0)
            w["buildingIndexes"] = [a0, a1, -1]
            changed = True
        # Ensure subStat is a list of exactly 3 integers
        sub_stat = w.get("subStat")
        if not isinstance(sub_stat, list) or len(sub_stat) != 3:
            w["subStat"] = [0, 0, 0]
            changed = True

    # 2. Rift Crystals
    if "riftCrystals" not in st or not isinstance(st["riftCrystals"], list) or not st["riftCrystals"]:
        st["riftCrystals"] = copy.deepcopy(DEFAULT_RIFT_CRYSTALS)
        changed = True
    else:
        for c in st["riftCrystals"]:
            # If ceilCount was erroneously set to max ceil (e.g. 70), reset to 0
            rarity_name = RIFT_CRYSTAL_RARITIES.get(c.get("rarity", 1), "Common")
            max_ceil = data["crystal_data"].get(rarity_name, {}).get("ceil", 0)
            if max_ceil > 0 and c.get("ceilCount", 0) >= max_ceil:
                c["ceilCount"] = 0
                changed = True
        if _repair_rift_crystals(st["riftCrystals"]):
            changed = True

    # 3. Equipped Weapons: Dict[int, List[EquippedRiftWeaponData]]
    if "equippedRiftWeapons" not in st or not isinstance(st["equippedRiftWeapons"], dict):
        st["equippedRiftWeapons"] = {}
        changed = True
    else:
        # Migrate old string keys to int keys and remove orphan equipped weapons
        eq = st["equippedRiftWeapons"]
        str_keys = [k for k in eq if isinstance(k, str)]
        for sk in str_keys:
            try:
                eq[int(sk)] = eq.pop(sk)
            except Exception:
                eq.pop(sk, None)
            changed = True

        for p_key, p_list in list(eq.items()):
            if not isinstance(p_list, list):
                eq[p_key] = []
                changed = True
                continue
            # Remove any equipped weapon that does not exist in st['riftWeapons']
            cleaned = [e for e in p_list if isinstance(e, dict) and e.get("riftWeaponId") in valid_weapon_ids]
            if len(cleaned) != len(p_list):
                eq[p_key] = cleaned
                changed = True

    # 4. Rift Gauge
    if "riftGauge" not in st:
        st["riftGauge"] = data["gauge_max"]  # Start with full gauge (1000)
        changed = True

    # 5. RogueLike DLCs (Unlocks Altars 6=Death, 7=Immortality, 8=Domination)
    all_dlcs = [
        {"dlc": 2400, "tier": 2},
        {"dlc": 2410, "tier": 2},
        {"dlc": 2420, "tier": 2},
    ]
    if not st.get("rogueLikeBoughtDlcs") or len(st.get("rogueLikeBoughtDlcs", [])) < 3:
        st["rogueLikeBoughtDlcs"] = all_dlcs
        changed = True

    # 6. Rift Weapon Archives
    if "riftWeaponArchives" not in st:
        st["riftWeaponArchives"] = []
        changed = True

    return changed


def _equipped_list_for_preset(st, preset_idx):
    equipped_dict = st.setdefault("equippedRiftWeapons", {})
    return equipped_dict.get(preset_idx, [])


def _equipped_weapon_ids_for_preset(st, preset_idx):
    eq_list = _equipped_list_for_preset(st, preset_idx)
    return [e["riftWeaponId"] for e in eq_list if "riftWeaponId" in e]


# ==============================================================================
# ROUTE HANDLERS
# ==============================================================================


def r_rift_weapon_inventory(body, st):
    """GET/POST /rift-weapon -> RiftWeaponInventoryResponseModel."""
    if ensure_rift_state(st):
        save_state(st)
    equipped_dict = st.setdefault("equippedRiftWeapons", {})
    resp = {
        "riftWeapons": st.get("riftWeapons", []),
        "equippedWeapons": equipped_dict,
    }
    admin_log(f"[RIFT DEBUG] weapon-inventory -> {len(resp['riftWeapons'])} weapons, equipped={len(equipped_dict)} presets")
    return resp


def r_rift_crystal_inventory(body, st):
    """GET/POST /rift-weapon/crystal-inventory -> RiftCrystalInventoryResponseModel."""
    if ensure_rift_state(st):
        save_state(st)
    resp = {
        "riftCrystals": st.get("riftCrystals", []),
    }
    admin_log(f"[RIFT DEBUG] crystal-inventory -> {len(resp['riftCrystals'])} crystals")
    return resp


def r_rift_weapon_equip(body, st):
    """POST /rift-weapon/equip -> RiftWeaponResultResponseModel."""
    ensure_rift_state(st)
    weapon_id = body_int(body.get("riftWeaponId"), 0)
    preset_idx = body_int(body.get("equipPreset"), 0)

    p_key = preset_idx
    equipped_dict = st.setdefault("equippedRiftWeapons", {})
    raw_list = equipped_dict.get(p_key) if p_key in equipped_dict else equipped_dict.get(str(p_key), [])
    preset_list = list(raw_list or [])

    # Find the weapon to equip
    weapon = next((w for w in st.get("riftWeapons", []) if w.get("id") == weapon_id), None)
    if weapon is not None:
        w_type_id = weapon.get("weaponId", 10000)
        slot_idx = (w_type_id - 10000) // 1000 if w_type_id in ALL_RIFT_WEAPON_IDS else body_int(body.get("targetIdx"), 0)
    else:
        slot_idx = body_int(body.get("targetIdx"), 0)

    # Remove any weapon occupying the same slot, or this weapon if already in another slot
    filtered = [e for e in preset_list if e.get("index") != slot_idx and e.get("riftWeaponId") != weapon_id]

    if weapon is not None:
        filtered.append({"deckPreset": preset_idx, "index": slot_idx, "riftWeaponId": weapon_id})

    # Keep list sorted by slot index (0..5)
    filtered.sort(key=lambda x: x.get("index", 0))

    equipped_dict[p_key] = filtered
    if str(p_key) in equipped_dict and str(p_key) != p_key:
        equipped_dict[str(p_key)] = filtered
    save_state(st)

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "deletedRiftWeapons": [],
        "rewardListResponseData": None,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "upgradeState": 0,
        "equippedWeaponIds": [e["riftWeaponId"] for e in filtered],
    }


def r_rift_weapon_release_equip(body, st):
    """POST /rift-weapon/release-equip -> RiftWeaponResultResponseModel."""
    ensure_rift_state(st)
    weapon_id = body_int(body.get("riftWeaponId"), 0)
    slot_idx = body_int(body.get("targetIdx"), -1)
    preset_idx = body_int(body.get("equipPreset"), 0)

    p_key = preset_idx
    equipped_dict = st.setdefault("equippedRiftWeapons", {})
    raw_list = equipped_dict.get(p_key) if p_key in equipped_dict else equipped_dict.get(str(p_key), [])
    preset_list = list(raw_list or [])

    filtered = [
        e
        for e in preset_list
        if not (
            (weapon_id and e.get("riftWeaponId") == weapon_id)
            or (slot_idx >= 0 and e.get("index") == slot_idx)
        )
    ]
    filtered.sort(key=lambda x: x.get("index", 0))
    equipped_dict[p_key] = filtered
    if str(p_key) in equipped_dict and str(p_key) != p_key:
        equipped_dict[str(p_key)] = filtered
    save_state(st)

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "deletedRiftWeapons": [],
        "rewardListResponseData": None,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "upgradeState": 0,
        "equippedWeaponIds": [e["riftWeaponId"] for e in filtered],
    }


def r_rift_weapon_upgrade(body, st):
    """POST /rift-weapon/upgrade -> RiftWeaponResultResponseModel.

    UpgradeState return codes (ResourceRiftWeaponConstant.UpgradeState):
    0 = SUCCESS (level +1)
    1 = FAIL (level unchanged)
    2 = DOWN (level -1)
    3 = BROKEN (weapon broken)
    """
    ensure_rift_state(st)
    data = _parse_xml()

    weapon_id = body_int(body.get("riftWeaponId"), 0)
    use_cash = bool(body.get("useCash", False))
    preset_idx = body_int(body.get("equipPreset"), 0)

    weapon = next((w for w in st.get("riftWeapons", []) if w.get("id") == weapon_id), None)
    if weapon is None or weapon.get("broken", False):
        return {
            "riftWeapons": st.get("riftWeapons", []),
            "deletedRiftWeapons": [],
            "rewardListResponseData": None,
            "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "upgradeState": 1,
            "equippedWeaponIds": _equipped_weapon_ids_for_preset(st, preset_idx),
        }

    cur_level = weapon.get("level", 1)
    rarity = weapon.get("rarity", 1)
    min_level = 15 if rarity == 3 else (5 if rarity == 2 else 1)
    max_level = 40 if rarity == 3 else (15 if rarity == 2 else 10)

    if cur_level >= max_level:
        return {
            "riftWeapons": st.get("riftWeapons", []),
            "deletedRiftWeapons": [],
            "rewardListResponseData": None,
            "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "upgradeState": 1,
            "equippedWeaponIds": _equipped_weapon_ids_for_preset(st, preset_idx),
        }

    target_level = cur_level + 1
    cost_info = data["level_costs"].get(target_level, {"success": 100, "fail": 0, "down": 0, "broken": 0, "dust": 10, "cash": -1})
    dust_needed = cost_info["dust"]
    gold_needed = dust_needed * data["gold_cost_ratio"]
    cash_needed = cost_info["cash"] if (use_cash and cost_info["cash"] > 0) else 0

    # Deduct resources
    if srv:
        srv._take_item(st, DUST_ITEM_ID, dust_needed)
    st["gold"] = max(0, st.get("gold", 0) - gold_needed)
    if cash_needed > 0:
        st["cash"] = max(0, st.get("cash", 0) - cash_needed)

    # Calculate outcome
    roll = random.uniform(0, 100)
    success_rate = cost_info["success"]
    fail_rate = cost_info["fail"]
    down_rate = cost_info["down"]
    broken_rate = cost_info["broken"]

    if use_cash and cash_needed > 0:
        # Cash protection turns Down and Broken into standard Fail
        down_rate = 0
        broken_rate = 0
        fail_rate = 100 - success_rate

    upgrade_state = 1  # FAIL (level unchanged)
    if roll < success_rate:
        # SUCCESS (0) -> Level increases
        upgrade_state = 0
        weapon["level"] = min(max_level, cur_level + 1)
    elif roll < success_rate + fail_rate:
        # FAIL (1) -> Level unchanged
        upgrade_state = 1
    elif roll < success_rate + fail_rate + down_rate:
        # DOWN (2) -> Level decreases
        upgrade_state = 2
        weapon["level"] = max(min_level, cur_level - 1)
    else:
        # BROKEN (3) -> Weapon broken
        upgrade_state = 3
        weapon["broken"] = True

    weapon["updatedAt"] = now_iso(0)
    save_state(st)

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "deletedRiftWeapons": [],
        "rewardListResponseData": None,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "upgradeState": upgrade_state,
        "equippedWeaponIds": _equipped_weapon_ids_for_preset(st, preset_idx),
    }


def r_rift_weapon_reroll(body, st):
    """POST /rift-weapon/re-roll -> RiftWeaponResultResponseModel."""
    ensure_rift_state(st)
    data = _parse_xml()
    admin_log(f"[RIFT REROLL] body={body}")

    # Unity may wrap request bodies in a "model" key — unwrap if present
    if "model" in body and isinstance(body["model"], dict):
        admin_log(f"[RIFT REROLL] unwrapping 'model' key: {body['model']}")
        body = body["model"]

    weapon_id = body_int(body.get("riftWeaponId"), 0)
    target_idx = body_int(body.get("targetIdx"), 0)
    target_option_id = body_int(body.get("targetOptionId"), 0)
    admin_log(f"[RIFT REROLL] weapon_id={weapon_id} target_idx={target_idx} target_option_id={target_option_id} raw_targetOptionId={body.get('targetOptionId')} raw_targetIdx={body.get('targetIdx')}")
    preset_idx = body_int(body.get("equipPreset"), 0)

    weapon = next((w for w in st.get("riftWeapons", []) if w.get("id") == weapon_id), None)
    if weapon is None or target_idx < 0 or target_idx >= 3:
        return {
            "riftWeapons": st.get("riftWeapons", []),
            "deletedRiftWeapons": [],
            "rewardListResponseData": None,
            "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "upgradeState": 0,
            "equippedWeaponIds": _equipped_weapon_ids_for_preset(st, preset_idx),
        }

    rarity_str = "Common" if weapon.get("rarity", 1) == 1 else ("Rare" if weapon.get("rarity", 1) == 2 else "Special")
    cost_gold = data["reroll_costs"].get(rarity_str, 1000)
    st["gold"] = max(0, st.get("gold", 0) - cost_gold)

    # Set chosen substat option (Forge target option)
    if target_option_id > 0:
        new_opt = target_option_id
    else:
        bi = weapon.get("buildingIndexes", [0, 1, -1])
        altar_idx = bi[target_idx] if target_idx < len(bi) else -1
        pool = _get_buff_options_for_altar(altar_idx)
        current_opt = weapon["subStat"][target_idx] if "subStat" in weapon else 0
        valid_new = [opt for opt in pool if opt != current_opt]
        new_opt = random.choice(valid_new) if valid_new else current_opt

    if "subStat" not in weapon:
        weapon["subStat"] = [0, 0, 0]
    while len(weapon["subStat"]) < 3:
        weapon["subStat"].append(0)

    weapon["subStat"][target_idx] = new_opt
    weapon["updatedAt"] = now_iso(0)
    save_state(st)

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "deletedRiftWeapons": [],
        "rewardListResponseData": None,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "upgradeState": 0,
        "equippedWeaponIds": _equipped_weapon_ids_for_preset(st, preset_idx),
    }


def r_rift_weapon_dismantle(body, st):
    """POST /rift-weapon/dismantle -> RiftWeaponResultResponseModel."""
    admin_log(f"[RIFT DEBUG] weapon-dismantle body: {body}")
    ensure_rift_state(st)
    data = _parse_xml()

    dismantle_ids = body_list(body.get("dismantleRiftWeaponIds"))
    dismantle_set = set(dismantle_ids)

    weapons = st.get("riftWeapons", [])
    kept_weapons = []
    deleted_ids = []
    total_dust = 0

    for w in weapons:
        w_id = w.get("id")
        if w_id in dismantle_set and not (w.get("state", 0) & 1):  # Not locked
            deleted_ids.append(w_id)
            rarity_str = "Common" if w.get("rarity", 1) == 1 else ("Rare" if w.get("rarity", 1) == 2 else "Special")
            total_dust += data["dismantle_rewards"].get(rarity_str, 40)
        else:
            kept_weapons.append(w)

    st["riftWeapons"] = kept_weapons

    # Remove deleted weapons from equipped lists
    equipped_dict = st.setdefault("equippedRiftWeapons", {})
    for p_key, p_list in equipped_dict.items():
        equipped_dict[p_key] = [e for e in p_list if e.get("riftWeaponId") not in dismantle_set]

    # Grant dust
    if srv and total_dust > 0:
        srv._grant_reward(st, "Item", DUST_ITEM_ID, total_dust)

    save_state(st)

    admin_log(f"[RIFT DEBUG] weapon-dismantle done: ids={deleted_ids}, dust={total_dust}, kept={len(kept_weapons)}")

    reward_data = None
    if srv:
        reward_data = srv._reward_list_data([{"type": "Item", "id": DUST_ITEM_ID, "count": total_dust}])

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "deletedRiftWeapons": deleted_ids,
        "rewardListResponseData": reward_data,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "upgradeState": 0,
        "equippedWeaponIds": _equipped_weapon_ids_for_preset(st, 0),
    }


def r_rift_weapon_reset_weapon(body, st):
    """POST /rift-weapon/reset-weapon -> RiftWeaponResultResponseModel."""
    ensure_rift_state(st)
    data = _parse_xml()

    weapon_id = body_int(body.get("riftWeaponId"), 0)
    preset_idx = body_int(body.get("equipPreset"), 0)

    weapon = next((w for w in st.get("riftWeapons", []) if w.get("id") == weapon_id), None)
    if weapon is not None:
        cost_cash = data["reset_cash_cost"]
        st["cash"] = max(0, st.get("cash", 0) - cost_cash)
        weapon["level"] = data["reset_level"]
        weapon["broken"] = False
        weapon["updatedAt"] = now_iso(0)
        save_state(st)

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "deletedRiftWeapons": [],
        "rewardListResponseData": None,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "upgradeState": 0,
        "equippedWeaponIds": _equipped_weapon_ids_for_preset(st, preset_idx),
    }


def r_rift_weapon_set_state(body, st):
    """POST /rift-weapon/set-state -> RiftWeaponResultResponseModel."""
    ensure_rift_state(st)
    weapon_id = body_int(body.get("riftWeaponId"), 0)
    state = body_int(body.get("state"), 0)
    preset_idx = body_int(body.get("equipPreset"), 0)

    weapon = next((w for w in st.get("riftWeapons", []) if w.get("id") == weapon_id), None)
    if weapon is not None:
        weapon["state"] = state
        weapon["updatedAt"] = now_iso(0)
        save_state(st)

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "deletedRiftWeapons": [],
        "rewardListResponseData": None,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "upgradeState": 0,
        "equippedWeaponIds": _equipped_weapon_ids_for_preset(st, preset_idx),
    }


def r_rift_crystal_charge(body, st):
    """POST /rift-weapon/crystal-charge -> RiftCrystalResultResponseModel."""
    admin_log(f"[RIFT DEBUG] crystal-charge body: {body}")
    ensure_rift_state(st)
    data = _parse_xml()

    crystal_id = body_int(body.get("crystalId"), 0)
    charge_count = max(1, body_int(body.get("count"), 1))
    crystals = st.setdefault("riftCrystals", [])
    crystal = next((c for c in crystals if c.get("id") == crystal_id), None)

    if crystal is None:
        return {
            "riftWeapons": st.get("riftWeapons", []),
            "riftCrystals": crystals,
            "deletedCrystals": [],
            "riftGauge": st.get("riftGauge", 0),
            "rewardListResponseData": None,
            "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "playerHeart": st.get("heart", 0),
        }

    rarity_int = crystal.get("rarity", 1)
    rarity_name = RIFT_CRYSTAL_RARITIES.get(rarity_int, "Common")
    c_info = data["crystal_data"].get(rarity_name, {"common": 100, "rare": 0, "special": 0, "dust_min": 25, "dust_max": 75, "gauge": 20, "ceil": 0})

    # Deduct gauge for all charges at once (unless Infinity Rift Energy is enabled)
    gauge_cost = c_info.get("gauge", 20)
    current_gauge = st.get("riftGauge", 0)
    total_gauge_cost = gauge_cost * charge_count
    if st.get("infinityRiftEnergy", False):
        st["riftGauge"] = max(current_gauge, 1000)
    else:
        st["riftGauge"] = max(0, current_gauge - total_gauge_cost)

    total_dust = 0
    created_weapons = []
    reward_items = []
    ceil_count = crystal.get("ceilCount", 0)
    max_ceil = c_info.get("ceil", 0)

    for _ in range(charge_count):
        rolled_rarity = 1
        # Pity check: if max_ceil > 0 and ceil_count + 1 >= max_ceil -> Guaranteed Special (3)
        if max_ceil > 0 and (ceil_count + 1) >= max_ceil:
            rolled_rarity = 3
            ceil_count = 0
        else:
            roll = random.uniform(0, 100)
            c_rate = c_info["common"]
            r_rate = c_info["rare"]
            if roll < c_rate:
                rolled_rarity = 1
            elif roll < c_rate + r_rate:
                rolled_rarity = 2
            else:
                rolled_rarity = 3

            if rolled_rarity == 3:
                ceil_count = 0  # Early pity reset
            elif max_ceil > 0:
                ceil_count += 1

        main_bld = crystal.get("mainBuildingIdx", 0)
        b_levels = crystal.get("buildingLevels", [])
        # Pick secondary altar from other altars configured on this crystal (level > 0)
        candidate_altars = [b for b in range(len(b_levels)) if b != main_bld and b_levels[b] > 0]
        if candidate_altars:
            weights = [b_levels[b] for b in candidate_altars]
            sub_bld = random.choices(candidate_altars, weights=weights, k=1)[0]
        else:
            candidate_altars = [b for b in range(RIFT_BUILDING_COUNT) if b != main_bld]
            sub_bld = random.choice(candidate_altars)
        selected_altars = [main_bld, sub_bld, -1]  # Altar0, Altar1, -1 (for slot 3 wildcard)

        new_w_id = _next_weapon_id(st)
        new_weapon = make_rift_weapon(
            i=new_w_id,
            rw_id=crystal.get("weaponId", 10000),
            rarity=rolled_rarity,
            level=None,  # Auto set starting level by rarity (Rare=5, Special=15)
            building_indexes=selected_altars,
        )
        st.setdefault("riftWeapons", []).append(new_weapon)
        created_weapons.append(new_weapon)

        dust_for_this = random.randint(c_info["dust_min"], c_info["dust_max"])
        total_dust += dust_for_this
        reward_items.append({"type": "Item", "id": DUST_ITEM_ID, "count": dust_for_this})

    crystal["ceilCount"] = ceil_count

    if srv and total_dust > 0:
        srv._grant_reward(st, "Item", DUST_ITEM_ID, total_dust)

    # Note: A Rift Crystal is NOT deleted on normal charge (it has 70 charges)
    deleted_crystals = []

    save_state(st)

    reward_data = None
    if srv and reward_items:
        reward_data = srv._reward_list_data(reward_items)

    admin_log(f"[RIFT DEBUG] crystal-charge done: {charge_count}x, gauge={st.get('riftGauge', 0)}, ceilCount={ceil_count}/{max_ceil}, weapons={len(st.get('riftWeapons', []))}")

    return {
        "riftWeapons": created_weapons,  # Newly crafted weapons for popup
        "riftCrystals": st.get("riftCrystals", []),
        "deletedCrystals": deleted_crystals,
        "riftGauge": st.get("riftGauge", 0),
        "rewardListResponseData": reward_data,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "playerHeart": st.get("heart", 0),
    }


def r_rift_crystal_destroy(body, st):
    """POST /rift-weapon/crystal-destroy -> RiftCrystalResultResponseModel."""
    admin_log(f"[RIFT DEBUG] crystal-destroy body: {body}")
    ensure_rift_state(st)
    crystal_id = body_int(body.get("crystalId"), 0)
    use_heart = bool(body.get("useHeart", False))

    crystals = st.setdefault("riftCrystals", [])
    crystal = next((c for c in crystals if c.get("id") == crystal_id), None)

    if crystal is None:
        return {
            "riftWeapons": st.get("riftWeapons", []),
            "riftCrystals": crystals,
            "deletedCrystals": [],
            "riftGauge": st.get("riftGauge", 0),
            "rewardListResponseData": None,
            "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "playerHeart": st.get("heart", 0),
        }

    rarity = crystal.get("rarity", 1)
    base_dust = {1: 30, 2: 60, 3: 120, 4: 200, 5: 350}.get(rarity, 30)

    if use_heart:
        st["heart"] = max(0, st.get("heart", 0) - 15)
        base_dust = int(base_dust * 2.0)

    if srv and base_dust > 0:
        srv._grant_reward(st, "Item", DUST_ITEM_ID, base_dust)

    crystals.remove(crystal)
    save_state(st)

    admin_log(f"[RIFT DEBUG] crystal-destroy done: crystal_id={crystal_id}, rarity={rarity}, dust={base_dust}")

    reward_data = None
    if srv:
        reward_data = srv._reward_list_data([{"type": "Item", "id": DUST_ITEM_ID, "count": base_dust}])

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "riftCrystals": crystals,
        "deletedCrystals": [crystal_id],
        "riftGauge": st.get("riftGauge", 0),
        "rewardListResponseData": reward_data,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "playerHeart": st.get("heart", 0),
    }


def r_rift_crystal_set_state(body, st):
    """POST /rift-weapon/set-crystal-state -> RiftCrystalResultResponseModel."""
    ensure_rift_state(st)
    crystal_id = body_int(body.get("crystalId"), 0)
    state = body_int(body.get("state"), 0)

    crystals = st.setdefault("riftCrystals", [])
    crystal = next((c for c in crystals if c.get("id") == crystal_id), None)
    if crystal is not None:
        crystal["state"] = state
        crystal["updatedAt"] = now_iso(0)
        save_state(st)

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "riftCrystals": crystals,
        "deletedCrystals": [],
        "riftGauge": st.get("riftGauge", 0),
        "rewardListResponseData": None,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "playerHeart": st.get("heart", 0),
    }


def r_rift_buy_gauge(body, st):
    """POST /rift-weapon/buy-rift-gauge -> RiftCrystalResultResponseModel."""
    admin_log(f"[RIFT DEBUG] buy-gauge body: {body}")
    ensure_rift_state(st)
    data = _parse_xml()

    costs = data["gauge_buy_costs"]
    buy_idx = st.get("gaugeBuyCount", 0)
    cost = costs[min(buy_idx, len(costs) - 1)] if costs else 30
    gauge_gain = data.get("gauge_buy_amount", 100)

    st["cash"] = max(0, st.get("cash", 0) - cost)
    st["riftGauge"] = min(data["gauge_max"], st.get("riftGauge", 0) + gauge_gain)
    st["gaugeBuyCount"] = buy_idx + 1
    save_state(st)

    admin_log(f"[RIFT DEBUG] buy-gauge done: cost={cost}, gauge={st['riftGauge']}, buyCount={st['gaugeBuyCount']}")

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "riftCrystals": st.get("riftCrystals", []),
        "deletedCrystals": [],
        "riftGauge": st["riftGauge"],
        "rewardListResponseData": None,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "playerHeart": st.get("heart", 0),
    }


def r_rift_archive(body, st):
    """POST /kg-wiki/rift-weapon/archive -> RiftWeaponResultResponseModel."""
    ensure_rift_state(st)
    archive_id = body_int(body.get("archiveId") or body.get("id"), 0)
    archives = st.setdefault("riftWeaponArchives", [])
    if archive_id and archive_id not in archives:
        archives.append(archive_id)
        save_state(st)

    return {
        "riftWeapons": st.get("riftWeapons", []),
        "deletedRiftWeapons": [],
        "rewardListResponseData": None,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "upgradeState": 0,
        "equippedWeaponIds": _equipped_weapon_ids_for_preset(st, 0),
    }


def r_rift_archive_delete(body, st):
    """POST /kg-wiki/rift-weapon/archive-delete -> KGWikiResponseModel."""
    ensure_rift_state(st)
    archive_id = body_int(body.get("archiveId") or body.get("id"), 0)
    archives = st.setdefault("riftWeaponArchives", [])
    if archive_id in archives:
        archives.remove(archive_id)
        save_state(st)

    return {
        "riftWeaponArchives": archives,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
    }


def handlers():
    """Mapping of all Rift route paths to handlers for OVERRIDES."""
    return {
        "/rift-weapon": r_rift_weapon_inventory,
        "/rift-weapon/crystal-inventory": r_rift_crystal_inventory,
        "/rift-weapon/equip": r_rift_weapon_equip,
        "/rift-weapon/release-equip": r_rift_weapon_release_equip,
        "/rift-weapon/upgrade": r_rift_weapon_upgrade,
        "/rift-weapon/re-roll": r_rift_weapon_reroll,
        "/rift-weapon/dismantle": r_rift_weapon_dismantle,
        "/rift-weapon/reset-weapon": r_rift_weapon_reset_weapon,
        "/rift-weapon/set-state": r_rift_weapon_set_state,
        "/rift-weapon/crystal-charge": r_rift_crystal_charge,
        "/rift-weapon/crystal-destroy": r_rift_crystal_destroy,
        "/rift-weapon/set-crystal-state": r_rift_crystal_set_state,
        "/rift-weapon/buy-rift-gauge": r_rift_buy_gauge,
        "/kg-wiki/rift-weapon/archive": r_rift_archive,
        "/kg-wiki/rift-weapon/archive-delete": r_rift_archive_delete,
    }


# ==============================================================================
# FASTAPI REGISTRATION
# ==============================================================================


def register(app, srv_module):
    """Wire Rift routes into live server module."""
    global srv
    srv = srv_module
