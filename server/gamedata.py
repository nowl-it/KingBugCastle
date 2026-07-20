"""Master-data lookups shared by the dashboard (and usable from scripts).

Everything here is read-only and parsed once at import from `xml_live/` - the same
directory server.py serves its JSON API from and rebuild_xml_bundle.py pushes to the
CDN, so a name shown in the dashboard is the name the client shows.

The interesting part is `stat_label()`: the game stores stat keys like `BaseDefPen`
but Strings_*.xml only has the *bare* key (`DefPen`). Guessing the meaning from the
key name is a trap - `BaseDefPen` is Menace and `BaseDefDen` is Guard, neither is
armour penetration - so every label here is resolved through Strings, never invented.
"""
import os
import re
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
XML_DIR = os.path.join(BASE, "xml_live")
STRINGS_FILE = os.path.join(XML_DIR, "Strings_EN_US.xml")


def _parse(fname):
    try:
        return list(ET.parse(os.path.join(XML_DIR, fname)).getroot())
    except Exception as e:
        print(f"[gamedata] {fname}: {e}", flush=True)
        return []


def _load_strings():
    out = {}
    for el in _parse("Strings_EN_US.xml"):
        k = el.get("Key")
        if k and el.text:
            out[k] = el.text
    return out


STRINGS = _load_strings()


def s(key, default=None):
    return STRINGS.get(key, default)


# --- stats -----------------------------------------------------------------
# Strings holds the bare stat key; saves hold decorated variants. Resolution order:
# exact -> without the "Base" prefix -> without the "Per" suffix -> both.
_PERCENT_SUFFIX = ("Per", "Mul", "Prob")


def stat_label(key):
    """'BaseDefPen' -> 'Menace'. Falls back to the raw key so an unknown stat is
    visible as itself rather than silently blank."""
    if not key:
        return ""
    for cand in (key, re.sub(r"^Base", "", key),
                 re.sub(r"(Per)$", "", key), re.sub(r"^Base|(Per)$", "", key)):
        if cand in STRINGS:
            return STRINGS[cand]
    return key


def stat_is_percent(key):
    return bool(key) and key.endswith(_PERCENT_SUFFIX)


def fmt_stat(key, value):
    if value is None:
        return ""
    txt = f"{value:g}"
    return txt + "%" if stat_is_percent(key) else txt


# --- heroes ----------------------------------------------------------------
def _load_heroes():
    """id (int) -> {id,name,role,sprite}. Only visible Player units."""
    names = {k[len("UnitName_"):]: v for k, v in STRINGS.items() if k.startswith("UnitName_")}
    out = {}
    for unit in _parse("Units.xml"):
        if (unit.findtext("Type") or "") != "Player":
            continue
        if (unit.findtext("Visible") or "") == "false":
            continue
        uid = unit.get("ID")
        if not uid:
            continue
        out[int(uid)] = {
            "id": int(uid),
            "name": names.get(uid, f"Unit_{uid}"),
            "role": unit.findtext("Role") or "Unknown",
            "sprite": unit.findtext("Sprite"),
        }
    return out


HEROES = _load_heroes()
HEROES_BY_NAME = {h["name"].lower(): h for h in HEROES.values()}


def hero(uid):
    return HEROES.get(int(uid)) if str(uid).lstrip("-").isdigit() else None


def hero_name(uid):
    h = hero(uid)
    return h["name"] if h else f"Unit {uid}"


# --- items -----------------------------------------------------------------
def _load_items():
    out = {}
    for it in _parse("InventoryItems.xml"):
        iid = it.get("ID")
        if not iid:
            continue
        namekey = (it.findtext("Name") or "").strip()
        out[int(iid)] = {
            "id": int(iid),
            "name": STRINGS.get(namekey) or it.findtext("AdminToolOnlyName") or namekey or iid,
            "sub": it.findtext("Type") or "None",
        }
    return out


ITEMS = _load_items()


def item_name(iid):
    it = ITEMS.get(int(iid))
    return it["name"] if it else f"Item {iid}"


# --- accessories -----------------------------------------------------------
ACCESSORY_TYPES = {1: "Necklace", 2: "Bracelet", 3: "Ring", 4: "Earring"}
RARITY_NAMES = {0: "Common", 1: "Uncommon", 2: "Rare", 3: "Special"}


def _accessory_constants():
    """(score thresholds, grade letters). Thresholds come from AccessoryConstants.xml;
    the letters are the client's GradePerColorAndText dict, keys 0..5.

    A score at or above the LAST threshold (26.5) maps to index 6, which the client's
    TryGetValue misses - it hides the badge. That is the real ceiling, so it is
    represented here as a `None` grade rather than an invented 7th letter."""
    root = None
    try:
        root = ET.parse(os.path.join(XML_DIR, "AccessoryConstants.xml")).getroot()
    except Exception as e:
        print(f"[gamedata] AccessoryConstants.xml: {e}", flush=True)
    txt = (root.findtext("AccessorySubStatScoreRange") if root is not None else None) or ""
    thresholds = [float(x) for x in txt.split(",") if x.strip()]
    return thresholds, ["D", "C", "B", "A", "S", "SS"]


SUBSTAT_SCORE_RANGE, GRADE_LETTERS = _accessory_constants()


def substat_grade(score):
    """Mirror of Utility.LowerBound + GradePerColorAndText lookup: the index of the
    greatest threshold <= score. Returns None when the client would hide the badge."""
    if score is None:
        return None
    idx = 0
    for t in SUBSTAT_SCORE_RANGE:
        if score >= t:
            idx += 1
        else:
            break
    idx -= 1
    return GRADE_LETTERS[idx] if 0 <= idx < len(GRADE_LETTERS) else None


def synergy_name(sid):
    return STRINGS.get(f"AccessorySynergyName_{sid}", f"Set {sid}")


SYNERGY_NAMES = {i: synergy_name(i) for i in range(13)}


def decorate_accessory(acc):
    """Turn a raw save accessory into something displayable: resolved set/type/stat
    names and the grade badge the client computes for each sub-stat."""
    subs = acc.get("subStats") or []
    scores = acc.get("subStatScores") or []
    data = acc.get("data") or {}
    main = data.get("mainStat", "")
    return {
        "id": acc.get("id"),
        "type": acc.get("type"),
        "typeName": ACCESSORY_TYPES.get(acc.get("type"), "?"),
        "synergy": acc.get("synergy"),
        "synergyName": synergy_name(acc.get("synergy")),
        "rarity": acc.get("rarity"),
        "rarityName": RARITY_NAMES.get(acc.get("rarity"), str(acc.get("rarity"))),
        "level": acc.get("level", 0),
        "unitId": acc.get("unitId", 0),
        "unitName": hero_name(acc["unitId"]) if acc.get("unitId") else None,
        "mainStat": main,
        "mainStatLabel": stat_label(main),
        "subStats": [
            {
                "key": k,
                "label": stat_label(k),
                "score": sc,
                "grade": substat_grade(sc),
                "percent": stat_is_percent(k),
            }
            for k, sc in zip(subs, list(scores) + [None] * len(subs))
        ],
        "scoreTotal": round(sum(x for x in scores if isinstance(x, (int, float))), 2),
    }


# --- reward catalog (mail picker) ------------------------------------------
def load_catalog():
    cat = {"Item": [], "Unit": [], "UnitSoul": [], "Artifact": [], "Treasure": [], "Accessory": []}
    cat["Item"] = sorted(ITEMS.values(), key=lambda x: x["id"])
    for h in sorted(HEROES.values(), key=lambda x: x["id"]):
        entry = {"id": h["id"], "name": h["name"], "sub": h["role"]}
        cat["Unit"].append(entry)
        cat["UnitSoul"].append(dict(entry))
    for a in _parse("Artifacts.xml"):
        if a.get("ID"):
            cat["Artifact"].append({"id": int(a.get("ID")),
                                    "name": STRINGS.get(f"ArtifactName_{a.get('ID')}", f"Artifact {a.get('ID')}")})
    for t in _parse("Treasures.xml"):
        if t.get("ID"):
            cat["Treasure"].append({"id": int(t.get("ID")),
                                    "name": STRINGS.get(f"TreasureName_{t.get('ID')}", f"Treasure {t.get('ID')}")})
    for ac in _parse("FixedAccessoryPresets.xml"):
        if ac.get("ID"):
            cat["Accessory"].append({"id": int(ac.get("ID")),
                                     "name": STRINGS.get(f"AccessoryName_{ac.get('ID')}", f"Accessory {ac.get('ID')}")})
    for k in cat:
        cat[k].sort(key=lambda x: x["id"])
    return cat


# --- battle-tracker effect resolution --------------------------------------
BUFF_NAMES = {k[len("BuffDataName_"):]: v for k, v in STRINGS.items() if k.startswith("BuffDataName_")}
BUFF_DESCS = {k[len("BuffDataDesc_"):]: v for k, v in STRINGS.items() if k.startswith("BuffDataDesc_")}
SKILL_NAMES = {k[len("SkillName_"):]: v for k, v in STRINGS.items() if k.startswith("SkillName_")}
SKILL_DESCS = {k[len("SkillDesc_"):]: v for k, v in STRINGS.items() if k.startswith("SkillDesc_")}

CATEGORY_LABELS = {
    "BuffOpt": "Buff", "Bind": "Bind", "Item": "Item", "Tile": "Tile Buff",
    "Skill": "Skill", "Syn": "Synergy", "Poten": "Potential", "Event": "Event",
    "Custom": "Custom", "Treasure": "Treasure", "Acc": "Accessory", "Rune": "Rune",
    "Mark": "Mark", "Global": "Global", "Overcome": "Overcome",
}


def clean_desc(text):
    if not text:
        return None
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{[0-9]+\}", "N", text)
    text = re.sub(r"\\n|\n", " ", text)
    return re.sub(r"\s+", " ", text).strip() or None


def resolve_effects(eff_field):
    """'N[b123@2.5/5.0,s456,Poten]' -> [{name,kind,desc,time,total} ...]."""
    if not eff_field:
        return []
    inner = eff_field[eff_field.find("[") + 1: eff_field.rfind("]")]
    out = []
    for tok in inner.split(","):
        tok = tok.strip()
        if not tok:
            continue
        time_v = total_v = None
        if "@" in tok:
            tok, timing = tok.split("@", 1)
            if "/" in timing:
                try:
                    a, b = timing.split("/", 1)
                    time_v, total_v = float(a), float(b)
                except ValueError:
                    pass
        eff = {"name": tok, "kind": "category", "desc": None, "time": time_v, "total": total_v}
        if tok and tok[0] == "b" and tok[1:].isdigit():
            eff["name"] = BUFF_NAMES.get(tok[1:], f"Buff #{tok[1:]}")
            eff["kind"] = "buff"
            eff["desc"] = clean_desc(BUFF_DESCS.get(tok[1:]))
        elif tok and tok[0] == "s" and tok[1:].isdigit():
            sid = tok[1:]
            eff["name"] = SKILL_NAMES.get(sid) or SKILL_NAMES.get(sid[:-1]) or f"Skill #{sid}"
            eff["kind"] = "skill"
            eff["desc"] = clean_desc(SKILL_DESCS.get(sid) or SKILL_DESCS.get(sid[:-1]))
        else:
            eff["name"] = CATEGORY_LABELS.get(tok, tok)
        out.append(eff)
    return out


def summary():
    return {"strings": len(STRINGS), "heroes": len(HEROES), "items": len(ITEMS),
            "buffs": len(BUFF_NAMES), "skills": len(SKILL_NAMES)}


if __name__ == "__main__":
    # Self-check: the stat-key resolution is the part that silently produces wrong
    # labels, so pin the two that were historically misread plus one of each shape.
    assert stat_label("BaseDefPen") == "Menace", stat_label("BaseDefPen")
    assert stat_label("BaseDefDen") == "Guard", stat_label("BaseDefDen")
    assert stat_label("AtkPer") == "ATK", stat_label("AtkPer")
    assert stat_label("BaseDef") == "Physical DEF", stat_label("BaseDef")
    assert stat_label("HpPer") == "HP", stat_label("HpPer")
    assert stat_label("NotAStat") == "NotAStat"
    assert stat_is_percent("HpPer") and not stat_is_percent("BaseDef")
    # Grade boundaries: below the first threshold there is no badge; each threshold
    # starts its letter; at/over the last one the client hides the badge entirely.
    assert SUBSTAT_SCORE_RANGE[:2] == [1.0, 4.5], SUBSTAT_SCORE_RANGE
    assert substat_grade(0.5) is None
    assert substat_grade(1.0) == "D"
    assert substat_grade(22.0) == "S", substat_grade(22.0)
    assert substat_grade(22.5) == "SS"
    assert substat_grade(26.0) == "SS"
    assert substat_grade(26.5) is None, "26.5+ overflows the client dict -> badge hidden"
    assert synergy_name(0) == "Steel" and synergy_name(1) == "Fear"
    print("gamedata ok:", summary(), "| grades:", SUBSTAT_SCORE_RANGE)
