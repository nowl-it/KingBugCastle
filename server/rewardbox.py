"""Open a reward box from RewardBoxInventoryData.xml into concrete rewards.

Reward boxes are the game's gift wrapper: mail, missions, shops and events all
hand out `InventoryItem` ids that are really boxes, and `/player/use-reward-box-
inventory-item` is what turns one into its contents. Without this the boxes pile
up in the inventory and cannot be opened, which is what the server did before.

Three box types, from `<Type>`:

  Fixable     every listed reward, always.
  Probable    `RewardCount` weighted draws (`Prob`), with replacement.
  Selectable  the player picks; the request carries a `selectIdx` bool[].

`Count` may be absent, in which case the reward rolls `Min`..`Max` instead.

Accessory rewards come in two shapes. `FixedAccessory` names a
FixedAccessoryPresets.xml id and is fully specified (an `Inherit` attribute
copies another preset's body - one level, no chains). `Accessory` gives only
synergy/rarity/type/main stat, so the sub-stats are rolled here against the same
AccessoryConstants.xml budget grant_accessories.py asserts on: sub-stat slots and
the shared upgrade pool are per rarity, and both sub-stats draw from ONE pool.

    python3 rewardbox.py     # self-check over every box in the XML
"""
import random
import xml.etree.ElementTree as ET
from pathlib import Path

from grant_accessories import rolls_for

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

# Type ids follow the order of AccessoryTypeInformation in AccessoryConstants.xml.
ACC_TYPE_IDS = {"Necklace": 1, "Bracelet": 2, "Ring": 3, "Earring": 4}
# Section names in AccessoryLevelEvent. Only "Special" appears in the reward data
# today, but the other two cost nothing to support.
ACC_RARITY_IDS = {"Common": 1, "Rare": 2, "Special": 3}

# Reward types that name an inventory row directly, so `ID` is an InventoryItems.xml
# id and the reward collapses to _grant_reward's "Item". `Key` is NOT one of them: it
# names a ShopItem whose <KeyItem> is the inventory row (ShopItem 370 -> item 380), so
# it stays a "Key" here and server.py resolves it through missions.key_item_for().
# Accessory and treasure types are handled separately because they carry a payload.
_ITEMISH = {"InventoryItem": "Item", "UnitExpItem": "Item", "UnitSoulItem": "Item"}

_cache = {}


def _root(xml_dir, name):
    key = (str(xml_dir), name)
    if key not in _cache:
        _cache[key] = ET.parse(Path(xml_dir) / name).getroot()
    return _cache[key]


def _acc_constants(xml_dir):
    """(sub-stat slots, shared score budget, per-score units, legal main stats) by rarity."""
    key = ("acc", str(xml_dir))
    if key in _cache:
        return _cache[key]
    root = _root(xml_dir, "AccessoryConstants.xml")
    units = {}
    for s in root.find("SubStatInformation"):
        stat = s.findtext("StatTypeStr")
        units[stat] = float(s.findtext("ValuePerScore") or s.findtext("ValueByScore") or 1)
    per_rarity = {}
    for section in root.find("AccessoryLevelEvent"):
        slots = budget = 0
        for e in section.findall("Event"):
            n = int(e.get("Value"))
            pt = e.find("PercentageTable")
            best = max((float(p.get("Score")) for p in pt), default=0.0) if pt is not None else 0.0
            if e.get("Type") == "UnlockSlot":
                slots += n
            budget += n * best
        per_rarity[section.tag] = (slots, budget)
    mains = {i + 1: t.findtext("MainStats").split(",")
             for i, t in enumerate(root.find("AccessoryTypeInformation"))}
    _cache[key] = (per_rarity, units, mains)
    return _cache[key]


def _presets(xml_dir):
    """FixedAccessoryPresets.xml by id, with `Inherit` resolved."""
    key = ("preset", str(xml_dir))
    if key in _cache:
        return _cache[key]
    by_id = {p.get("ID"): p for p in _root(xml_dir, "FixedAccessoryPresets.xml")
             .findall("FixedAccessoryPreset")}
    out = {}
    for pid, p in by_id.items():
        src = by_id.get(p.get("Inherit"), p) if p.get("Inherit") else p
        out[int(pid)] = src
    _cache[key] = out
    return out


def load_boxes(xml_dir=DEFAULT_XML):
    """box id -> {type, count, rewards[]}. Rewards keep their raw XML attributes."""
    key = ("boxes", str(xml_dir))
    if key in _cache:
        return _cache[key]
    out = {}
    for b in _root(xml_dir, "RewardBoxInventoryData.xml"):
        if b.tag != "RewardBoxInventoryData":
            continue
        out[int(b.get("ID"))] = {
            "type": b.findtext("Type") or "Fixable",
            "count": int(b.findtext("RewardCount") or 0),
            "rewards": [dict(r.attrib) for r in b.iter("Reward")],
        }
    _cache[key] = out
    return out


def make_fixed_accessory(preset_id, inst_id, xml_dir=DEFAULT_XML, now=""):
    """Build an AccessoryModel-shaped dict from a FixedAccessoryPresets entry.

    Mirrors load_corruption_accessories() in server.py: the client renders name,
    stats and grade off data.mainStat + data.subStats, and off the parallel
    subStats/subStatScores lists - a fabricated template with an invalid main stat
    renders as garbage, so everything here comes from the preset."""
    p = _presets(xml_dir).get(int(preset_id))
    if p is None:
        return None
    _, units, _ = _acc_constants(xml_dir)
    rolls = [(s.get("Key"), float(s.get("Value"))) for s in p.findall("./SubStats/SubStat")]
    fb = p.find("FixedBonusSubStat")
    if fb is not None:
        rolls.append((fb.get("Key"), float(fb.get("Value"))))
    scores = {}
    for k, v in rolls:
        scores[k] = scores.get(k, 0.0) + v / units.get(k, 1)
    return {
        "id": inst_id, "accountId": 1, "unitId": 0, "slot": 0,
        "type": int(p.findtext("Type", "1")), "rarity": int(p.findtext("Rarity", "3")),
        "level": int(p.findtext("Level", "20")), "exp": 0,
        "synergy": int(p.findtext("Synergy", "0")), "state": 0,
        "data": {"mainStat": p.findtext("MainStat", "AtkPer"),
                 "subStats": [{"key": k, "value": v} for k, v in rolls]},
        "subStats": list(scores.keys()), "subStatScores": [round(s, 3) for s in scores.values()],
        "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
        "createdAt": now, "updatedAt": now,
        "usedThemeList": [], "isEarlyAccessModeTestAccessory": False,
    }


def roll_accessory(spec, inst_id, xml_dir=DEFAULT_XML, now="", rng=random):
    """Build an accessory from a `Type="Accessory"` reward's synergy/rarity/type/main.

    The reward only pins the main stat, so sub-stats are rolled: `slots` distinct
    stats sharing the rarity's upgrade pool, most of it on the first. Splitting the
    pool this way is what a real maxed item looks like - two big sub-stats cannot
    coexist, the pool is not per-slot (see grant_accessories.py)."""
    per_rarity, units, mains = _acc_constants(xml_dir)
    rarity_name = spec.get("AccRarity", "Special")
    slots, budget = per_rarity.get(rarity_name, (2, 30.0))
    typ = ACC_TYPE_IDS.get(spec.get("AccType", "Necklace"), 1)
    main = spec.get("AccMainStat") or mains[typ][0]
    # A main stat the type cannot roll makes the client render an empty name.
    if main not in mains[typ]:
        main = mains[typ][0]
    pool = [s for s in units if s != main] or list(units)
    keys = rng.sample(pool, min(slots, len(pool)))
    # Everything the pool allows onto the first sub-stat, the unlock roll onto the
    # rest - the best-in-slot shape. 4 is the largest single upgrade roll.
    scores = [max(budget - 4.0 * (len(keys) - 1), 4.0)] + [4.0] * (len(keys) - 1)
    rolls = []
    for k, sc in zip(keys, scores):
        rolls += [{"key": k, "value": v} for v in rolls_for(sc, units.get(k, 1))]
    return {
        "id": inst_id, "accountId": 1, "unitId": 0, "slot": 0,
        "type": typ, "rarity": ACC_RARITY_IDS.get(rarity_name, 3),
        "level": 20, "exp": 0,
        "synergy": int(spec.get("AccSynergy", 0)), "state": 0,
        "data": {"mainStat": main, "subStats": rolls},
        "subStats": keys, "subStatScores": [round(s, 3) for s in scores],
        "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
        "createdAt": now, "updatedAt": now,
        "usedThemeList": [], "isEarlyAccessModeTestAccessory": False,
    }


def _count(r, rng):
    if r.get("Count") is not None:
        return int(r["Count"])
    lo, hi = int(r.get("Min", 1)), int(r.get("Max", 1))
    return rng.randint(min(lo, hi), max(lo, hi))


def pick_rewards(box, select_idx=None, rng=random):
    """Which of the box's reward entries the player actually gets."""
    rewards = box["rewards"]
    n = box["count"] or 1
    kind = box["type"]
    if kind == "Probable":
        weights = [float(r.get("Prob", 1)) for r in rewards]
        if sum(weights) <= 0:
            weights = [1.0] * len(rewards)
        return rng.choices(rewards, weights=weights, k=n)
    if kind == "Selectable":
        chosen = [rewards[i] for i, on in enumerate(select_idx or []) if on and i < len(rewards)]
        # No selection sent (or an out-of-range one): fall back to the first N so a
        # malformed request still yields something instead of an empty box.
        return chosen[:n] if chosen else rewards[:n]
    return rewards


def open_box(box_id, select_idx=None, xml_dir=DEFAULT_XML, next_id=1, now="", rng=random):
    """box id -> (rewards, accessories).

    `rewards` are {type, id, count} in _grant_reward's vocabulary, ready to hand
    straight back to the client as RewardResponseData. `accessories` are full
    AccessoryModel dicts to append to the player's list; each one also appears in
    `rewards` as type "Accessory" so the reward popup shows it."""
    box = load_boxes(xml_dir).get(int(box_id))
    if box is None:
        return [], []
    out, accs = [], []
    for r in pick_rewards(box, select_idx, rng):
        t = r.get("Type", "")
        if t in _ITEMISH:
            out.append({"type": "Item", "id": int(r.get("ID", 0)), "count": _count(r, rng)})
        elif t in ("Gold", "Cash", "Heart"):
            out.append({"type": t, "id": 0, "count": _count(r, rng)})
        elif t in ("Key", "CardOrSoul"):
            out.append({"type": t, "id": int(r.get("ID", 0)), "count": _count(r, rng)})
        elif t == "Treasure":
            # Display only - granting a treasure into state trips the client's
            # treasure panel invariants the same way artifacts do (see AGENTS.md).
            out.append({"type": "Treasure", "id": int(r.get("ID", 0)), "count": _count(r, rng)})
        elif t == "FixedAccessory":
            a = make_fixed_accessory(r.get("ID"), next_id + len(accs), xml_dir, now)
            if a:
                accs.append(a)
                out.append({"type": "Accessory", "id": a["id"], "count": 1})
        elif t == "Accessory":
            a = roll_accessory(r, next_id + len(accs), xml_dir, now, rng)
            accs.append(a)
            out.append({"type": "Accessory", "id": a["id"], "count": 1})
    return out, accs


def _self_check():
    boxes = load_boxes()
    assert boxes, "RewardBoxInventoryData.xml parsed to zero boxes"
    per_rarity, units, mains = _acc_constants(DEFAULT_XML)
    assert "Special" in per_rarity, f"no Special rarity in AccessoryLevelEvent: {list(per_rarity)}"
    slots, budget = per_rarity["Special"]
    rng = random.Random(1234)
    n_acc = n_rew = 0
    for bid, box in sorted(boxes.items()):
        assert box["type"] in ("Fixable", "Probable", "Selectable"), f"box {bid}: type {box['type']}"
        # Selectable with every slot ticked must still respect RewardCount.
        sel = [True] * len(box["rewards"])
        rewards, accs = open_box(bid, sel, next_id=1, rng=rng)
        assert rewards or not box["rewards"], f"box {bid} yielded nothing from {len(box['rewards'])} entries"
        if box["type"] in ("Probable", "Selectable"):
            assert len(rewards) <= max(box["count"], 1), \
                f"box {bid} ({box['type']}) returned {len(rewards)} > RewardCount {box['count']}"
        for r in rewards:
            assert r["count"] >= 1, f"box {bid}: reward {r} has a non-positive count"
        for a in accs:
            assert a["type"] in (1, 2, 3, 4), f"box {bid}: accessory type {a['type']}"
            assert a["data"]["mainStat"] in mains[a["type"]], \
                f"box {bid}: main stat {a['data']['mainStat']} is illegal for type {a['type']}"
            assert len(a["subStats"]) == len(a["subStatScores"])
            assert sum(a["subStatScores"]) <= budget + 1e-6 or a["rarity"] != 3, \
                f"box {bid}: sub-stat scores {a['subStatScores']} exceed the Special pool {budget}"
            # data.subStats must sum to the advertised score, else the tooltip and
            # the grade badge disagree.
            for k, sc in zip(a["subStats"], a["subStatScores"]):
                got = sum(s["value"] for s in a["data"]["subStats"] if s["key"] == k)
                assert abs(got / units.get(k, 1) - sc) < 0.01, \
                    f"box {bid}: {k} rolls sum to {got} but score says {sc}"
        n_acc += len(accs)
        n_rew += len(rewards)
    # A Probable box must be able to return different things across seeds.
    prob = [b for b, x in boxes.items() if x["type"] == "Probable" and len(x["rewards"]) > 1]
    if prob:
        seen = {tuple(sorted(r["id"] for r in open_box(prob[0], rng=random.Random(s))[0]))
                for s in range(20)}
        assert len(seen) > 1, f"Probable box {prob[0]} returned the same reward for 20 seeds"
    print(f"ok: {len(boxes)} boxes, {n_rew} rewards, {n_acc} accessories; "
          f"Special = {slots} slots / {budget} pool")


if __name__ == "__main__":
    _self_check()
