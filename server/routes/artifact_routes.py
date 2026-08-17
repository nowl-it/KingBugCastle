"""Artifact, treasure, accessory, and rift-item routes.

Owns the whole item-instance domain: the instance templates (make_*), the default
inventories the client expects on a fresh save, and the equip/dismantle/result
handlers. The accessory paths route directly to the accessory leaf module from
server.py's OVERRIDES, so this module only keeps the server-side defaults.

bump / _inventory_models / _grant_reward stay in server.py (or rewards) and are
reached through srv.
"""
import copy

from common import admin_log, body_int, now_iso
from config import ITEM_TEMPLATES, XML_DIR
from state import save_state
import accessory
import rift

srv = None      # live server module, injected via register()


DEFAULTS_BUILT = False


def _ensure_defaults():
    """Build the default inventories once srv is live (module import runs before
    register, so the ALL_* id lists are not available yet)."""
    global DEFAULTS_BUILT, RIFT_BUILDING_COUNT, DEFAULT_ARTIFACTS, DEFAULT_TREASURES
    global DEFAULT_ACCESSORIES, DEFAULT_RIFT_WEAPONS, ARTIFACT_BY_ID
    if DEFAULTS_BUILT:
        return
    RIFT_BUILDING_COUNT = srv._rift_building_count()
    DEFAULT_ARTIFACTS = [make_artifact(i + 1, aid) for i, aid in enumerate(srv.ALL_ARTIFACT_IDS)]
    DEFAULT_TREASURES = [make_treasure(i + 1, tid) for i, tid in enumerate(srv.ALL_TREASURE_IDS)]
    DEFAULT_ACCESSORIES = load_corruption_accessories() or [make_accessory(i + 1) for i in range(ITEM_TEMPLATES["accessory"]["count"])]
    DEFAULT_RIFT_WEAPONS = [make_rift_weapon(i + 1, rwid) for i, rwid in enumerate(srv.ALL_RIFT_WEAPON_IDS)]
    ARTIFACT_BY_ID = {a["id"]: a for a in DEFAULT_ARTIFACTS}
    for _n in ("RIFT_BUILDING_COUNT", "DEFAULT_ARTIFACTS", "DEFAULT_TREASURES",
               "DEFAULT_ACCESSORIES", "DEFAULT_RIFT_WEAPONS", "ARTIFACT_BY_ID"):
        setattr(srv, _n, globals()[_n])
    DEFAULTS_BUILT = True


def register(app, server_module):
    global srv
    srv = server_module
    _ensure_defaults()
    srv.ARTIFACT_OVERRIDES = handlers()


def handlers():
    return {
        "/artifact/reroll": r_artifact_result,
        "/artifact/polish/replace-option-slot-idx": r_artifact_result,
        "/artifact/inventory": r_artifact_inventory,
        "/artifact/equip": r_artifact_equip,
        "/artifact/crafting": r_artifact_result,
        "/artifact/dismantle": r_artifact_dismantle,
        "/artifact/merge": r_artifact_result,
        "/artifact/polish": r_artifact_result,
        "/artifact/gacha": r_artifact_result,
        "/artifact/set-reroll": r_artifact_result,
        "/artifact/smart-reroll": r_artifact_result,
        "/artifact/fetch-reroll": r_artifact_result,
        "/artifact/open-catalyst-box": r_artifact_result,
        "/artifact/set-favorites": r_artifact_result,
        "/treasure": r_treasure,
        "/treasure/equip": r_treasure_equip,
        "/treasure/add-exp": r_treasure_add_exp,
        "/treasure/dismantle": r_treasure_dismantle,
        "/treasure/equip-tutorial": r_treasure_equip,
        "/treasure/overcome": r_treasure_overcome,
        "/treasure/release-equip": r_treasure_release,
        "/treasure/set-state": r_treasure_set_state,
    }


# Ghidra ROOT CAUSE (2026-07-02, ResourceArtifactOption.GetValue crash):
# ArtifactOptionUI.Init's loop gate is `uVar8 < targets.Count` (top-level
# ArtifactOptions.targets, NOT types/lvs). Only when the gate is open does it call
# GetValue(types[i], lvs[i], ...) which does a Dictionary["AtkSpeedPer"] style
# lookup - "None" is never a registered key, so ANY slot reached with type="None"
# throws KeyNotFoundException. Fix: targets.Count must equal opt_count exactly, so
# the loop's else/hide branch (which never touches types/lvs) handles slots
# opt_count..3 instead of trying to look up "None". types_list/lvs_list stay
# padded to optionSlots (loop only ever reads indices < opt_count from them, so
# the tail values are never touched, but keep them present per the JSON schema).
#
# positionIcons (icon highlighting) separately requires: idx values 1-based
# (FUN_02e91408 = List<int>.IndexOf), and BOTH idx (nested struct list) and lvs
# (parallel list) must stay UNIFORM in length/value across all sent slots or the
# client's JSON parser corrupts subsequent fields (live-verified both ways).
# idx > 1 element still crashes for unknown reasons - capped at safePositions.
def make_artifact(i, art_id):
    t = ITEM_TEMPLATES["artifact"]
    level = srv.ARTIFACT_LEVELS.get(art_id, "Normal")
    opt_count = t["optCountByLevel"].get(level, 1)
    types_pool = t["typesPool"]
    max_roll_lvs = t["maxRollLvs"]
    safe_positions = t["safePositions"]

    opt_data = []
    types_list = []
    lvs_list = []
    targets_list = []
    locks = []

    for idx in range(opt_count):
        ty = types_pool[idx % len(types_pool)]
        opt_data.append({"targets": safe_positions, "type": ty, "value": 4 * max_roll_lvs, "level": max_roll_lvs})
        types_list.append(ty)
        targets_list.append({"idx": safe_positions})
        lvs_list.append(max_roll_lvs)
        locks.append(False)

    for idx in range(opt_count, 4):
        opt_data.append({"targets": safe_positions, "type": "None", "value": 0, "level": 0})
        types_list.append("None")
        lvs_list.append(0)
        locks.append(False)

    return {
        "id": i,
        "artifactId": art_id,
        "count": t["count"],
        "polishPoint": t["polishPoint"],
        "data": {"options": opt_data},
        "options": {
            "targets": targets_list,
            "types": types_list,
            "lvs": lvs_list
        },
        "optionLock": locks,
        "customType": t["customType"],
        "createdAt": now_iso()
    }


def make_accessory(i, unit_id=0):
    t = ITEM_TEMPLATES["accessory"]
    return {
        "id": i, "accountId": t["accountId"], "unitId": unit_id, "slot": t["slot"],
        "type": (i % t["typeCount"]) + 1,
        "rarity": t["rarity"], "level": t["level"], "exp": t["exp"], "synergy": t["synergy"], "state": t["state"],
        "data": t["data"], "subStats": t["subStats"], "subStatScores": t["subStatScores"],
        "coolTimeEndAt": t["coolTimeEndAt"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
        "usedThemeList": t["usedThemeList"],
        "isEarlyAccessModeTestAccessory": t["isEarlyAccessModeTestAccessory"],
    }


def _acc_perscore(key):
    # AccessoryConstants.xml: BaseDef/BaseMDef roll in ValuePerScore=20 units; every other
    # substat uses ValueByScore=1. score = summed value / perScore.
    return 20.0 if key in ("BaseDef", "BaseMDef") else 1.0


def load_corruption_accessories():
    """Real 'Corruption II-1' first-clear reward accessories (FixedAccessoryPreset 2000-2003,
    one per type) - the exact items the client grants for clearing the stage that unlocks the
    accessory system. Mirrors AccessoryModel (data.mainStat + data.subStats[{key,value}]) so
    the client renders proper name/stats/grade instead of the 99.9% garbage a fabricated
    template with an invalid mainStat produced."""
    import xml.etree.ElementTree as ET
    root = ET.parse(XML_DIR / "FixedAccessoryPresets.xml").getroot()
    out, inst = [], 1
    for p in root.findall("FixedAccessoryPreset"):
        if p.get("ID", "") not in ("2000", "2001", "2002", "2003"):
            continue
        rolls = [(s.get("Key"), float(s.get("Value"))) for s in p.findall("./SubStats/SubStat")]
        fb = p.find("FixedBonusSubStat")
        if fb is not None:
            rolls.append((fb.get("Key"), float(fb.get("Value"))))
        scores = {}
        for k, v in rolls:
            scores[k] = scores.get(k, 0.0) + v / _acc_perscore(k)
        out.append({
            "id": inst, "accountId": 1, "unitId": 0, "slot": 0,
            "type": int(p.findtext("Type", "1")), "rarity": int(p.findtext("Rarity", "3")),
            "level": int(p.findtext("Level", "20")), "exp": 0,
            "synergy": int(p.findtext("Synergy", "0")), "state": 0,
            "data": {"mainStat": p.findtext("MainStat", "AtkPer"),
                     "subStats": [{"key": k, "value": v} for k, v in rolls]},
            "subStats": list(scores.keys()), "subStatScores": [round(s, 3) for s in scores.values()],
            "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
            "createdAt": now_iso(), "updatedAt": now_iso(),
            "usedThemeList": [], "isEarlyAccessModeTestAccessory": False,
        })
        inst += 1
    return out


def get_st_accessories(st):
    accessory.ensure_accessory_state(st)
    return st.get("accessories", [])


def r_accessory(body, st):
    return accessory.r_accessory_equip(body, st)


def r_accessory_release(body, st):
    return accessory.r_accessory_release(body, st)


def r_accessory_result(body, st):
    return accessory._make_result_response(st)


def make_treasure(i, tr_id):
    t = ITEM_TEMPLATES["treasure"]
    return {
        "id": i, "treasureId": tr_id, "accountId": t["accountId"],
        "level": t["level"], "exp": t["exp"], "overcome": t["overcome"], "unitId": t["unitId"], "state": t["state"],
        "coolTimeEndAt": t["coolTimeEndAt"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
        "usedThemeList": t["usedThemeList"],
        "isEarlyAccessModeTestTreasure": t["isEarlyAccessModeTestTreasure"],
    }


def make_rift_weapon(i, rw_id):
    t = ITEM_TEMPLATES["riftWeapon"]
    return {
        "id": i, "weaponId": rw_id, "buildingIndexes": t["buildingIndexes"],
        "level": t["level"], "rarity": t["rarity"], "broken": t["broken"],
        "subStat": t["subStat"], "state": t["state"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
    }


RIFT_BUILDING_COUNT = 6   # real value from srv._rift_building_count() at register
# CrystalRarity (ResourceRiftWeaponConstant.CrystalRarity): None=0, Common=1, UnCommon=2,
# Rare=3, Epic=4, Legendary=5. Rarity 0 names the crystal via the key
# `RiftCrystalNameKeyword_None`, which does not exist in any locale - the client then
# renders the raw key. Only 1-5 have a keyword (Faded/Ordinary/King/God/King God).
RIFT_CRYSTAL_RARITIES = {1: "Common", 2: "UnCommon", 3: "Rare", 4: "Epic", 5: "Legendary"}
# Altars cap at level 15 ("You have an Altar with more than 15 points" / the 16 entries
# of RiftWeaponConstants.xml BuildingOptionSlotLevelValue = levels 0..15).
RIFT_BUILDING_MAX_LEVEL = 15


def make_rift_crystal(i, rw_id, main_idx=None):
    t = ITEM_TEMPLATES["riftCrystal"]
    main_idx = t["mainBuildingIdx"] if main_idx is None else main_idx
    main_idx %= max(RIFT_BUILDING_COUNT, 1)
    level = min(int(t["mainBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL)
    other = min(int(t["otherBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL)
    # One level per altar, with the main altar strictly highest: GetMaxBuildingIdx
    # returns the FIRST maximum, so an all-equal list would name every crystal after
    # altar 0 regardless of mainBuildingIdx.
    levels = [other] * RIFT_BUILDING_COUNT
    levels[main_idx] = max(level, other + 1)
    rarity = int(t["rarity"])
    assert rarity in RIFT_CRYSTAL_RARITIES, (
        f"riftCrystal rarity {rarity} has no RiftCrystalNameKeyword_* string; "
        f"valid: {sorted(RIFT_CRYSTAL_RARITIES)}")
    return {
        "id": i, "weaponId": rw_id, "mainBuildingIdx": main_idx,
        "buildingLevels": levels, "rarity": rarity,
        "ceilCount": t["ceilCount"], "state": t["state"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
    }


def _repair_rift_crystals(crystals):
    """Upgrade crystals saved before the shape was understood. Returns True if anything
    changed, so the caller can persist.

    Two legacy defects, both of which the client renders rather than rejects:
      * rarity 0 (CrystalRarity.None) -> the name resolves `RiftCrystalNameKeyword_None`,
        a key that exists in no locale, so the panel shows the raw key;
      * buildingLevels shorter than the altar count -> GetMaxBuildingIdx can only ever
        return an index inside the short list, so every crystal named itself after
        altar 0 and the altars past the end contributed nothing.
    """
    t = ITEM_TEMPLATES["riftCrystal"]
    changed = False
    for c in crystals:
        if c.get("rarity") not in RIFT_CRYSTAL_RARITIES:
            c["rarity"] = int(t["rarity"])
            changed = True
        levels = c.get("buildingLevels") or []
        if len(levels) != RIFT_BUILDING_COUNT:
            main = int(c.get("mainBuildingIdx", 0)) % max(RIFT_BUILDING_COUNT, 1)
            other = min(int(t["otherBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL)
            # Keep whatever levels the save already had; only extend to full width.
            fixed = [min(int(v), RIFT_BUILDING_MAX_LEVEL) for v in levels[:RIFT_BUILDING_COUNT]]
            fixed += [other] * (RIFT_BUILDING_COUNT - len(fixed))
            fixed[main] = max(min(int(t["mainBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL), other + 1)
            c["buildingLevels"] = fixed
            c["mainBuildingIdx"] = main
            changed = True
    return changed


# ArtifactRequestModel.targetId = the equipped artifact's instance `id` (dump.cs
# ArtifactRequestModel @0x8 targetId, @0x1C index, @0x20 deckPreset).
# ArtifactResultResponseModel.equippedArtifacts = List<EquippedArtifactData>
# {deckPreset, index, artifact} (dump.cs @0x2C). Persisted server-side as
def get_st_artifacts(st):
    _ensure_defaults()
    if "artifacts" not in st:
        st["artifacts"] = copy.deepcopy(DEFAULT_ARTIFACTS)
    return st["artifacts"]


def _resolve_equipped_artifacts(st):
    out = []
    arts = get_st_artifacts(st)
    art_map = {a.get("id"): a for a in arts}
    art_by_aid = {a.get("artifactId"): a for a in arts}
    for e in st.get("equippedArtifacts", []):
        art_id = e.get("artifactId")
        art = art_map.get(art_id) or art_by_aid.get(art_id)
        if art:
            out.append({"deckPreset": e.get("deckPreset", 0), "index": e.get("index", 0), "artifact": art})
    return out


def r_artifact_inventory(body, st):
    return {"artifacts": get_st_artifacts(st), "dustCount": st.get("dustCount", 99999),
            "equippedArtifacts": _resolve_equipped_artifacts(st), "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0)}


def r_artifact_equip(body, st):
    target_id = body_int(body.get("targetId"), 0)
    index = body_int(body.get("index"), 0)
    deck_preset = body_int(body.get("deckPreset"), 0)
    equipped = [e for e in st.get("equippedArtifacts", [])
                if not (e.get("deckPreset", 0) == deck_preset and e.get("index", 0) == index)]
    arts = get_st_artifacts(st)
    art = next((a for a in arts if a.get("id") == target_id or a.get("artifactId") == target_id), None)
    if art:
        equipped.append({"deckPreset": deck_preset, "index": index, "artifactId": art.get("id")})
    st["equippedArtifacts"] = equipped
    save_state(st)
    return {"artifacts": arts, "dustCount": st.get("dustCount", 99999),
            "equippedArtifacts": _resolve_equipped_artifacts(st), "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "changeEquipped": True, "polishItemAdded": False,
            "results": []}


def r_artifact_dismantle(body, st):
    admin_log(f"[artifact-dismantle] body={body}")
    arts = get_st_artifacts(st)
    raw_targets = (
        body.get("targets") or
        body.get("targetIds") or
        body.get("artifactIds") or
        body.get("artifacts") or
        []
    )
    if not isinstance(raw_targets, list):
        raw_targets = [raw_targets]
    if body.get("targetId"):
        raw_targets.append(body.get("targetId"))
    if body.get("id"):
        raw_targets.append(body.get("id"))
    if body.get("artifactId"):
        raw_targets.append(body.get("artifactId"))

    target_ids = set()
    target_counts = {}
    for item in raw_targets:
        if isinstance(item, dict):
            t_id = item.get("id") or item.get("targetId") or item.get("artifactId")
            if t_id is not None:
                target_ids.add(t_id)
                target_ids.add(str(t_id))
                if str(t_id).isdigit():
                    target_ids.add(int(t_id))
                target_counts[t_id] = item.get("count", 1)
                target_counts[str(t_id)] = item.get("count", 1)
                if str(t_id).isdigit():
                    target_counts[int(t_id)] = item.get("count", 1)
        elif item is not None:
            target_ids.add(item)
            target_ids.add(str(item))
            if str(item).isdigit():
                target_ids.add(int(item))
            target_counts[item] = 1
            target_counts[str(item)] = 1
            if str(item).isdigit():
                target_counts[int(item)] = 1

    dust_gain = 0
    dust_table = {"Normal": 70, "King": 230, "God": 650, "KingGod": 2000}
    remaining_arts = []
    dismantled_instance_ids = set()

    for a in arts:
        aid = a.get("id")
        art_id = a.get("artifactId")
        match_id = None
        for cand in (aid, str(aid), art_id, str(art_id)):
            if cand in target_ids:
                match_id = cand
                break

        if match_id is not None:
            cnt_to_remove = target_counts.get(match_id, a.get("count", 1))
            current_cnt = a.get("count", 1)
            lvl = srv.ARTIFACT_LEVELS.get(art_id, "Normal")
            dust_per = dust_table.get(lvl, 70)

            if cnt_to_remove >= current_cnt:
                dust_gain += dust_per * current_cnt
                if aid is not None:
                    dismantled_instance_ids.add(aid)
                if art_id is not None:
                    dismantled_instance_ids.add(art_id)
            else:
                a["count"] = current_cnt - cnt_to_remove
                dust_gain += dust_per * cnt_to_remove
                remaining_arts.append(a)
        else:
            remaining_arts.append(a)

    st["artifacts"] = remaining_arts
    st["dustCount"] = st.get("dustCount", 0) + dust_gain

    if dismantled_instance_ids:
        st["equippedArtifacts"] = [e for e in st.get("equippedArtifacts", []) if e.get("artifactId") not in dismantled_instance_ids]

    save_state(st)
    srv.bump(st, "artifactDismantle", len(target_ids) or 1)

    return {
        "artifacts": remaining_arts,
        "dustCount": st.get("dustCount", 99999),
        "equippedArtifacts": _resolve_equipped_artifacts(st),
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "changeEquipped": True,
        "polishItemAdded": False,
        "results": []
    }


def r_artifact_result(body, st):
    arts = get_st_artifacts(st)
    return {"artifacts": arts, "dustCount": st.get("dustCount", 99999),
            "equippedArtifacts": _resolve_equipped_artifacts(st), "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "changeEquipped": False, "polishItemAdded": False,
            "results": []}


def get_st_treasures(st):
    _ensure_defaults()
    if "treasures" not in st:
        st["treasures"] = copy.deepcopy(DEFAULT_TREASURES)
    return st["treasures"]


def r_treasure(body, st):
    tr = get_st_treasures(st)
    target_id = body.get("targetId", 0)
    unit_id = body.get("unitId", 0)
    if target_id and unit_id:
        for t in tr:
            if t["unitId"] == unit_id:
                t["unitId"] = 0
            if t["id"] == target_id:
                t["unitId"] = unit_id
        save_state(st)
    return {"treasures": tr, "treasureCapacity": 9999, "capacity": 9999, "maxCapacity": 9999, "maxTreasureCount": 9999, "deletedTreasures": [], "inventories": srv._inventory_models(st)}


def r_treasure_equip(body, st):
    return r_treasure(body, st)


def r_treasure_release(body, st):
    tr = get_st_treasures(st)
    inv_id = body.get("targetId")
    for t in tr:
        if t["id"] == inv_id:
            t["unitId"] = 0
    save_state(st)
    return r_treasure(body, st)


def r_treasure_dismantle(body, st):
    admin_log(f"[treasure-dismantle] body={body}")
    tr = get_st_treasures(st)
    raw_targets = (
        body.get("treasureIds") or
        body.get("targets") or
        body.get("targetIds") or
        body.get("dismantleTreasureIds") or
        []
    )
    if not isinstance(raw_targets, list):
        raw_targets = [raw_targets]
    if body.get("targetId"):
        raw_targets.append(body.get("targetId"))
    if body.get("id"):
        raw_targets.append(body.get("id"))
    if body.get("treasureId"):
        raw_targets.append(body.get("treasureId"))

    target_ids = set()
    for item in raw_targets:
        if isinstance(item, dict):
            for k in ("id", "targetId", "treasureId", "itemId"):
                if item.get(k) is not None:
                    target_ids.add(item[k])
                    target_ids.add(str(item[k]))
                    if str(item[k]).isdigit():
                        target_ids.add(int(item[k]))
        elif item is not None:
            target_ids.add(item)
            target_ids.add(str(item))
            if str(item).isdigit():
                target_ids.add(int(item))

    remaining_treasures = []
    deleted_ids = []

    for t in tr:
        t_id = t.get("id")
        tr_id = t.get("treasureId")

        matched_id = None
        for cand in (t_id, tr_id):
            if cand is not None and (cand in target_ids or str(cand) in target_ids):
                matched_id = cand
                break

        if matched_id is not None:
            deleted_ids.append(matched_id)

            overcome = t.get("overcome", 0)
            srv._grant_reward(st, "Item", 3000, 10 * (overcome + 1))
            srv._grant_reward(st, "Item", 3100, 5 * (overcome + 1))
        else:
            remaining_treasures.append(t)

    st["treasures"] = remaining_treasures
    save_state(st)
    srv.bump(st, "treasureDismantle", len(deleted_ids) or 1)

    return {
        "treasures": remaining_treasures,
        "deletedTreasures": list(set(deleted_ids)),
        "treasureCapacity": 9999,
        "capacity": 9999,
        "maxCapacity": 9999,
        "maxTreasureCount": 9999,
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "inventories": srv._inventory_models(st),
        "addedExpItems": 0
    }


def r_treasure_set_state(body, st):
    tr = get_st_treasures(st)
    target_id = body_int(body.get("targetId"), 0)
    state = body_int(body.get("state"), 0)
    for t in tr:
        if t.get("id") == target_id:
            t["state"] = state
    save_state(st)
    return r_treasure(body, st)


# Legacy (treasure) enhancement: the client labels it "Enhance Legacy"
# (TreasureUpgrade) / "Tier Transcendence" (TreasureAlreadyMaxOvercome).
# Costs come from TreasureConstants.xml: TreasureLevelCost (exp+gold per level,
# per rarity), TreasureOvercomeCost (item 3200 초월의 주괴 per overcome step:
# Common 0 / Rare 1 / Special 6, MaxOvercome 10), TreasureOvercomeUp
# (overcome tier -> max level 10+2*overcome). Exp items: 3000 Legacy Piece = 30
# exp, 3100 = 150 (InventoryItems.xml AddTreasureExp).
TREASURE_EXP_ITEM_VALUES = {3000: 30, 3100: 150}
TREASURE_OVERCOME_ITEM = 3200
_TREASURE_META = None


def _treasure_meta():
    global _TREASURE_META
    if _TREASURE_META is None:
        from xml.etree import ElementTree as ET
        root = ET.parse(XML_DIR / "TreasureConstants.xml").getroot()
        costs = {}
        for rarity in root.find("TreasureLevelCost"):
            costs[rarity.tag] = {
                int(c.get("Level")): (int(c.get("NeedExp")), int(c.get("NeedGold")))
                for c in rarity.findall("Cost")}
        oc = {c.tag: (int(c.get("MaxOvercome")), int(c.get("NeedMaterial")))
              for c in root.find("TreasureOvercomeCost").findall("*")}
        up = {int(c.get("Overcome")): int(c.get("MaxLevel"))
              for c in root.find("TreasureOvercomeUp").findall("*")
              if c.get("EventType") == "Treasure"}
        rarities = {}
        troot = ET.parse(XML_DIR / "Treasures.xml").getroot()
        for t in troot.findall("Treasure"):
            rarities[int(t.get("ID"))] = t.findtext("Rarity", "Common")
        _TREASURE_META = {"costs": costs, "overcome": oc, "up": up, "rarities": rarities}
    return _TREASURE_META


def _treasure_rarity(t):
    return _treasure_meta()["rarities"].get(int(t.get("treasureId")), "Common")


def _treasure_max_level(overcome):
    return _treasure_meta()["up"].get(int(overcome), 10 + 2 * int(overcome))


def _treasure_result(st, added_exp=0):
    return {
        "treasures": get_st_treasures(st),
        "deletedTreasures": [],
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "inventories": srv._inventory_models(st),
        "addedExpItems": added_exp,
    }


def r_treasure_add_exp(body, st):
    """"Enhance Legacy": feed exp items (Legacy Pieces) + gold, level the treasure.
    Mirrors the accessory add-exp flow; response is TreasureResultResponseModel."""
    admin_log(f"[treasure-add-exp] body={body}")
    tr = get_st_treasures(st)
    t = next((x for x in tr if x.get("id") == body_int(body.get("targetId"), 0)), None)
    if t is None:
        return _treasure_result(st)
    total_exp = 0
    for it in (body.get("expItems") or []):
        iid = int(it.get("id", 0) or 0)
        cnt = int(it.get("count", 0) or 0)
        unit = TREASURE_EXP_ITEM_VALUES.get(iid, 0)
        if unit and cnt > 0 and accessory._deduct_inventory_item(st, iid, cnt):
            total_exp += unit * cnt
    rarity = _treasure_rarity(t)
    costs = _treasure_meta()["costs"].get(rarity, {})
    level = int(t.get("level", 1))
    exp = int(t.get("exp", 0)) + total_exp
    while level < _treasure_max_level(t.get("overcome", 0)):
        need_exp, need_gold = costs.get(level + 1, (10 ** 9, 0))
        if exp < need_exp or st.get("gold", 0) < need_gold:
            break
        st["gold"] -= need_gold
        exp -= need_exp
        level += 1
    t["level"] = level
    t["exp"] = exp
    t["updatedAt"] = now_iso()
    save_state(st)
    return _treasure_result(st, added_exp=total_exp)


def r_treasure_overcome(body, st):
    """"Tier Transcendence": consume item 3200 (초월의 주괴) per TreasureOvercomeCost
    and raise the treasure's overcome tier (max level +2 per tier, cap 10)."""
    admin_log(f"[treasure-overcome] body={body}")
    tr = get_st_treasures(st)
    t = next((x for x in tr if x.get("id") == body_int(body.get("targetId"), 0)), None)
    if t is None:
        return _treasure_result(st)
    rarity = _treasure_rarity(t)
    max_overcome, need_material = _treasure_meta()["overcome"].get(rarity, (10, 0))
    overcome = int(t.get("overcome", 0))
    if overcome >= max_overcome:
        return _treasure_result(st)
    mats = body.get("materialTreasureIds") or []
    if mats:
        ids = [int(m.get("id", m) if isinstance(m, dict) else m) for m in mats]
        tr[:] = [x for x in tr if x.get("id") not in ids]
        st["treasures"] = tr
    if need_material and not accessory._deduct_inventory_item(st, TREASURE_OVERCOME_ITEM, need_material):
        return _treasure_result(st)
    t["overcome"] = overcome + 1
    t["updatedAt"] = now_iso()
    save_state(st)
    return _treasure_result(st)


def r_rift_weapon(body, st):
    return rift.r_rift_weapon_inventory(body, st)