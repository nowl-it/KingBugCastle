import xml.etree.ElementTree as ET
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XML = ROOT / "xml_live"

_GACHAS_CACHE = None
_UNITS_CACHE = None
_SKINS_CACHE = None
_MAP_SKINS_CACHE = None
_TREASURE_CACHE = None
_ARTIFACT_CACHE = None
_SKIN_TOKEN_ID = 2001
_DIM_UNIT_IDS = None

def _get_dim_unit_ids(xml_dir):
    global _DIM_UNIT_IDS
    if _DIM_UNIT_IDS is None:
        _DIM_UNIT_IDS = set()
        try:
            tree = ET.parse(xml_dir / "Units.xml")
            for u in tree.findall("Unit"):
                if (u.findtext("IsDimensionUnit") or "").strip().lower() == "true":
                    _DIM_UNIT_IDS.add(int(u.get("ID", 0)))
        except Exception:
            pass
    return _DIM_UNIT_IDS

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
            le = t.findtext("LimitedEdition")
            mv = int(t.findtext("MinVersion") or 0)
            if tid > 0 and cg != "false" and le != "true" and mv <= 171100:
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

    stacks = st.setdefault("gachaStacks", {})
    base_keys = {str(gacha_id)}
    if item_id > 0:
        base_keys.add(str(item_id))
    parent_id = gacha_el.get("Parent")
    if parent_id:
        base_keys.add(str(parent_id))
    key_item = gacha_el.findtext("KeyItem")
    if key_item:
        base_keys.add(str(key_item))
    gtype = gacha_el.findtext("Type") or ""

    # Parse GachaCeil entries
    ceil_entries = []
    for ce in gacha_el.findall("GachaCeil"):
        ck = ce.get("Key")
        pid = ce.get("PoolID")
        val_text = ce.text
        target_attr = ce.get("Target")
        lim = int(val_text) if (val_text and val_text.isdigit()) else (int(target_attr) if (target_attr and target_attr.isdigit()) else 100)
        ceil_entries.append({
            "key": ck,
            "pool_id": pid,
            "target": target_attr,
            "limit": lim,
        })

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
    dim_ids = _get_dim_unit_ids(xml_dir)
    
    # Check for featured pickup items on the Gacha banner
    pickup_treasures = []
    pickups_el = gacha_el.find("Pickups")
    if pickups_el is not None:
        for p in pickups_el.findall("Pickup"):
            pid = p.get("PoolID")
            if pid:
                pickup_treasures.append(30041)

    t_cache = _get_treasures(xml_dir)
    special_treasures = set(t_cache.get("Special", []))
    rare_treasures = set(t_cache.get("Rare", []))

    gacha_collections = []
    
    for _ in range(amount):
        # 1. Increment base gacha counters
        for k in base_keys:
            stacks[k] = stacks.get(k, 0) + 1

        # 2. Increment individual ceil counters
        for ce in ceil_entries:
            ck = ce["key"]
            pid = ce["pool_id"]
            if ck:
                stacks[ck] = stacks.get(ck, 0) + 1
            if pid:
                stacks[str(pid)] = stacks.get(str(pid), 0) + 1

        # 3. Check pity hit for each ceil entry in priority order
        special_pity = False
        rare_pity = False
        dim_pity = False
        skin_pity = False

        for ce in ceil_entries:
            ck = ce["key"] or ""
            lim = ce["limit"]
            cur = stacks.get(ck, 0)
            if lim > 0 and cur >= lim:
                if "Special" in ck:
                    special_pity = True
                elif "Rare" in ck:
                    rare_pity = True
                elif "DimGachaCeil" in ck:
                    dim_pity = True
                elif "SkinGachaCeil" in ck:
                    skin_pity = True

        if gacha_el.find("UnitCount") is None:
            num_rolls = 1
        else:
            uc = gacha_el.find("UnitCount")
            num_rolls = random.randint(int(uc.get("Min", 3)), int(uc.get("Max", 3)))
            
        gacha_list = []
        reward_gacha_list = []
        collection_has_upgrade = False
        
        for _ in range(num_rolls):
            pull_res = None
            is_reward = (gtype == "SkinGacha")

            if special_pity:
                if gacha_id in (5052, 6004):
                    c_pick = st.get("customPickups", {}).get(str(gacha_id), [30041])
                    c_tr = c_pick[0] if c_pick else 30041
                    pull_res = {"type": "Treasure", "unitId": c_tr, "count": 1, "isNew": True}
                else:
                    tid = random.choice(t_cache.get("Special", [30041]))
                    pull_res = {"type": "Treasure", "unitId": tid, "count": 1, "isNew": True}
                for ce in ceil_entries:
                    if "Special" in (ce["key"] or ""):
                        if ce["key"]:
                            stacks[ce["key"]] = 0
                        if ce["pool_id"]:
                            stacks[str(ce["pool_id"])] = 0
                special_pity = False
            elif dim_pity:
                uid = 10790
                is_new = str(uid) not in st.get("cards", {})
                dim_id = uid if uid in dim_ids else 0
                pull_res = {"type": "Unit", "unitId": uid, "count": 1, "isNew": is_new, "dimensionUnitId": dim_id}
                if not is_new:
                    collection_has_upgrade = True
                for ce in ceil_entries:
                    if "DimGachaCeil" in (ce["key"] or ""):
                        if ce["key"]:
                            stacks[ce["key"]] = 0
                dim_pity = False
            elif skin_pity:
                map_skins_cache = _get_map_skins(xml_dir)
                map_skin_pool = map_skins_cache.get(2) or map_skins_cache.get(3) or map_skins_cache.get("all") or [10000]
                msid = random.choice(map_skin_pool)
                is_new = msid not in st.get("mapSkins", [])
                pull_res = {"type": "MapSkin", "unitId": msid, "count": 1, "isNew": is_new}
                for ce in ceil_entries:
                    if "SkinGachaCeil" in (ce["key"] or ""):
                        if ce["key"]:
                            stacks[ce["key"]] = 0
                skin_pity = False
            elif rare_pity:
                tid = random.choice(t_cache.get("Rare", [20000]))
                pull_res = {"type": "Treasure", "unitId": tid, "count": 1, "isNew": True}
                for ce in ceil_entries:
                    if "Rare" in (ce["key"] or ""):
                        if ce["key"]:
                            stacks[ce["key"]] = 0
                        if ce["pool_id"]:
                            stacks[str(ce["pool_id"])] = 0
                rare_pity = False
            else:
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
                is_reward = chosen.get("is_reward", is_reward)

                if type_str == "Unit":
                    uid = chosen.get("id") or hero_id
                    is_new = str(uid) not in st.get("cards", {})
                    dim_id = uid if uid in dim_ids else 0
                    pull_res = {"type": "Unit", "unitId": uid, "count": 1, "isNew": is_new, "dimensionUnitId": dim_id}
                    if not is_new:
                        collection_has_upgrade = True
                elif type_str == "Gold":
                    pull_res = {"type": "Gold", "unitId": 0, "count": count, "isNew": True}
                elif type_str in ("Treasure", "TreasureGacha"):
                    rarity = chosen.get("rarity", "Common")
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
                    grade = int(chosen.get("id", 0))
                    skins_cache = _get_skins(xml_dir)
                    skin_pool = skins_cache.get(grade) or skins_cache.get("all") or [1000001]
                    sid = random.choice(skin_pool)
                    is_new = sid not in st.get("skins", [])
                    pull_res = {"type": "Skin", "unitId": sid, "count": 1, "isNew": is_new}
                elif type_str == "MapSkin_Grade":
                    grade = int(chosen.get("id", 0))
                    map_skins_cache = _get_map_skins(xml_dir)
                    map_skin_pool = map_skins_cache.get(grade) or map_skins_cache.get("all") or [10000]
                    msid = random.choice(map_skin_pool)
                    is_new = msid not in st.get("mapSkins", [])
                    pull_res = {"type": "MapSkin", "unitId": msid, "count": 1, "isNew": is_new}
                elif type_str == "LoginSkin_Grade":
                    pull_res = {"type": "Item", "unitId": 2001, "count": 15, "isNew": True}
                elif type_str in ("UnitExp", "UnitSoul", "UnitSoulItem"):
                    pull_res = {"type": type_str, "unitId": hero_id, "count": count, "isNew": True}
                else:
                    uid = chosen.get("id") or 0
                    pull_res = {"type": type_str, "unitId": uid, "count": count, "isNew": True}

                # Check natural resets
                if pull_res.get("type") == "Treasure":
                    tid = pull_res.get("unitId", 0)
                    if tid in special_treasures:
                        for ce in ceil_entries:
                            if "Special" in (ce["key"] or ""):
                                if ce["key"]:
                                    stacks[ce["key"]] = 0
                                if ce["pool_id"]:
                                    stacks[str(ce["pool_id"])] = 0
                    elif tid in rare_treasures:
                        for ce in ceil_entries:
                            if "Rare" in (ce["key"] or ""):
                                if ce["key"]:
                                    stacks[ce["key"]] = 0
                                if ce["pool_id"]:
                                    stacks[str(ce["pool_id"])] = 0
                elif pull_res.get("type") == "MapSkin" and chosen.get("id") in (2, 3, "2", "3"):
                    for ce in ceil_entries:
                        if "SkinGachaCeil" in (ce["key"] or ""):
                            if ce["key"]:
                                stacks[ce["key"]] = 0
                elif pull_res.get("type") == "Unit" and pull_res.get("unitId") == 10790 and gacha_id == 8001:
                    for ce in ceil_entries:
                        if "DimGachaCeil" in (ce["key"] or ""):
                            if ce["key"]:
                                stacks[ce["key"]] = 0

            if pull_res:
                if is_reward and gtype == "SkinGacha":
                    _WIRE_TYPE = {"Item": "InventoryItem", "Unit": "Card", "UnitSoul": "CardSoul"}
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
            "upgrade": collection_has_upgrade
        })
        
    return gacha_collections
