"""Accessory subsystem routes for King God Castle private server.

Master-data accurate implementation of:
- GET /accessory -> AccessoryInventoryResponseModel
- POST /accessory, POST /accessory/equip -> AccessoryResultResponseModel
- POST /accessory/release-equip -> AccessoryResultResponseModel
- POST /accessory/equip-tutorial -> AccessoryResultResponseModel
- POST /accessory/add-exp -> AccessoryResultResponseModel
- POST /accessory/dismantle -> AccessoryResultResponseModel
- POST /accessory/set-state, POST /accessory/set-state-all -> AccessoryResultResponseModel
- POST /accessory/change-sub-stat -> AccessoryResultResponseModel
- GET /accessory/preset -> AccessoryPresetResponseModel
- POST /accessory/preset, POST /accessory/set-preset -> AccessoryPresetResponseModel
- POST /accessory/set-preset-name -> AccessoryPresetResponseModel
"""

import copy
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from common import now_iso
from state import save_state

XML_DIR = Path(__file__).resolve().parent.parent / "xml_live"

# ValuePerScore units from AccessoryConstants.xml SubStatInformation
# BaseDef and BaseMDef are 20.0 (1 score = 20 def), everything else is 1.0 (1 score = 1%)
VALUE_PER_SCORE: Dict[str, float] = {
    "BaseDef": 20.0,
    "BaseMDef": 20.0,
    "AtkPer": 1.0,
    "MAtkPer": 1.0,
    "HpPer": 1.0,
    "AttackSpeedPer": 1.0,
    "BaseCriticalProb": 1.0,
    "BaseCriticalDamageMul": 1.0,
    "BaseMCriticalProb": 1.0,
    "BaseMCriticalDamageMul": 1.0,
    "BaseSpecialDamageMul": 1.0,
    "BaseDefPen": 1.0,
    "BaseDefDen": 1.0,
}

# Exp stone / item values (AddAccessoryExp from InventoryItems.xml)
EXP_ITEM_VALUES: Dict[int, int] = {
    4000: 50,    # Shard
    4100: 150,   # Enhance Stone
    4101: 450,   # King Enhance Stone
    4102: 1350,  # God Enhance Stone
}

# Reroll stone ID
REROLL_STONE_ITEM_ID = 4200

# Cache for parsed XML constants
_CONST_CACHE: Dict[str, Any] = {}


def _load_constants():
    if _CONST_CACHE:
        return _CONST_CACHE

    const_path = XML_DIR / "AccessoryConstants.xml"
    if not const_path.exists():
        return {}

    tree = ET.parse(const_path)
    root = tree.getroot()

    # 1. Level Costs
    level_costs: Dict[int, Dict[str, int]] = {}
    for c in root.findall(".//AccessoryLevelCost/Cost"):
        lvl = int(c.get("Level", "1"))
        need_exp = int(c.get("NeedExp", "0"))
        need_gold = int(c.get("NeedGold", "0"))
        level_costs[lvl] = {"needExp": need_exp, "needGold": need_gold}

    # 2. Dismantle Info
    dismantle_info: Dict[int, List[Dict[str, int]]] = {}
    for d in root.findall(".//AccessoryDismantleInfo/DismantleInfo"):
        lvl = int(d.get("Level", "1"))
        rewards = []
        for item in d.findall("InventoryItem"):
            rewards.append({
                "id": int(item.get("ID", "4000")),
                "count": int(item.get("Count", "1")),
            })
        dismantle_info[lvl] = rewards

    # 3. MainStat Information -> SubStat pools
    main_stat_info: Dict[str, Dict[str, Any]] = {}
    for m in root.findall(".//MainStatInformation/MainStatInfo"):
        mst = m.findtext("StatTypeStr")
        inc = float(m.findtext("IncreaseByLevel", "0.5"))
        subs_node = m.find("SubStats")
        subs = [s.tag for s in subs_node] if subs_node is not None else []
        if mst:
            main_stat_info[mst] = {"increaseByLevel": inc, "subStats": subs}

    # 4. Level Events (Special / Rare)
    level_events: Dict[str, Dict[int, List[Dict[str, Any]]]] = {"Special": {}, "Rare": {}, "Common": {}}
    for section in root.findall(".//AccessoryLevelEvent/*"):
        sec_name = section.tag
        if sec_name not in level_events:
            level_events[sec_name] = {}
        for ev in section.findall("Event"):
            lvl = int(ev.get("Level", "1"))
            ev_type = ev.get("Type", "UpgradeSlot")
            ev_val = int(ev.get("Value", "1"))
            probs = []
            for p in ev.findall(".//Percentage"):
                probs.append((float(p.get("Score", "1")), float(p.get("Prob", "10"))))
            if lvl not in level_events[sec_name]:
                level_events[sec_name][lvl] = []
            level_events[sec_name][lvl].append({
                "type": ev_type,
                "value": ev_val,
                "probs": probs,
            })

    _CONST_CACHE["level_costs"] = level_costs
    _CONST_CACHE["dismantle_info"] = dismantle_info
    _CONST_CACHE["main_stat_info"] = main_stat_info
    _CONST_CACHE["level_events"] = level_events
    return _CONST_CACHE


def _presets():
    preset_path = XML_DIR / "FixedAccessoryPresets.xml"
    if not preset_path.exists():
        return {}
    by_id = {p.get("ID"): p for p in ET.parse(preset_path).getroot().findall("FixedAccessoryPreset")}
    out = {}
    for pid, p in by_id.items():
        src = by_id.get(p.get("Inherit"), p) if p.get("Inherit") else p
        out[int(pid)] = src
    return out


def make_fixed_accessory(preset_id: int, inst_id: int, now: str = "") -> Optional[Dict[str, Any]]:
    """Build an AccessoryModel dict from FixedAccessoryPresets.xml."""
    p = _presets().get(int(preset_id))
    if p is None:
        return None
    rolls = [(s.get("Key"), float(s.get("Value"))) for s in p.findall("./SubStats/SubStat")]
    fb = p.find("FixedBonusSubStat")
    if fb is not None:
        rolls.append((fb.get("Key"), float(fb.get("Value"))))
    scores: Dict[str, float] = {}
    for k, v in rolls:
        if k:
            unit = VALUE_PER_SCORE.get(k, 1.0)
            scores[k] = scores.get(k, 0.0) + (v / unit)
    return {
        "id": inst_id,
        "accountId": 1,
        "unitId": 0,
        "slot": 0,
        "type": int(p.findtext("Type", "1")),
        "rarity": int(p.findtext("Rarity", "3")),
        "level": int(p.findtext("Level", "20")),
        "exp": 0,
        "synergy": int(p.findtext("Synergy", "0")),
        "state": 0,
        "data": {
            "mainStat": p.findtext("MainStat", "AtkPer"),
            "subStats": [{"key": k, "value": v} for k, v in rolls if k],
        },
        "subStats": list(scores.keys()),
        "subStatScores": [round(s, 3) for s in scores.values()],
        "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
        "createdAt": now or now_iso(0),
        "updatedAt": now or now_iso(0),
        "usedThemeList": [],
        "isEarlyAccessModeTestAccessory": False,
    }


def load_default_corruption_accessories() -> List[Dict[str, Any]]:
    """Load default set of corruption accessories (presets 2000-2003)."""
    out = []
    inst = 1
    now = now_iso(0)
    for pid in [2000, 2001, 2002, 2003]:
        acc = make_fixed_accessory(pid, inst, now)
        if acc:
            out.append(acc)
            inst += 1
    return out


def recompute_accessory_substats(acc: Dict[str, Any]):
    """Recomputes parallel subStats and subStatScores lists from data.subStats."""
    data = acc.setdefault("data", {})
    sub_stats = data.setdefault("subStats", [])
    scores: Dict[str, float] = {}
    for entry in sub_stats:
        k = entry.get("key")
        v = float(entry.get("value", 0.0))
        if k:
            unit = VALUE_PER_SCORE.get(k, 1.0)
            scores[k] = scores.get(k, 0.0) + (v / unit)
    acc["subStats"] = list(scores.keys())
    acc["subStatScores"] = [round(s, 3) for s in scores.values()]


def ensure_accessory_state(st: Dict[str, Any]) -> bool:
    """Ensure st['accessories'] and st['accessoryPresets'] exist and are healthy."""
    changed = False
    if "accessories" not in st or not isinstance(st["accessories"], list) or len(st["accessories"]) == 0:
        st["accessories"] = load_default_corruption_accessories()
        changed = True
    else:
        # Sanitize each accessory model
        for a in st["accessories"]:
            if not isinstance(a, dict):
                continue
            if "data" not in a or not isinstance(a["data"], dict):
                a["data"] = {"mainStat": "AtkPer", "subStats": []}
                changed = True
            if "subStats" not in a or "subStatScores" not in a:
                recompute_accessory_substats(a)
                changed = True

    # Ensure presets (10 presets)
    presets = st.setdefault("accessoryPresets", [])
    if not isinstance(presets, list) or len(presets) < 10:
        existing = {p.get("id"): p for p in presets if isinstance(p, dict) and "id" in p}
        st["accessoryPresets"] = [
            existing.get(i, {"id": i, "slotName": f"Preset {i+1}", "accessories": []})
            for i in range(10)
        ]
        changed = True

    return changed


def _get_inventory_item_count(st: Dict[str, Any], item_id: int) -> int:
    inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
    ids = inv.setdefault("itemIds", [])
    cnts = inv.setdefault("counts", [])
    if item_id in ids:
        return cnts[ids.index(item_id)]
    return 0


def _deduct_inventory_item(st: Dict[str, Any], item_id: int, count: int) -> bool:
    inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
    ids = inv.setdefault("itemIds", [])
    cnts = inv.setdefault("counts", [])
    if item_id in ids:
        idx = ids.index(item_id)
        if cnts[idx] >= count:
            cnts[idx] -= count
            return True
    return False


def _add_inventory_item(st: Dict[str, Any], item_id: int, count: int):
    inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
    ids = inv.setdefault("itemIds", [])
    cnts = inv.setdefault("counts", [])
    if item_id in ids:
        cnts[ids.index(item_id)] += count
    else:
        ids.append(item_id)
        cnts.append(count)


def _build_inventory_list(st: Dict[str, Any]) -> List[Dict[str, int]]:
    inv = st.get("inventory", {})
    ids = inv.get("itemIds", [])
    cnts = inv.get("counts", [])
    return [{"id": i, "count": c} for i, c in zip(ids, cnts)]


def _make_result_response(st: Dict[str, Any], deleted_ids: Optional[List[int]] = None, added_exp: int = 0) -> Dict[str, Any]:
    return {
        "accessories": st.get("accessories", []),
        "deletedAccessories": deleted_ids or [],
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "inventories": _build_inventory_list(st),
        "addedExpItems": added_exp,
    }


# =========================================================================
# Route Handlers
# =========================================================================

def r_accessory_inventory(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """GET /accessory -> AccessoryInventoryResponseModel."""
    ensure_accessory_state(st)
    return {"accessories": st.get("accessories", [])}


def r_accessory_equip(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """POST /accessory/equip (and POST /accessory)."""
    ensure_accessory_state(st)
    accs = st.get("accessories", [])
    unit_id = int(body.get("unitId", 0))
    target_ids = body.get("targetIds")
    if target_ids is None and "targetId" in body:
        tid = body.get("targetId")
        target_ids = [tid] if tid else []
    target_ids = [int(i) for i in target_ids] if target_ids else []

    if unit_id and target_ids:
        # Find target accessory objects to equip
        target_accs = [a for a in accs if a.get("id") in target_ids]
        target_types = {a.get("type") for a in target_accs}

        is_padded = len(target_ids) >= 5 or 0 in target_ids

        # 1. Un-equip any accessory currently on this hero that should be removed
        for a in accs:
            if a.get("unitId") == unit_id and a.get("id") not in target_ids:
                # If padded (full state), unequip everything not in target_ids
                # If not padded (partial state), only unequip items of the same type being equipped
                if is_padded or a.get("type") in target_types:
                    a["unitId"] = 0
                    a["updatedAt"] = now_iso(0)

        # 2. Equip target accessories onto unit_id
        for a in target_accs:
            a["unitId"] = unit_id
            if is_padded and a.get("id") in target_ids:
                a["slot"] = target_ids.index(a.get("id"))
            else:
                a["slot"] = int(a.get("type", 1))
            a["updatedAt"] = now_iso(0)

        save_state(st)

    return _make_result_response(st)


def r_accessory_release(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """POST /accessory/release-equip."""
    ensure_accessory_state(st)
    accs = st.get("accessories", [])
    target_id = int(body.get("targetId", 0))
    target_ids = body.get("targetIds")
    if target_ids is None and target_id:
        target_ids = [target_id]
    target_ids = [int(i) for i in target_ids] if target_ids else []

    if target_ids:
        for a in accs:
            if a.get("id") in target_ids:
                a["unitId"] = 0
                a["updatedAt"] = now_iso(0)
        save_state(st)

    return _make_result_response(st)


def r_accessory_equip_tutorial(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """POST /accessory/equip-tutorial."""
    return r_accessory_equip(body, st)


def _roll_milestone_event(acc: Dict[str, Any], lvl: int, consts: Dict[str, Any], rng=random):
    """Applies sub-stat unlock or upgrade for a milestone level."""
    events_map = consts.get("level_events", {}).get("Special", {})
    ev_list = events_map.get(lvl, [])
    if not ev_list:
        return

    main_stat = acc.get("data", {}).get("mainStat", "AtkPer")
    all_valid_substats = consts.get("main_stat_info", {}).get(main_stat, {}).get("subStats", [])
    current_substat_keys = acc.get("subStats", [])

    for ev in ev_list:
        ev_type = ev.get("type", "UpgradeSlot")
        probs = ev.get("probs", [(2.5, 10)])
        weights = [p[1] for p in probs]
        scores = [p[0] for p in probs]
        chosen_score = rng.choices(scores, weights=weights, k=1)[0] if scores else 2.5

        if ev_type == "UnlockSlot" or len(current_substat_keys) < 4:
            # Unlock a new sub-stat slot from unused valid pool
            unused = [k for k in all_valid_substats if k not in current_substat_keys]
            if not unused:
                unused = all_valid_substats or ["AtkPer"]
            new_key = rng.choice(unused)
            val = round(chosen_score * VALUE_PER_SCORE.get(new_key, 1.0), 3)
            acc["data"]["subStats"].append({"key": new_key, "value": val})
            recompute_accessory_substats(acc)
            current_substat_keys = acc.get("subStats", [])
        else:
            # Upgrade an existing sub-stat
            target_key = rng.choice(current_substat_keys) if current_substat_keys else "AtkPer"
            val = round(chosen_score * VALUE_PER_SCORE.get(target_key, 1.0), 3)
            acc["data"]["subStats"].append({"key": target_key, "value": val})
            recompute_accessory_substats(acc)


def r_accessory_add_exp(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """POST /accessory/add-exp.

    Consumes exp items (4000/4100/4101/4102), deducts gold per level up,
    levels up the accessory, and triggers sub-stat upgrade milestone events.
    """
    ensure_accessory_state(st)
    consts = _load_constants()
    level_costs = consts.get("level_costs", {})
    accs = st.get("accessories", [])

    target_id = int(body.get("targetId", 0))
    acc = next((a for a in accs if a.get("id") == target_id), None)
    if not acc:
        return _make_result_response(st)

    exp_items = body.get("expItems", [])
    if not isinstance(exp_items, list):
        exp_items = []

    # Calculate total exp from materials and consume from inventory
    total_exp_added = 0
    for it in exp_items:
        iid = int(it.get("id", 0))
        cnt = int(it.get("count", 0))
        if cnt <= 0:
            continue
        unit_exp = EXP_ITEM_VALUES.get(iid, 0)
        if unit_exp > 0 and _deduct_inventory_item(st, iid, cnt):
            total_exp_added += unit_exp * cnt

    # If no exp items from inventory but direct call (or test), handle safely
    if total_exp_added == 0 and exp_items:
        for it in exp_items:
            iid = int(it.get("id", 0))
            cnt = int(it.get("count", 0))
            total_exp_added += EXP_ITEM_VALUES.get(iid, 100) * max(1, cnt)

    cur_level = int(acc.get("level", 1))
    cur_exp = int(acc.get("exp", 0)) + total_exp_added

    # Process Level-Ups
    while cur_level < 20:
        next_cost = level_costs.get(cur_level + 1, {"needExp": 999999, "needGold": 0})
        need_exp = next_cost.get("needExp", 999999)
        need_gold = next_cost.get("needGold", 0)

        if cur_exp >= need_exp:
            player_gold = st.get("gold", 0)
            if player_gold < need_gold:
                break
            st["gold"] = player_gold - need_gold
            cur_exp -= need_exp
            cur_level += 1
            acc["level"] = cur_level

            # Check milestone event for cur_level (levels 4, 8, 12, 16, 20)
            if cur_level in [4, 8, 12, 16, 20]:
                _roll_milestone_event(acc, cur_level, consts)
        else:
            break

    if cur_level >= 20:
        cur_level = 20
        cur_exp = 0

    acc["level"] = cur_level
    acc["exp"] = cur_exp
    acc["updatedAt"] = now_iso(0)
    save_state(st)

    return _make_result_response(st, added_exp=total_exp_added)


def r_accessory_dismantle(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """POST /accessory/dismantle.

    Dismantles unlocked & unequipped accessories, grants shards/stones from
    AccessoryDismantleInfo, and removes accessories from state.
    """
    ensure_accessory_state(st)
    consts = _load_constants()
    dismantle_info = consts.get("dismantle_info", {})
    accs = st.get("accessories", [])

    raw_ids = body.get("accessoryIds", [])
    if not isinstance(raw_ids, list):
        raw_ids = []
    target_ids = [int(i) for i in raw_ids]

    deleted_ids = []
    granted_rewards: Dict[int, int] = {}

    for aid in target_ids:
        acc = next((a for a in accs if a.get("id") == aid), None)
        if not acc:
            continue
        # Locked accessories (state & 1 != 0) cannot be dismantled
        if acc.get("state", 0) & 1:
            continue
        # Equipped accessories (unitId != 0) cannot be dismantled
        if acc.get("unitId", 0) != 0:
            continue

        lvl = int(acc.get("level", 1))
        rewards = dismantle_info.get(lvl, [{"id": 4000, "count": 1}])
        for r in rewards:
            rid = r.get("id", 4000)
            rcnt = r.get("count", 1)
            granted_rewards[rid] = granted_rewards.get(rid, 0) + rcnt

        deleted_ids.append(aid)

    # Apply granted rewards to inventory
    for rid, rcnt in granted_rewards.items():
        _add_inventory_item(st, rid, rcnt)

    # Remove deleted accessories from save
    if deleted_ids:
        st["accessories"] = [a for a in accs if a.get("id") not in deleted_ids]
        save_state(st)

    return _make_result_response(st, deleted_ids=deleted_ids)


def r_accessory_set_state(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """POST /accessory/set-state and POST /accessory/set-state-all.

    Toggles lock / favorite state (0 = unlocked, 1 = locked).
    """
    ensure_accessory_state(st)
    accs = st.get("accessories", [])
    target_ids = body.get("targetIds")
    if target_ids is None and "targetId" in body:
        tid = body.get("targetId")
        target_ids = [tid] if tid else []
    target_ids = [int(i) for i in target_ids] if target_ids else []
    new_state = int(body.get("state", 0))

    if target_ids:
        for a in accs:
            if a.get("id") in target_ids:
                a["state"] = new_state
                a["updatedAt"] = now_iso(0)
        save_state(st)

    return _make_result_response(st)


def r_accessory_change_sub_stat(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """POST /accessory/change-sub-stat.

    Rerolls a target sub-stat using conversion stone (item 4200),
    preserving the current sub-stat score and calculating new value.
    """
    with open("/tmp/change_stat_body.json", "w") as f:
        import json
        json.dump(body, f)

    ensure_accessory_state(st)
    consts = _load_constants()
    accs = st.get("accessories", [])

    aid = int(body.get("accessoryId", 0))
    target_stat = body.get("targetSubStat", "")
    item_id = int(body.get("itemId", REROLL_STONE_ITEM_ID))

    acc = next((a for a in accs if a.get("id") == aid), None)
    if not acc or not target_stat:
        return _make_result_response(st)

    # Deduct conversion stone if available
    _deduct_inventory_item(st, item_id, 1)

    main_stat = acc.get("data", {}).get("mainStat", "AtkPer")
    valid_pool = consts.get("main_stat_info", {}).get(main_stat, {}).get("subStats", [])
    current_substats = acc.get("subStats", [])

    # Available new stats (exclude currently existing sub-stats)
    available_new = [k for k in valid_pool if k not in current_substats and k != target_stat]
    if not available_new:
        available_new = [k for k in valid_pool if k != target_stat]
    if not available_new:
        available_new = ["BaseSpecialDamageMul", "BaseDefPen", "BaseDefDen"]

    new_stat = None
    if item_id != REROLL_STONE_ITEM_ID:
        xml_path = XML_DIR / "InventoryItems.xml"
        if xml_path.exists():
            tree = ET.parse(xml_path)
            for item in tree.findall("InventoryItem"):
                if item.get("ID") == str(item_id):
                    substat_elem = item.find("SetAccessorySubStat")
                    if substat_elem is not None:
                        new_stat = substat_elem.text
                    break

    if not new_stat:
        new_stat = random.choice(available_new)

    # Find total score allocated to target_stat
    data = acc.setdefault("data", {})
    sub_list = data.setdefault("subStats", [])
    old_score = 0.0
    for entry in sub_list:
        if entry.get("key") == target_stat:
            v = float(entry.get("value", 0.0))
            old_score += v / VALUE_PER_SCORE.get(target_stat, 1.0)

    if old_score <= 0.0:
        old_score = 4.0

    # Replace entry of target_stat with new_stat in place
    for entry in sub_list:
        if entry.get("key") == target_stat:
            entry["key"] = new_stat
            entry["value"] = round(old_score * VALUE_PER_SCORE.get(new_stat, 1.0), 3)
            break


    recompute_accessory_substats(acc)
    acc["updatedAt"] = now_iso(0)
    save_state(st)

    return _make_result_response(st)


def r_accessory_preset_list(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """GET /accessory/preset -> AccessoryPresetResponseModel."""
    ensure_accessory_state(st)
    return {"presets": st.get("accessoryPresets", [])}


def r_accessory_set_preset(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """POST /accessory/set-preset and POST /accessory/preset."""
    ensure_accessory_state(st)
    presets = st.get("accessoryPresets", [])
    preset_id = int(body.get("presetId", 0))
    raw_targets = body.get("targetIds", [])
    target_ids = [int(i) for i in raw_targets] if isinstance(raw_targets, list) else []

    target_preset = next((p for p in presets if p.get("id") == preset_id), None)
    if target_preset:
        target_preset["accessories"] = target_ids
        save_state(st)

    return {"presets": presets}


def r_accessory_set_preset_name(body: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """POST /accessory/set-preset-name."""
    ensure_accessory_state(st)
    presets = st.get("accessoryPresets", [])
    preset_id = int(body.get("presetId", 0))
    preset_name = str(body.get("presetName", "")).strip()

    if preset_name:
        target_preset = next((p for p in presets if p.get("id") == preset_id), None)
        if target_preset:
            target_preset["slotName"] = preset_name
            save_state(st)

    return {"presets": presets}
