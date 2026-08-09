"""Story-mode Challenge: the season's reward track.

`/story-mode/challenge/info`, `/reward` and `/daily-reward` fell through to the
auto-generated model, so the Challenge panel showed an empty track and neither
button paid out. This is the mode Season 71 added the boss unit 30000000 for.

ChallengeSeasons.xml keeps the reward tables on entry ID 0 and gives each season a
thin `Inherit="0"` body carrying only what differs (stage ids, unit count, enemy
stat scaling). So "the current season" is the highest numbered entry, and its reward
track is inherited.

Two mission kinds drive the track:

  ClearDifficulty    reach difficulty N (N runs 1..21, odd numbers)
  ClearBattleIndex   clear the Nth battle of the season

    python3 challenge.py     # self-check
"""
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XML = ROOT / "xml_live"

# Reward Type -> inventory item. ChallengeToken is 2014 (챌린지 토큰); a Key names a
# ShopItem the way the mission and invasion rewards do, and is resolved by the caller.
ITEM_REWARDS = {"ChallengeToken": 2014}

_cache = {}


def _root(xml_dir):
    key = str(xml_dir)
    if key not in _cache:
        _cache[key] = ET.parse(Path(xml_dir) / "ChallengeSeasons.xml").getroot()
    return _cache[key]


def seasons(xml_dir=DEFAULT_XML):
    return {int(c.get("ID")): c for c in _root(xml_dir) if c.get("ID")}


def current_season(xml_dir=DEFAULT_XML):
    """The highest numbered season. Entry 0 is the shared base, not a season."""
    ids = [i for i in seasons(xml_dir) if i > 0]
    return max(ids) if ids else 0


def _inherited(sid, tag, xml_dir):
    """A season's own node for `tag`, else the one it inherits (one level, no chains)."""
    all_s = seasons(xml_dir)
    el = all_s.get(sid)
    if el is None:
        return None
    node = el.find(tag)
    if node is not None:
        return node
    parent = all_s.get(int(el.get("Inherit", 0)))
    return parent.find(tag) if parent is not None else None


def _rewards(node):
    out = []
    for r in node.findall("Reward"):
        t = r.get("Type") or ""
        cnt = int(r.get("Count", 1))
        if t == "InventoryItem":
            out.append({"type": "Item", "id": int(r.get("ID", 0)), "count": cnt})
        elif t in ITEM_REWARDS:
            out.append({"type": "Item", "id": ITEM_REWARDS[t], "count": cnt})
        elif t == "Key":
            out.append({"type": "Key", "id": int(r.get("ID", 0)), "count": cnt})
        elif t in ("Gold", "Cash", "Heart"):
            out.append({"type": t, "id": 0, "count": cnt})
        else:
            out.append({"type": t, "id": int(r.get("ID", 0)), "count": cnt})
    return out


def track(sid=None, xml_dir=DEFAULT_XML):
    """The season's mission reward track, in the order rewardStates indexes it.

    The order is the document order of MissionRewards - the client's rewardStates is
    a parallel List<int>, so re-sorting here would silently misalign every claim."""
    sid = current_season(xml_dir) if sid is None else sid
    node = _inherited(sid, "MissionRewards", xml_dir)
    if node is None:
        return []
    return [{"kind": m.get("Type"), "value": int(m.get("Value", 0)),
             "rewards": _rewards(m)}
            for m in node.findall("Mission")]


def daily_track(sid=None, xml_dir=DEFAULT_XML):
    """difficulty -> rewards, for the once-a-day claim."""
    sid = current_season(xml_dir) if sid is None else sid
    node = _inherited(sid, "DailyRewards", xml_dir)
    if node is None:
        return {}
    return {int(d.get("Difficulty", 0)): _rewards(d) for d in node.findall("DailyReward")}


def unlocked_difficulty(sid=None, xml_dir=DEFAULT_XML):
    sid = current_season(xml_dir) if sid is None else sid
    node = _inherited(sid, "DefaultUnlockDifficulty", xml_dir)
    return int(node.text) if node is not None and node.text else 1


def earned(entry, best_difficulty, cleared_battles):
    """Whether the player has met this track entry's condition."""
    if entry["kind"] == "ClearDifficulty":
        return best_difficulty >= entry["value"]
    if entry["kind"] == "ClearBattleIndex":
        return cleared_battles > entry["value"]
    return False


def _self_check():
    sid = current_season()
    assert sid > 0, "no numbered challenge season found"
    t = track(sid)
    assert t, f"season {sid} has an empty reward track"
    assert unlocked_difficulty(sid) >= 1
    kinds = {e["kind"] for e in t}
    assert kinds <= {"ClearDifficulty", "ClearBattleIndex"}, f"unknown mission kinds {kinds}"
    for e in t:
        assert e["rewards"], f"track entry {e['kind']}={e['value']} pays nothing"
        for r in e["rewards"]:
            assert r["count"] >= 1, f"{e} has a reward with count < 1"
            assert r["type"] != "ChallengeToken", "ChallengeToken was not mapped to an item"
    # Nothing on the track may be earned by a player who has cleared nothing, or the
    # panel pays out its whole season on first open.
    assert not [e for e in t if earned(e, 0, 0)], \
        "some track entries are earned at zero progress"
    # The top entry must be reachable: a track whose highest ClearDifficulty exceeds
    # the unlocked cap can never be completed.
    top = max((e["value"] for e in t if e["kind"] == "ClearDifficulty"), default=0)
    assert all(earned(e, top, len(t)) for e in t), \
        f"some entries stay unearned even at difficulty {top}"
    daily = daily_track(sid)
    assert daily, f"season {sid} has no daily rewards"
    assert all(v for v in daily.values()), "a daily difficulty pays nothing"
    print(f"ok: season {sid}, {len(t)} track entries ({sorted(kinds)}), "
          f"unlock cap {unlocked_difficulty(sid)}, {len(daily)} daily tiers")


if __name__ == "__main__":
    _self_check()
