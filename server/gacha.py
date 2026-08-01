import xml.etree.ElementTree as ET
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

_GACHAS_CACHE = None
_UNITS_CACHE = None
_TREASURE_CACHE = None
_ARTIFACT_CACHE = None

def _int(el, tag, default=0):
    val = el.findtext(tag)
    return int(val) if val is not None else default

def _get_pools(xml_dir):
    global _UNITS_CACHE
    if not _UNITS_CACHE:
        _UNITS_CACHE = {"normal": [], "king": []}
        # Known King God heroes from Banner 302 WelcomeUnitList + a few typical high IDs
        king_ids = {10070, 10110, 10170, 10210, 10220, 10260, 10280, 10290, 10300, 10310, 10320}
        
        tree = ET.parse(xml_dir / "Units.xml")
        for unit in tree.findall("Unit"):
            uid = int(unit.get("ID", 0))
            if uid > 0 and unit.findtext("Type") == "Player" and unit.findtext("IsObtainable") != "false":
                if uid in king_ids:
                    _UNITS_CACHE["king"].append(uid)
                else:
                    _UNITS_CACHE["normal"].append(uid)
        
        if not _UNITS_CACHE["king"]:
            _UNITS_CACHE["king"] = [10260]
        if not _UNITS_CACHE["normal"]:
            _UNITS_CACHE["normal"] = [10000, 10010, 10020]
    return _UNITS_CACHE

def _get_treasures(xml_dir):
    global _TREASURE_CACHE
    if not _TREASURE_CACHE:
        _TREASURE_CACHE = {"Common": [], "Rare": [], "Special": []}
        tree = ET.parse(xml_dir / "Treasures.xml")
        for t in tree.findall("Treasure"):
            tid = int(t.get("ID", 0))
            if tid > 0:
                r = t.findtext("Rarity")
                if r in _TREASURE_CACHE:
                    _TREASURE_CACHE[r].append(tid)
        for k in _TREASURE_CACHE:
            if not _TREASURE_CACHE[k]:
                _TREASURE_CACHE[k] = [10001] # fallback
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

def roll(gacha_id, amount, st, xml_dir=DEFAULT_XML):
    gacha_el = _get_gacha(gacha_id, xml_dir)
    if gacha_el is None:
        return []
        
    results = []
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
                    "rarity": r.get("Rarity", "Common")
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
                result_pool.append({
                    "weight": weight,
                    "type": rtype,
                    "min": int(r.get("Min", 1)),
                    "max": int(r.get("Max", r.get("Min", 1)))
                })
            
    if not result_pool:
        return []
        
    total_weight = sum(r["weight"] for r in result_pool)
    pools = _get_pools(xml_dir)
    is_king = (gacha_id >= 301) # Banners 301, 302, 303 etc are King/God tier
    units = pools["king"] if is_king else pools["normal"]
    
    gacha_collections = []
    
    for _ in range(amount):
        scroll_hero_id = random.choice(units)
        if gacha_el.find("UnitCount") is None:
            num_rolls = 1
        else:
            uc = gacha_el.find("UnitCount")
            num_rolls = random.randint(int(uc.get("Min", 3)), int(uc.get("Max", 3)))
            
        gacha_list = []
        for _ in range(num_rolls):
            r = random.uniform(0, total_weight)
            cum = 0
            chosen = result_pool[-1]
            for p in result_pool:
                cum += p["weight"]
                if r <= cum:
                    chosen = p
                    break

            item_id = scroll_hero_id
            count = random.randint(chosen["min"], chosen["max"])
            type_str = chosen["type"]

            if type_str == "Unit":
                count = 1
            elif type_str == "Gold":
                item_id = 0 # Gold has no item ID usually
            elif type_str == "Treasure":
                t_cache = _get_treasures(xml_dir)
                r_pool = t_cache.get(chosen.get("rarity", "Common")) or t_cache["Common"]
                item_id = random.choice(r_pool)
            elif type_str == "Artifact":
                a_cache = _get_artifacts(xml_dir)
                if chosen.get("art_id"):
                    item_id = int(chosen["art_id"])
                else:
                    ft = chosen.get("from_type")
                    lv = chosen.get("level")
                    k = f"{ft}_{lv}"
                    a_pool = a_cache.get(k) or a_cache["all"]
                    item_id = random.choice(a_pool)

            gacha_list.append({
                "type": type_str,
                "unitId": item_id,
                "count": count,
                "isNew": True,
                "gachaCount": 0,
                "mileageAmount": 0
            })

        gacha_collections.append({
            "gacha": gacha_list,
            "rewardGacha": [],
            "upgrade": False
        })
        
    return gacha_collections
