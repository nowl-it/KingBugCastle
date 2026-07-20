"""Grant a full best-in-slot accessory loadout for every synergy set.

13 sets x 5 pieces (Necklace, Bracelet, Ring, Ring, Earring) = 65 accessories,
rarity Special, level 20, one main stat and **two** sub-stats each, both at the
highest tier the client will actually draw.

Sub-stat slots are per rarity, from AccessoryLevelEvent in AccessoryConstants.xml:
Common 4, Rare 1, **Special 2**. The Common section is not a shared baseline - it
is Common's own schedule; reading it as one is how this first shipped with four.
SLOTS is asserted against the XML at run time so that mistake cannot come back.

**Grades.** AccessorySubStatGrade.Set does
`LowerBound(AccessorySubStatScoreRange, score)` -> index of the greatest threshold
<= score -> a Dictionary built in the cctor with keys 0..5 = D, C, B, A, S, SS.
Bands: 1=D, 4.5=C, 8.5=B, 13.5=A, 18.5=S, 22.5=SS. A score >= 26.5 gives index 6,
TryGetValue misses and the badge is HIDDEN - so 26.5 is a hard ceiling, not a tier.

**Budget.** The two sub-stats share one upgrade pool (AccessoryLevelEvent, rarity
Special): 2 unlock rolls x4 + 5 upgrades x4 + 1 upgradeHighest x2 = 30 total. Two
S sub-stats would need 18.5+18.5 = 37, which the game cannot produce. SCORES below
spends the pool the way a player chasing best-in-slot would: everything into one
stat (26 = SS, the max under the 26.5 ceiling), the other left at its unlock roll.
BUDGET is computed from the XML and asserted, so this cannot drift.

Rolls are legal values from IncreaseRandomValues (max 4, or 80 for the /20 stats),
so data.subStats sums to exactly the advertised score.

    python3 grant_accessories.py [--uid dev-0001] [--dry-run]
"""
import argparse, datetime, xml.etree.ElementTree as ET
from pathlib import Path

import playerdb

ROOT = Path(__file__).resolve().parent
XML = ROOT / "xml_live" / "AccessoryConstants.xml"

SCORES = (26.0, 4.0)         # per sub-stat: 26 = SS (max under the 26.5 cutoff), 4 = D
GRADES = [(22.5, "SS"), (18.5, "S"), (13.5, "A"), (8.5, "B"), (4.5, "C"), (1.0, "D")]
LEVEL, RARITY = 20, 3        # 20 = max level; 3 = Special, max of ResourceTreasure.Rarity

# Type ids follow the order of AccessoryTypeInformation in AccessoryConstants.xml.
NECKLACE, BRACELET, RING, EARRING = 1, 2, 3, 4
# 5 pieces, 2 of them rings. The two rings get different main stats where the
# type allows it, so the pair is not a duplicate.
LOADOUT = [(NECKLACE, 0), (BRACELET, 0), (RING, 0), (RING, 1), (EARRING, 0)]

# Main stats a type can roll (AccessoryTypeInformation):
#   Necklace AtkPer|MAtkPer   Bracelet BaseDef|BaseMDef
#   Ring     HpPer|AttackSpeedPer|BaseDefPen|BaseDefDen
#   Earring  BaseCriticalDamageMul|BaseMCriticalDamageMul|BaseDef|BaseMDef|BaseSpecialDamageMul
#
# NOTE the two easily-misread keys (Strings: DefPen / DefDen):
#   BaseDefPen = **Menace** (Uy hiep) - the stat the Fear / Suppression sets scale
#   BaseDefDen = **Guard**  (Ho ve)   - the stat the Ocean / Eternity sets scale
# Neither is armour penetration. Both are also legal SUB-stats.
#
# A Necklace can only ever roll attack, so tank sets carry a dead necklace main -
# that is the game's constraint, not a choice here.
TANK    = {NECKLACE: "AtkPer",  BRACELET: "BaseDef",  RING: ["HpPer", "HpPer"],                   EARRING: "BaseDef"}
MENACE  = {NECKLACE: "AtkPer",  BRACELET: "BaseDef",  RING: ["BaseDefPen", "BaseDefPen"],         EARRING: "BaseDef"}
GUARD   = {NECKLACE: "AtkPer",  BRACELET: "BaseDef",  RING: ["BaseDefDen", "BaseDefDen"],         EARRING: "BaseDef"}
GUARD_M = {NECKLACE: "MAtkPer", BRACELET: "BaseMDef", RING: ["BaseDefDen", "BaseDefDen"],         EARRING: "BaseMDef"}
CRIT    = {NECKLACE: "AtkPer",  BRACELET: "BaseDef",  RING: ["AttackSpeedPer", "HpPer"],          EARRING: "BaseCriticalDamageMul"}
SPELL   = {NECKLACE: "MAtkPer", BRACELET: "BaseMDef", RING: ["AttackSpeedPer", "HpPer"],          EARRING: "BaseMCriticalDamageMul"}
SPECIAL = {NECKLACE: "AtkPer",  BRACELET: "BaseDef",  RING: ["AttackSpeedPer", "HpPer"],          EARRING: "BaseSpecialDamageMul"}
HASTE   = {NECKLACE: "AtkPer",  BRACELET: "BaseDef",  RING: ["AttackSpeedPer", "AttackSpeedPer"], EARRING: "BaseSpecialDamageMul"}

# synergy id -> (name, main stats, [SS sub-stat, D sub-stat], why)
# The first sub-stat gets SCORES[0] (26 = SS), the second SCORES[1] (4 = D).
# Rule: put SS on the stat the set's own bonus MULTIPLIES; never spend on a stat
# the set already grants, and never on crit for the sets that reduce crit.
SETS = {
    0:  ("Steel",       TANK,     ["BaseDef", "HpPer"],
         "5pc scales final DEF per tier -> DEF is what multiplies"),
    1:  ("Fear",        MENACE,   ["BaseDefPen", "HpPer"],
         "Menace set: 2pc/3pc/5pc all scale Menace = BaseDefPen"),
    2:  ("Sharpness",   CRIT,     ["BaseCriticalDamageMul", "BaseCriticalProb"],
         "5pc already grants CRIT chance -> damage scales harder"),
    3:  ("Ocean",       GUARD,    ["BaseDefDen", "BaseDef"],
         "Guard set: 5pc converts base Guard into DEF -> Guard = BaseDefDen"),
    4:  ("Wind",        HASTE,    ["BaseSpecialDamageMul", "AtkPer"],
         "3pc REDUCES crit chance and pays in special damage -> no crit stats"),
    5:  ("Barbarian",   SPECIAL,  ["BaseSpecialDamageMul", "AtkPer"],
         "5pc REDUCES crit chance by 40% -> crit stats would be wasted"),
    6:  ("Adamant",     TANK,     ["HpPer", "BaseDef"],
         "2pc final HP, 5pc shield scales off Max HP -> HP is the multiplier"),
    7:  ("Covenant",    SPELL,    ["BaseMCriticalDamageMul", "MAtkPer"],
         "3pc already grants +50% spell CRIT chance -> spend on spell CRIT damage"),
    8:  ("Eternity",    GUARD_M,  ["BaseDefDen", "HpPer"],
         "healer: 3pc scales final Guard; 2pc cuts ATK/Spell 70% so offence is dead"),
    9:  ("Moonlight",   CRIT,     ["BaseCriticalDamageMul", "AtkPer"],
         "5pc grants phys CRIT chance, 3pc scales CRIT damage by Range"),
    10: ("Suppression", MENACE,   ["BaseDefPen", "HpPer"],
         "Menace set: 2pc/3pc/5pc all scale Menace = BaseDefPen"),
    11: ("Fatality",    SPECIAL,  ["BaseSpecialDamageMul", "AtkPer"],
         "3pc can cut final CRIT damage -> special damage only"),
    12: ("Ascension",   GUARD,    ["BaseDefDen", "BaseDef"],
         "support set - Guard main stat; 2pc amplifies sub-stats by 30%"),
}


def level_events(rarity):
    """(sub-stat slots, total score the upgrade pool can add) for this rarity.

    Both sub-stats draw from ONE pool, so the cap is on their sum, not each."""
    section = {1: "Common", 2: "Rare", 3: "Special"}[rarity]
    ev = ET.parse(XML).getroot().find("AccessoryLevelEvent").find(section)
    slots = budget = 0
    for e in ev.findall("Event"):
        n = int(e.get("Value"))
        pt = e.find("PercentageTable")
        best = max((float(p.get("Score")) for p in pt), default=0.0) if pt is not None else 0.0
        if e.get("Type") == "UnlockSlot":
            slots += n
        budget += n * best
    return slots, budget


def grade(score):
    return next((g for lo, g in GRADES if score >= lo), None)


def allowed_mains():
    """type id -> main stats that type may roll (AccessoryTypeInformation order)."""
    types = ET.parse(XML).getroot().find("AccessoryTypeInformation")
    return {i + 1: t.findtext("MainStats").split(",") for i, t in enumerate(types)}


def per_score():
    """stat -> value units per 1 score point (ValuePerScore, else ValueByScore=1)."""
    root = ET.parse(XML).getroot()
    out = {}
    for s in root.find("SubStatInformation"):
        key = s.findtext("StatTypeStr")
        out[key] = float(s.findtext("ValuePerScore") or s.findtext("ValueByScore") or 1)
    return out


def rolls_for(score, unit):
    """Split `score` into individual rolls that are legal IncreaseRandomValues.

    Max roll is 4 score (value 4, or 80 where a point of score costs 20 units), so
    22.0 becomes 5x4 + 1x2 - the same shape a maxed-out real accessory has."""
    out, left = [], score
    while left > 4:
        out.append(4.0 * unit)
        left -= 4
    if left > 0:
        out.append(round(left * unit, 3))
    return out


def build(uid):
    slots, budget = level_events(RARITY)
    for syn, (name, _m, subs, _why) in SETS.items():
        assert len(subs) == slots, \
            f"set {syn} {name} has {len(subs)} sub-stats but rarity {RARITY} unlocks {slots} slots"
        assert len(set(subs)) == len(subs), f"set {syn} {name} repeats a sub-stat"
    assert len(SCORES) == slots, f"SCORES has {len(SCORES)} entries, rarity {RARITY} unlocks {slots}"
    assert sum(SCORES) <= budget, \
        f"SCORES sum to {sum(SCORES)} but the shared upgrade pool caps at {budget}"
    assert all(grade(s) for s in SCORES), f"a score in {SCORES} falls outside the client's grade dict"
    legal = allowed_mains()
    for syn, (name, mains, _s, _w) in SETS.items():
        for typ, opts in ((NECKLACE, None), (BRACELET, None), (RING, None), (EARRING, None)):
            picks = mains[typ] if isinstance(mains[typ], list) else [mains[typ]]
            for m in picks:
                assert m in legal[typ], f"set {syn} {name}: {m} is not a legal main stat for type {typ}"
    units = per_score()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    accs, next_id = [], 1
    for synergy, (_name, mains, subs, _why) in sorted(SETS.items()):
        for typ, variant in LOADOUT:
            main = mains[typ]
            main = main[variant] if isinstance(main, list) else main
            rolls = []
            for key, score in zip(subs, SCORES):
                rolls += [{"key": key, "value": v} for v in rolls_for(score, units[key])]
            accs.append({
                "id": next_id, "accountId": 1, "unitId": 0, "slot": 0,
                "type": typ, "rarity": RARITY, "level": LEVEL, "exp": 0,
                "synergy": synergy, "state": 0,
                "data": {"mainStat": main, "subStats": rolls},
                "subStats": list(subs),
                "subStatScores": list(SCORES),
                "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
                "createdAt": now, "updatedAt": now,
                "usedThemeList": [], "isEarlyAccessModeTestAccessory": False,
            })
            next_id += 1
    return accs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uid", default=None, help="player uid (default: the active player)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    uid = args.uid or playerdb.active()
    accs = build(uid)

    slots, budget = level_events(RARITY)
    print(f"{len(accs)} accessories for {uid}: {len(SETS)} sets x {len(LOADOUT)} (2 rings), "
          f"rarity {RARITY}, level {LEVEL}")
    print(f"  sub-stats: " + ", ".join(f"{s} [{grade(s)}]" for s in SCORES)
          + f"  (sum {sum(SCORES)} / pool {budget})")
    if args.dry_run:
        for syn, (name, mains, subs, why) in sorted(SETS.items()):
            picks = [mains[t][v] if isinstance(mains[t], list) else mains[t] for t, v in LOADOUT]
            print(f"  {syn:2} {name:12} {subs[0]:24}[SS] + {subs[1]:20}[D]")
            print(f"     mains: {', '.join(picks)}")
            print(f"     why:   {why}")
        return

    with playerdb.write_lock():          # same lock the request middleware holds
        st = playerdb.load(uid)
        if st is None:
            raise SystemExit(f"no such player: {uid}")
        st["accessories"] = accs
        playerdb.save(uid, st)
    print(f"granted -> {playerdb.DB_PATH}")


if __name__ == "__main__":
    main()
