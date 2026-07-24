"""Missions: the list the client shows, and how far along each one is.

`/mission` used to answer `{"missions": []}`, so the mission tab was empty and its
claim button did nothing. Missions.xml has 2751 entries across every mission system
the game has ever run.

**What this does and does not simulate.** A mission's Condition is one of 167 kinds,
and most of them describe things that happen inside the client's battle simulation
("win with card X", "reach population 7") which never reach the server at all. So
progress is evaluated from the two things the server genuinely knows:

  * player state - hero levels, castle level, accessories, cleared themes
  * counters this server increments itself, in the routes it already owns
    (/game/complete, /shop, /post/receive)

A condition outside that set evaluates to 0 and its mission stays unclaimable rather
than being silently marked complete. That is the honest failure: a mission tab that
under-reports is recoverable (the dashboard can set a counter), one that hands out
every reward in the game on first login is not.

    python3 missions.py     # self-check + a breakdown of what is observable
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

# Mission systems the lobby's mission tab shows. Excluded: PassOld/RepeatedOld (dead
# predecessors kept for old saves), Pass/MissionPoint (season-pass tracks, served by
# /pass), Event (each needs its own live event to exist), Shop/Unit/Challenge (driven
# by their own panels, not this list).
VISIBLE_TYPES = {"Normal", "Repeated", "Beginner", "Starter"}

# Reward Type -> the inventory item it is really n of. Ids pinned by NameComment in
# InventoryItems.xml: 110 경험의 서, 130 왕의 증표, 2000 초보자 임무 코인,
# 2001 스킨 토큰, 2002 아레나 토큰, 2003 연맹전 토큰, 2004 이벤트 토큰,
# 2008/2009/2010 해변축제 브론즈/실버/골드 토큰.
ITEM_REWARDS = {
    "UnitExpItem": 110,
    "UnitSoulItem": 130,
    "BeginnerMissionCoin": 2000,
    "SkinToken": 2001,
    "Token_SKIN": 2001,
    "ArenaToken": 2002,
    "Token_ARENA": 2002,
    "Token_COLOSSEUM": 2002,
    "ClanToken": 2003,
    "Token_SEASONAL_EVENT": 2004,
    "TerritoryTycoonToken_Bronze": 2008,
    "TerritoryTycoonToken_Silver": 2009,
    "TerritoryTycoonToken_Gold": 2010,
}

# Reported to the client's reward popup but deliberately not written into state.
# Artifacts and treasures follow the existing _grant_reward policy (a half-specified
# artifact trips ArtifactOptionUI); the rest are progression points and cosmetics with
# no inventory row to put them in, so inventing one would corrupt the save.
DISPLAY_ONLY = {
    "Artifact", "Treasure", "Treasure_Special", "ArtifactDust", "UnitExp_10",
    "NewUnitGachaItem", "Flag", "NameTag", "TowerTicket", "PassPoint",
    "PassPoint_FifthHalfYear", "MissionPoint_Daily", "MissionPoint_Weekly",
    "ColosseumOpenMissionPoint",
}


def reward_attrs(el):
    """A reward written the `Type`/`ID`/`Count` way, in _grant_reward's vocabulary.

    Missions.xml is the odd one out (Value/Amount, see rewards_of); every other
    table - babel floors, colosseum tiers, journey, the anniversary event - writes
    the count in `Count` and the id in `ID`. Kept here beside ITEM_REWARDS so the
    token-to-inventory-row mapping has one home rather than a copy per table."""
    t = el.get("Type") or ""
    rid = int(el.get("ID", 0) or 0)
    count = int(float(el.get("Count", 1) or 1))
    if t in ITEM_REWARDS:
        return {"type": "Item", "id": ITEM_REWARDS[t], "count": count}
    if t == "InventoryItem":
        return {"type": "Item", "id": rid, "count": count}
    return {"type": t, "id": rid, "count": count}

_cache = {}


def load(xml_dir=DEFAULT_XML):
    """{mission id: element} for the mission systems the lobby shows."""
    key = str(xml_dir)
    if key not in _cache:
        root = ET.parse(Path(xml_dir) / "Missions.xml").getroot()
        _cache[key] = {int(m.get("ID")): m for m in root
                       if m.get("ID") and (m.findtext("Type") or "") in VISIBLE_TYPES}
    return _cache[key]


def goal_value(m):
    c = m.find("Condition")
    try:
        return int(c.get("Value"))
    except (AttributeError, TypeError, ValueError):
        return 1


def condition(m):
    c = m.find("Condition")
    return (c.get("Type") or "") if c is not None else ""


def _suffix_int(cond, prefix):
    """`ClearTheme_64` -> 64, and `Accessory_LvOver20` -> 20.

    The separator is optional because the XML uses both spellings: the theme
    conditions put an underscore before the number, the threshold ones
    (Accessory_LvOver20, CardCount_LvOver4) run it straight on. Requiring the
    underscore made every threshold condition silently unobservable."""
    m = re.fullmatch(re.escape(prefix) + r"_?(\d+)", cond)
    return int(m.group(1)) if m else None


def progress(m, st, counters):
    """How far the player is on this mission, from state and server-side counters.

    Anything this cannot see returns 0 - see the module docstring for why that is
    preferred over assuming completion."""
    cond = condition(m)
    cards = (st.get("cards") or {}).values()

    # Plain counters the server increments in the routes it owns.
    direct = {
        "ClearGame": "clearGame",
        "PlayGame": "playGame",
        "UseGold": "useGold",
        "UseHeart": "useHeart",
        "UseArenaShop": "useArenaShop",
        "UseClanShop": "useClanShop",
        "UseEventShop": "useEventShop",
        "GachaUnit": "gachaUnit",
        "GachaTreasure": "gachaTreasure",
        "ArtifactGacha": "artifactGacha",
        "DailyLoginCount": "dailyLogin",
        "MissionClearCount": "missionClear",
        # Counted from the routes this server already handles, so they cost nothing
        # beyond one increment each and cover the largest remaining condition groups.
        "PlayArena": "playArena",
        "WinArena": "winArena",
        "ChargeHeart": "chargeHeart",
        "ArtifactReforge": "artifactReforge",
        "ArtifactMerge": "artifactMerge",
        "ArtifactDismantle": "artifactDismantle",
        "ArtifactPolish": "artifactPolish",
        "AccessoryDismantle": "accessoryDismantle",
        "LevelUpAccessory": "accessoryLevelUp",
        "ClanSupport": "clanSupport",
    }
    if cond in direct:
        return int(counters.get(direct[cond], 0))

    # Per-theme counters live in one dict so a new theme needs no new key.
    for prefix, bucket in (("ClearTheme", "clearTheme"), ("PlayTheme", "playTheme"),
                           ("Theme", "clearTheme")):
        n = _suffix_int(cond, prefix)
        if n is not None:
            return int((counters.get(bucket) or {}).get(str(n), 0))

    # Derived straight from the save.
    if cond == "CastleLevel":
        # 본성 (the main castle) is the player themself - its level IS the
        # account level, which is why these missions read off `level`.
        return int(st.get("castleLevel", st.get("level", 0)) or 0)
    n = _suffix_int(cond, "Level")
    if n is not None:
        return sum(1 for c in cards if c.get("level", 0) >= n)
    n = _suffix_int(cond, "CardCount_LvOver")
    if n is not None:
        return sum(1 for c in cards if c.get("level", 0) >= n)
    n = _suffix_int(cond, "Accessory_LvOver")
    if n is not None:
        return sum(1 for a in (st.get("accessories") or []) if a.get("level", 0) >= n)
    if cond == "CardCount":
        return len(cards)
    n = _suffix_int(cond, "CardCount_PotentialTier")
    if n is not None:
        return sum(1 for c in cards if c.get("potentialTier", 0) >= n)
    if cond == "SkinCount":
        return sum(len(c.get("skins") or []) for c in cards)
    if cond == "GetSpecialAccessory":
        # Rarity 3 is Special, the top rarity (see grant_accessories.py).
        return sum(1 for a in (st.get("accessories") or []) if a.get("rarity", 0) >= 3)
    if cond == "AccessoryCount":
        return len(st.get("accessories") or [])
    if cond == "TreasureCount":
        return len(st.get("treasures") or [])
    return 0


def observable(m):
    """Whether progress() can ever move this mission off zero."""
    dummy = {"cards": {"1": {"level": 99, "potentialTier": 9, "skins": [1]}},
             "accessories": [{"level": 99, "rarity": 3}],
             "treasures": [{}], "castleLevel": 99}
    counters = dict.fromkeys(
        ("clearGame", "playGame", "useGold", "useHeart", "useArenaShop", "useClanShop",
         "useEventShop", "gachaUnit", "gachaTreasure", "artifactGacha", "dailyLogin",
         "missionClear", "playArena", "winArena", "chargeHeart", "artifactReforge",
         "artifactMerge", "artifactDismantle", "artifactPolish", "accessoryDismantle",
         "accessoryLevelUp", "clanSupport"), 1)
    counters["clearTheme"] = counters["playTheme"] = {str(i): 1 for i in range(200)}
    return progress(m, dummy, counters) > 0


def to_model(m, st, counters, claimed, now="", until=""):
    goal = goal_value(m)
    value = progress(m, st, counters)
    return {
        "missionId": int(m.get("ID")),
        "value": min(value, goal),
        "goalValue": goal,
        "clear": int(m.get("ID")) in claimed or value >= goal,
        "createdAt": now,
        "untilAt": until,
    }


def listing(st, counters, claimed, now="", xml_dir=DEFAULT_XML):
    return [to_model(m, st, counters, claimed, now)
            for _, m in sorted(load(xml_dir).items())]


def rewards_of(m):
    """{type, id, count} per reward, in _grant_reward's vocabulary.

    The XML is inconsistent about which attribute carries the amount: InventoryItem
    puts the count in Value and the item in ID, Key puts a shop-item id in Value and
    the count in Amount, and the token rewards use Amount alone. Each case is read
    explicitly rather than through one guessed rule."""
    out = []
    for r in m.findall("Reward"):
        t = r.get("Type") or ""
        val = r.get("Value")
        amt = r.get("Amount")
        rid = r.get("ID")

        def _n(x, default=1):
            try:
                return int(float(x))
            except (TypeError, ValueError):
                return default

        if t in ("Gold", "Cash", "Heart"):
            out.append({"type": t, "id": 0, "count": _n(val)})
        elif t == "InventoryItem":
            out.append({"type": "Item", "id": _n(rid, 0), "count": _n(val)})
        elif t in ITEM_REWARDS:
            out.append({"type": "Item", "id": ITEM_REWARDS[t],
                        "count": _n(amt if amt is not None else val)})
        elif t == "Key":
            # Value names the ShopItem whose KeyItem this is; the count is in Amount.
            out.append({"type": "Key", "id": _n(val, 0), "count": _n(amt)})
        elif t in ("Card", "CardOrSoul"):
            out.append({"type": "CardOrSoul", "id": _n(rid if rid else val, 0), "count": 1})
        elif t == "CardSoul":
            out.append({"type": "UnitSoul", "id": _n(rid, 0), "count": _n(val)})
        elif t == "CardExp":
            out.append({"type": "CardExp", "id": _n(rid, 0), "count": _n(val)})
        elif t == "FixedAccessory":
            out.append({"type": "FixedAccessory", "id": _n(rid, 0), "count": _n(val)})
        elif t in DISPLAY_ONLY:
            out.append({"type": t, "id": _n(rid if rid else val, 0),
                        "count": _n(amt if amt is not None else val)})
        else:
            out.append({"type": t, "id": _n(rid, 0),
                        "count": _n(amt if amt is not None else val)})
    return out


def _key_index(xml_dir):
    key = ("keys", str(xml_dir))
    if key not in _cache:
        root = ET.parse(Path(xml_dir) / "ShopItems.xml").getroot()
        items, boxes = {}, {}
        for c in root:
            if not c.get("ID"):
                continue
            sid = int(c.get("ID"))
            if c.findtext("KeyItem"):
                items[sid] = int(c.findtext("KeyItem"))
            elif c.findtext("Type") == "ArtifactGacha" and c.findtext("GachaBoxIndex"):
                boxes[sid] = int(c.findtext("GachaBoxIndex"))
        _cache[key] = (items, boxes)
    return _cache[key]


def key_item_for(shop_item_id, xml_dir=DEFAULT_XML):
    """A `Key` reward names a ShopItem; the thing granted is that item's <KeyItem>."""
    return _key_index(xml_dir)[0].get(int(shop_item_id))


def artifact_box_for(shop_item_id, xml_dir=DEFAULT_XML):
    """The artifact boxes have no KeyItem - their keys are counted per box in
    ShopResponseModel.artifactBoxKey, indexed by <GachaBoxIndex>, not held as an
    inventory row. Returns that index, or None when this is not an artifact box."""
    return _key_index(xml_dir)[1].get(int(shop_item_id))


def _self_check():
    ms = load()
    assert ms, "no visible missions parsed"
    obs = [m for m in ms.values() if observable(m)]
    conds = {condition(m) for m in ms.values()}
    for m in ms.values():
        assert goal_value(m) >= 1, f"mission {m.get('ID')} has goal {goal_value(m)}"
        for r in rewards_of(m):
            assert r["count"] >= 1, f"mission {m.get('ID')}: reward {r} count < 1"
            if r["type"] in ("Item", "CardOrSoul", "UnitSoul", "CardExp", "FixedAccessory"):
                assert r["id"] > 0, f"mission {m.get('ID')}: {r['type']} with no id"
        assert rewards_of(m), f"mission {m.get('ID')} grants nothing"
    # An empty save must not have anything already complete, or first login pays out
    # the whole mission tab.
    empty = {"cards": {}, "accessories": []}
    done = [m for m in ms.values() if progress(m, empty, {}) >= goal_value(m)]
    assert not done, f"{len(done)} missions read as complete on an empty save: {done[:3]}"
    # A `Key` reward has to resolve to something - a KeyItem inventory row, or an
    # artifact box index - else it silently grants item 0.
    unresolved = [(int(m.get("ID")), r["id"]) for m in ms.values() for r in rewards_of(m)
                  if r["type"] == "Key"
                  and key_item_for(r["id"]) is None and artifact_box_for(r["id"]) is None]
    assert not unresolved, f"Key rewards naming an unresolvable shop item: {unresolved[:5]}"
    print(f"ok: {len(ms)} visible missions, {len(conds)} distinct conditions, "
          f"{len(obs)} ({100 * len(obs) // len(ms)}%) observable server-side")
    missing = sorted({condition(m) for m in ms.values() if not observable(m)})
    print(f"   not observable ({len(missing)} conditions): {', '.join(missing[:12])}"
          + (" ..." if len(missing) > 12 else ""))


if __name__ == "__main__":
    _self_check()
