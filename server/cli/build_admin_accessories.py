#!/usr/bin/env python3
"""Regenerate server/data/admin_accessories.json with the curated custom sets.

Every entry is built from the same main-stat/sub-stat tables that
grant_accessories.py validates against, so nothing here can drift from the
game's rules. Run:

    python3 server/cli/build_admin_accessories.py
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # server/
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cli"))

from cli import grant_accessories  # noqa: E402

# ---------------------------------------------------------------------------
# Sub-stat score rule (Special rarity: two sub-slots, shared budget = 30):
#   the higher-grade sub-stat takes its grade's in-band max
#     SS -> 26 (top of the SS band, just under the 26.5 cutoff)
#     S  -> 22 (just under the SS 22.5 threshold)
#     A  -> 18 (just under the S 18.5 threshold)
#   and the LOWER sub-stat fills the rest of the 30 budget so the pair always
#   sums to exactly 30. This means the lower one is NOT clamped to its own
#   band max - e.g. AB uses 18 + 12 even though B alone could reach 13.
# ---------------------------------------------------------------------------


def pair(hi_value):
    """hi sub-stat value (top of its grade band) + the lo that fills to 30."""
    return hi_value, 30.0 - hi_value


NECKLACE, BRACELET, RING, EARRING = 1, 2, 3, 4
TYPE_NAME = {1: "Necklace", 2: "Bracelet", 3: "Ring", 4: "Earring"}
RARITY, LEVEL = 3, 20                              # Special, max level

# type -> main stat (or [variant0, variant1] for rings) - mirrors grant_accessories
MAINS = {
    "TANK":    {1: "AtkPer", 2: "BaseDef", 3: ["HpPer", "HpPer"], 4: "BaseDef"},
    "MENACE":  {1: "AtkPer", 2: "BaseDef", 3: ["BaseDefPen", "BaseDefPen"], 4: "BaseDef"},
    "GUARD":   {1: "AtkPer", 2: "BaseDef", 3: ["BaseDefDen", "BaseDefDen"], 4: "BaseDef"},
    "GUARD_M": {1: "MAtkPer", 2: "BaseMDef", 3: ["BaseDefDen", "BaseDefDen"], 4: "BaseMDef"},
    "CRIT":    {1: "AtkPer", 2: "BaseDef", 3: ["AttackSpeedPer", "HpPer"], 4: "BaseCriticalDamageMul"},
    "SPELL":   {1: "MAtkPer", 2: "BaseMDef", 3: ["AttackSpeedPer", "HpPer"], 4: "BaseMCriticalDamageMul"},
    "SPECIAL": {1: "AtkPer", 2: "BaseDef", 3: ["AttackSpeedPer", "HpPer"], 4: "BaseSpecialDamageMul"},
}

# synergy id -> (set name, mains key)
SETS = {
    0:  ("Steel",     "TANK"),
    1:  ("Fear",      "MENACE"),
    3:  ("Ocean",     "GUARD"),
    5:  ("Barbarian", "SPECIAL"),
    7:  ("Covenant",  "SPELL"),
    8:  ("Eternity",  "GUARD_M"),
    9:  ("Moonlight", "CRIT"),
    11: ("Fatality",  "SPECIAL"),
    12: ("Ascension", "GUARD"),
}

entries = []


def entry(name, typ, syn, main, subs, mega=False):
    e = {"name": name, "type": TYPE_NAME[typ], "rarity": RARITY, "level": LEVEL,
         "synergy": syn, "mainStat": main,
         "subStats": [{"key": k, "value": v} for k, v in subs]}
    if mega:
        e["mega"] = True
    return e


def full_set(prefix, syn, mains_key, subs, n):
    m = MAINS[mains_key]
    for i in range(1, n + 1):
        entries.append(entry(f"{prefix} {i} Necklace", NECKLACE, syn, m[NECKLACE], subs))
        entries.append(entry(f"{prefix} {i} Bracelet", BRACELET, syn, m[BRACELET], subs))
        entries.append(entry(f"{prefix} {i} Ring A", RING, syn, m[RING][0], subs))
        entries.append(entry(f"{prefix} {i} Ring B", RING, syn, m[RING][1], subs))
        entries.append(entry(f"{prefix} {i} Earring", EARRING, syn, m[EARRING], subs))


def covenant_set(prefix, syn, subs, n):
    """User-defined Covenant set = 1 Necklace, 1 Bracelet, 1 Ring, 2 Earrings."""
    m = MAINS["SPELL"]
    for i in range(1, n + 1):
        entries.append(entry(f"{prefix} {i} Necklace", NECKLACE, syn, m[NECKLACE], subs))
        entries.append(entry(f"{prefix} {i} Bracelet", BRACELET, syn, m[BRACELET], subs))
        entries.append(entry(f"{prefix} {i} Ring A", RING, syn, m[RING][0], subs))
        entries.append(entry(f"{prefix} {i} Earring A", EARRING, syn, m[EARRING], subs))
        entries.append(entry(f"{prefix} {i} Earring B", EARRING, syn, m[EARRING], subs))


def rings(prefix, syn, mains_key, subs, n):
    m = MAINS[mains_key]
    for i in range(1, n // 2 + 1):
        entries.append(entry(f"{prefix} Ring AtkSpd {i}", RING, syn, m[RING][0], subs))
    for i in range(1, n - n // 2 + 1):
        entries.append(entry(f"{prefix} Ring Hp {i}", RING, syn, m[RING][1], subs))


# ---- R1: 5 Bracelet + 5 Necklace + 5 Earring of Ocean (script stats) --------
OCEAN = 3
ocean_subs = [("BaseDefDen", 26.0), ("BaseDef", 4.0)]
m_oca = MAINS["GUARD"]
for i in range(1, 6):
    entries.append(entry(f"Ocean {i} Necklace", NECKLACE, OCEAN, m_oca[NECKLACE], ocean_subs))
    entries.append(entry(f"Ocean {i} Bracelet", BRACELET, OCEAN, m_oca[BRACELET], ocean_subs))
    entries.append(entry(f"Ocean {i} Earring", EARRING, OCEAN, m_oca[EARRING], ocean_subs))
# ---- R2: 4 Barbarian rings, SS sub = Guard (BaseDefDen) instead of SpecialDmg
BARBARIAN = 5
rings("Barbarian Guard", BARBARIAN, "SPECIAL",
      [("BaseDefDen", 26.0), ("AtkPer", 4.0)], 4)

# ---- R3: 6 full Steel sets, subs = A phys DEF (max 18) + B spell DEF (fills to 12)
STEEL = 0
steel_ab = [("BaseDef", pair(18.0)[0]), ("BaseMDef", pair(18.0)[1])]
full_set("Steel AB", STEEL, "TANK", steel_ab, 6)

# ---- R4: 4 Covenant sets (1 neck / 1 brace / 1 ring / 2 earrings),
#          subs = S spell crit dmg (max 22) + C spell crit chance (fills to 8)
COVENANT = 7
covenant_sc = [("BaseMCriticalDamageMul", pair(22.0)[0]), ("BaseMCriticalProb", pair(22.0)[1])]
covenant_set("Covenant SC", COVENANT, covenant_sc, 4)

# ---- R5: 4 Covenant rings, SS sub = Guard instead of spell crit dmg
rings("Covenant Guard", COVENANT, "SPELL",
      [("BaseDefDen", 26.0), ("MAtkPer", 4.0)], 4)

# ---- R6: 4 full Barbarian sets (script stats)
full_set("Barbarian", BARBARIAN, "SPECIAL",
         [("BaseSpecialDamageMul", 26.0), ("AtkPer", 4.0)], 4)

# ---- R7: 2 full Fear ("fearful") sets (script stats)
FEAR = 1
full_set("Fear", FEAR, "MENACE", [("BaseDefPen", 26.0), ("HpPer", 4.0)], 2)

# ---- R8: 2 full Ocean sets (script stats)
full_set("Ocean", OCEAN, "GUARD", ocean_subs, 2)

# ---- R9: 2 full Ascension sets (script stats)
ASCENSION = 12
full_set("Ascension", ASCENSION, "GUARD",
         [("BaseDefDen", 26.0), ("BaseDef", 4.0)], 2)

# ---- R10: 2 full Fatality sets, D sub = spell crit chance (was AtkPer)
FATALITY = 11
full_set("Fatality", FATALITY, "SPECIAL",
         [("BaseSpecialDamageMul", 26.0), ("BaseMCriticalProb", 4.0)], 2)

# ---- R11: 3 full Moonlight sets, subs = A phys crit dmg (max 18) + B phys crit chance (fills to 12)
MOONLIGHT = 9
moonlight_ab = [("BaseCriticalDamageMul", pair(18.0)[0]), ("BaseCriticalProb", pair(18.0)[1])]
full_set("Moonlight AB", MOONLIGHT, "CRIT", moonlight_ab, 3)

# ---- R12: 2 Ascension rings, main Guard, subs = A Guard (max 18) + B spell crit chance (fills to 12)
asc_rings_subs = [("BaseDefDen", pair(18.0)[0]), ("BaseMCriticalProb", pair(18.0)[1])]
for i in range(1, 3):
    entries.append(entry(f"Ascension Guard Ring {i}", RING, ASCENSION,
                         "BaseDefDen", asc_rings_subs))

# ---- R13: Eternity 1 Bracelet + 1 Necklace + 2 Earrings (earring main = spell
#           crit dmg), subs = A Guard + B spell crit chance
ETERNITY = 8
m_et = MAINS["GUARD_M"]
et_subs = asc_rings_subs
entries.append(entry("Eternity Bracelet", BRACELET, ETERNITY, m_et[BRACELET], et_subs))
entries.append(entry("Eternity Necklace", NECKLACE, ETERNITY, m_et[NECKLACE], et_subs))
entries.append(entry("Eternity Earring 1", EARRING, ETERNITY, "BaseMCriticalDamageMul", et_subs))
entries.append(entry("Eternity Earring 2", EARRING, ETERNITY, "BaseMCriticalDamageMul", et_subs))

# ---- R14: "MEGA 1000" experimental over-power set (test only) ---------------
#          Sub-stat wire values are literal 1000.0 (score 1000 - far past the
#          26.5 grade cutoff, so the client HIDES the badge). This is NOT a
#          legal roll: it deliberately bypasses the SS ceiling. The main stat
#          has NO value field on the wire (it scales with the accessory level),
#          so it stays the normal level-20 max - only sub-stats go to 1000.
MEGA = 9  # Moonlight synergy
mega_subs = [("AtkPer", 1000.0), ("HpPer", 1000.0)]
entries.append(entry("MEGA 1000 Necklace", NECKLACE, MEGA, "AtkPer", mega_subs, mega=True))
entries.append(entry("MEGA 1000 Ring", RING, MEGA, "AttackSpeedPer", mega_subs, mega=True))
entries.append(entry("MEGA 1000 Bracelet", BRACELET, MEGA, "BaseDef", mega_subs, mega=True))
entries.append(entry("MEGA 1000 Earring", EARRING, MEGA, "BaseCriticalDamageMul", mega_subs, mega=True))

# ---- validate against the real game rules + write ---------------------------
out = {"include_builtin": True, "accessories": entries}
out_path = ROOT / "data" / "admin_accessories.json"
out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {len(entries)} custom accessories -> {out_path}")
# sanity: every entry must pass our own validator
from dashboard import _validate_admin_accessory  # noqa: E402
for e in entries:
    _validate_admin_accessory(e)
print("all entries passed game-rule validation")
