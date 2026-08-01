import xml.etree.ElementTree as ET
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

_GACHAS_CACHE = None
_UNITS_CACHE = []

def _int(el, tag, default=0):
    val = el.findtext(tag)
    return int(val) if val is not None else default

def _get_all_units(xml_dir):
    global _UNITS_CACHE
    if not _UNITS_CACHE:
        tree = ET.parse(xml_dir / "Units.xml")
        for unit in tree.findall("Unit"):
            uid = int(unit.get("ID", 0))
            if uid > 0 and unit.findtext("IsObtainable") != "false":
                _UNITS_CACHE.append(uid)
        if not _UNITS_CACHE:
            _UNITS_CACHE = [10000, 10010, 10020]
    return _UNITS_CACHE

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
    for r in gacha_el.findall("Results/Result"):
        weight = int(r.get("Rate", 0))
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
    units = _get_all_units(xml_dir)
    
    gacha_collections = []
    
    for _ in range(amount):
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

            item_id = random.choice(units)
            count = random.randint(chosen["min"], chosen["max"])
            type_str = chosen["type"]

            if type_str == "Unit":
                count = 1
            elif type_str == "Gold":
                item_id = 0 # Gold has no item ID usually

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
