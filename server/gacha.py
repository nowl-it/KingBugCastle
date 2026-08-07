import xml.etree.ElementTree as ET
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

_GACHAS_CACHE = None
_UNITS_CACHE = None
_SKINS_CACHE = None
_MAP_SKINS_CACHE = None
_TREASURE_CACHE = None
_ARTIFACT_CACHE = None
_SKIN_TOKEN_ID = 2001

def _int(el, tag, default=0):
    val = el.findtext(tag)
    return int(val) if val is not None else default

def _get_units(xml_dir):
    global _UNITS_CACHE
    if not _UNITS_CACHE:
        _UNITS_CACHE = []
        tree = ET.parse(xml_dir / "Units.xml")
        for unit in tree.findall("Unit"):
            uid = int(unit.get("ID", 0))
            if 10000 <= uid <= 10999 and unit.findtext("Type") == "Player" and unit.findtext("IsObtainable") != "false":
                _UNITS_CACHE.append(uid)
        if not _UNITS_CACHE:
            _UNITS_CACHE = [10000, 10010, 10020, 10040, 10070, 10210, 10260]
    return _UNITS_CACHE

def _get_skins(xml_dir):
    global _SKINS_CACHE
    if not _SKINS_CACHE:
        _SKINS_CACHE = {0: [], 1: [], 2: [], 3: [], 4: []}
        tree = ET.parse(xml_dir / "Skins.xml")
        for s in tree.findall("Skin"):
            sid = int(s.get("ID", 0))
            if 1000000 <= sid <= 1099999 and not str(sid).endswith("99"):
                g_val = s.findtext("Grade")
                if g_val is not None and g_val.isdigit():
                    grade = int(g_val)
                    _SKINS_CACHE.setdefault(grade, []).append(sid)
                    _SKINS_CACHE.setdefault("all", []).append(sid)
        for k in (0, 1, 2, 3, 4):
            if not _SKINS_CACHE.get(k):
                _SKINS_CACHE[k] = _SKINS_CACHE.get("all", [1000001])
    return _SKINS_CACHE

def _get_map_skins(xml_dir):
    global _MAP_SKINS_CACHE
    if not _MAP_SKINS_CACHE:
        _MAP_SKINS_CACHE = {0: [], 1: [], 2: [], 3: []}
        tree = ET.parse(xml_dir / "MapSkins.xml")
        for ms in tree.findall("MapSkin"):
            msid = int(ms.get("ID", 0))
            if msid > 0:
                grade = _int(ms, "Grade", 0)
                _MAP_SKINS_CACHE.setdefault(grade, []).append(msid)
                _MAP_SKINS_CACHE.setdefault("all", []).append(msid)
        for k in (0, 1, 2, 3):
            if not _MAP_SKINS_CACHE.get(k):
                _MAP_SKINS_CACHE[k] = _MAP_SKINS_CACHE.get("all", [10000])
    return _MAP_SKINS_CACHE

def _get_treasures(xml_dir):
    global _TREASURE_CACHE
    if not _TREASURE_CACHE:
        _TREASURE_CACHE = {"Common": [], "Rare": [], "Special": []}
        tree = ET.parse(xml_dir / "Treasures.xml")
        for t in tree.findall("Treasure"):
            tid = int(t.get("ID", 0))
            cg = t.findtext("CanGacha")
            mv = int(t.findtext("MinVersion") or 0)
            if tid > 0 and cg != "false" and mv <= 171100:
                r = t.findtext("Rarity")
                if r in _TREASURE_CACHE:
                    _TREASURE_CACHE[r].append(tid)
        for k in _TREASURE_CACHE:
            if not _TREASURE_CACHE[k]:
                _TREASURE_CACHE[k] = [10000]
    return _TREASURE_CACHE

def _get_artifacts(xml_dir):
    global _ARTIFACT_CACHE
    if not _ARTIFACT_CACHE:
        _ARTIFACT_CACHE = {}
        tree = ET.parse(xml_dir / "Artifacts.xml")
        for a in tree.findall("Artifact"):
            aid = int(a.get("ID", 0))
            if aid > 0 and a.findtext("Type") == "Artifact":
                ft = a.findtext("FromType")
                lv = a.findtext("Level")
                if ft and lv:
                    key = f"{ft}_{lv}"
                    _ARTIFACT_CACHE.setdefault(key, []).append(aid)
                _ARTIFACT_CACHE.setdefault("all", []).append(aid)
        if not _ARTIFACT_CACHE:
            _ARTIFACT_CACHE["all"] = [501]
    return _ARTIFACT_CACHE

def _get_gacha(gacha_id, xml_dir):
    global _GACHAS_CACHE
    if not _GACHAS_CACHE:
        _GACHAS_CACHE = {}
        tree = ET.parse(xml_dir / "Gachas.xml")
        for g in tree.findall("Gacha"):
            gid = g.get("ID")
            if gid:
                _GACHAS_CACHE[int(gid)] = g
    return _GACHAS_CACHE.get(gacha_id)

def roll(gacha_id, amount, st, xml_dir=DEFAULT_XML, item_id=0):
    gacha_el = _get_gacha(gacha_id, xml_dir)
    if gacha_el is None:
        return []

    # Pity tracking: increment stack for gacha_id, parent_id, key_item, item_id, and category IDs
    stacks = st.setdefault("gachaStacks", {})
    keys_to_update = {str(gacha_id)}
    if item_id > 0:
        keys_to_update.add(str(item_id))
    parent_id = gacha_el.get("Parent")
    if parent_id:
        keys_to_update.add(str(parent_id))
    key_item = gacha_el.findtext("KeyItem")
    if key_item:
        keys_to_update.add(str(key_item))
        
    gacha_ceil = gacha_el.find("GachaCeil")
    if gacha_ceil is not None:
        ceil_key = gacha_ceil.get("Key")
        if ceil_key:
            keys_to_update.add(ceil_key)

    gtype = gacha_el.findtext("Type") or ""
    if "Treasure" in gtype or parent_id == "102":
        keys_to_update.update({"3999", "370", "371", "102", "131000", "121000", "231052"})
    elif "Unit" in gtype or parent_id == "100":
        keys_to_update.update({"300", "303", "305", "100", "2007"})
    elif "Skin" in gtype or parent_id == "103":
        keys_to_update.update({"7000", "390", "103"})

    for k in keys_to_update:
        stacks[k] = stacks.get(k, 0) + amount

    result_pool = []
    
    fixed_treasures = gacha_el.find("FixedTreasures")
    fixed_artifacts = gacha_el.find("FixedArtifacts")
    
    if fixed_treasures is not None:
        for r in fixed_treasures.findall("Treasure"):
            weight = float(r.get("Rate", 0)) * 10
            if weight > 0:
                result_pool.append({
                    "weight": weight,
                    "type": "Treasure",
                    "min": 1,
                    "max": 1,
                    "rarity": r.get("Rarity", "Common"),
                    "pool_id": r.get("PoolID")
                })
    elif fixed_artifacts is not None:
        for r in fixed_artifacts.findall("Artifact"):
            weight = float(r.get("Rate", 0)) * 10
            if weight > 0:
                result_pool.append({
                    "weight": weight,
                    "type": "Artifact",
                    "min": 1,
                    "max": 1,
                    "art_id": r.get("ID"),
                    "from_type": r.get("FromType"),
                    "level": r.get("Level")
                })
    else:
        for r in gacha_el.findall("Results/Result"):
            weight = float(r.get("Rate", 0)) * 10
            rtype = r.get("Type")
            if weight > 0 and rtype:
                rid = 0
                raw_id = r.get("ID")
                if raw_id is not None and str(raw_id).isdigit():
                    rid = int(raw_id)
                result_pool.append({
                    "weight": weight,
                    "type": rtype,
                    "min": int(r.get("Min", 1)),
                    "max": int(r.get("Max", r.get("Min", 1))),
                    "id": rid,
                    "rarity": r.get("Rarity"),
                    "is_reward": r.get("IsReward") == "true"
                })
            
    if not result_pool:
        return []
        
    total_weight = sum(r["weight"] for r in result_pool)
    all_heroes = _get_units(xml_dir)
    
    # Check for featured pickup items on the Gacha banner
    pickup_treasures = []
    pickups_el = gacha_el.find("Pickups")
    if pickups_el is not None:
        for p in pickups_el.findall("Pickup"):
            pid = p.get("PoolID")
            if pid:
                # e.g. PoolID 231052 -> Treasure ID 30041 (Audakia)
                pickup_treasures.append(30041)

    gacha_collections = []
    
    for _ in range(amount):
        if gacha_el.find("UnitCount") is None:
            num_rolls = 1
        else:
            uc = gacha_el.find("UnitCount")
            num_rolls = random.randint(int(uc.get("Min", 3)), int(uc.get("Max", 3)))
            
        gacha_list = []
        reward_gacha_list = []
        for _ in range(num_rolls):
            r = random.uniform(0, total_weight)
            cum = 0
            chosen = result_pool[-1]
            for p in result_pool:
                cum += p["weight"]
                if r <= cum:
                    chosen = p
                    break

            hero_id = random.choice(all_heroes)
            count = random.randint(chosen.get("min", 1), chosen.get("max", 1))
            type_str = chosen["type"]
            is_reward = chosen.get("is_reward", False)

            pull_res = None
            if type_str == "Unit":
                pull_res = {"type": "Unit", "unitId": hero_id, "count": 1, "isNew": True}
            elif type_str == "Gold":
                pull_res = {"type": "Gold", "unitId": 0, "count": count, "isNew": True}
            elif type_str in ("Treasure", "TreasureGacha"):
                rarity = chosen.get("rarity", "Common")
                t_cache = _get_treasures(xml_dir)
                if rarity == "Special" and pickup_treasures and random.random() < 0.8:
                    tid = random.choice(pickup_treasures)
                else:
                    r_pool = t_cache.get(rarity) or t_cache["Common"]
                    tid = random.choice(r_pool)
                pull_res = {"type": "Treasure", "unitId": tid, "count": 1, "isNew": True}
            elif type_str in ("Artifact", "ArtifactGacha"):
                a_cache = _get_artifacts(xml_dir)
                if chosen.get("art_id"):
                    aid = int(chosen["art_id"])
                else:
                    ft = chosen.get("from_type")
                    lv = chosen.get("level")
                    k = f"{ft}_{lv}" if ft and lv else None
                    a_pool = (a_cache.get(k) if k else None) or a_cache.get("all") or [501]
                    aid = random.choice(a_pool)
                pull_res = {"type": "Artifact", "unitId": aid, "count": 1, "isNew": True}
            elif type_str in ("SkinToken",):
                pull_res = {"type": "Item", "unitId": 2001, "count": count, "isNew": True}
            elif type_str == "Skin_Grade":
                grade = chosen.get("id", "0")
                import xml.etree.ElementTree as ET
                import pathlib
                cache = getattr(gacha, "_SKIN_GRADE_CACHE", None)
                if cache is None:
                    cache = {}
                    try:
                        tree = ET.parse(pathlib.Path(xml_dir) / "Skins.xml")
                        for skin in tree.findall("Skin"):
                            g = skin.findtext("Grade")
                            if g is not None:
                                cache.setdefault(g, []).append(int(skin.get("ID")))
                        gacha._SKIN_GRADE_CACHE = cache
                    except:
                        pass
                pool = cache.get(str(grade))
                if pool:
                    sid = random.choice(pool)
                    is_new = sid not in st.get("skins", [])
                    pull_res = {"type": "Skin", "unitId": sid, "count": 1, "isNew": is_new}
                else:
                    pull_res = {"type": "SkinToken", "unitId": 0, "count": 5, "isNew": True}
            elif type_str == "MapSkin_Grade":
                grade = chosen.get("id", 0)
                map_skins_cache = _get_map_skins(xml_dir)
                map_skin_pool = map_skins_cache.get(grade) or map_skins_cache.get("all")
                msid = random.choice(map_skin_pool)
                is_new = msid not in st.get("mapSkins", [])
                pull_res = {"type": "MapSkin", "unitId": msid, "count": 1, "isNew": is_new}
            elif type_str == "LoginSkin_Grade":
                pull_res = {"type": "Item", "unitId": _SKIN_TOKEN_ID, "count": 15, "isNew": True}
            elif type_str == "UnitExp":
                pull_res = {"type": "UnitSoul", "unitId": hero_id, "count": count, "isNew": True}
            elif type_str == "UnitSoul":
                pull_res = {"type": "UnitSoul", "unitId": hero_id, "count": count, "isNew": True}
            elif type_str == "UnitSoulItem":
                pull_res = {"type": "UnitSoulItem", "unitId": hero_id, "count": count, "isNew": True}
            else:
                pull_res = {"type": type_str, "unitId": hero_id, "count": count, "isNew": True}

            if pull_res:
                if is_reward:
                    _WIRE_TYPE = {"Item": "InventoryItem", "Unit": "Card", "UnitSoul": "CardSoul"}
                    # Convert pull_res to RewardGachaResult format which contains originReward of type RewardResponseData
                    reward = {
                        "originReward": {
                            "type": _WIRE_TYPE.get(pull_res["type"], pull_res["type"]),
                            "id": pull_res["unitId"],
                            "count": pull_res.get("count", 1)
                        },
                        "replaceTo": None
                    }
                    if pull_res.get("type") == "Skin" and not pull_res.get("isNew"):
                        reward["replaceTo"] = {
                            "type": "InventoryItem",
                            "id": 2001,
                            "count": 5
                        }
                    elif pull_res.get("type") == "MapSkin" and not pull_res.get("isNew"):
                        reward["replaceTo"] = {
                            "type": "InventoryItem",
                            "id": 2011,
                            "count": 5
                        }
                    reward_gacha_list.append(reward)
                else:
                    gacha_list.append(pull_res)

        gacha_collections.append({
            "gacha": gacha_list,
            "rewardGacha": reward_gacha_list,
            "upgrade": False
        })
        
    return gacha_collections
