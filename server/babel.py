"""Babel: the six towers.

`/babel` is the mode's only route and it answered an empty model, so the tower
select screen listed nothing at all - no floors, no progress, and nothing openable.

Six towers, one per region, each 210 floors. Five of them open on a weekday rota
(`OpenDays`); the unnamed theme-400 one and the West tower are open every day. The
rota is what makes the panel worth building carefully: a tower shown as available on
the wrong day sends the player into a battle whose stage the client will not load.

Floor ids encode the tower: theme * 100000 + floor, which is also what the
`StagesPrefix` in Babels.xml spells out.

    python3 babel.py     # self-check
"""
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

import missions

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

# C# DateTime.DayOfWeek, which is what the client compares OpenDays against:
# Sunday is 0. Reading it as Monday-first shifts every tower by a day.
SUNDAY = 0

_cache = {}


def _root(name, xml_dir):
    key = (name, str(xml_dir))
    if key not in _cache:
        _cache[key] = ET.parse(Path(xml_dir) / name).getroot()
    return _cache[key]


def towers(xml_dir=DEFAULT_XML):
    """{babelId: {theme, region, maxFloor, openDays}}."""
    out = {}
    for el in _root("Babels.xml", xml_dir):
        if el.get("ID") is None:
            continue
        days = [int(d) for d in (el.findtext("OpenDays") or "").split(",") if d.strip()]
        out[int(el.get("ID"))] = {
            "theme": int(el.findtext("Theme", 0)),
            "region": el.findtext("Region") or "",
            "maxFloor": int(el.findtext("MaxFloor", 0)),
            "openDays": days,
        }
    return out


def theme_to_id(xml_dir=DEFAULT_XML):
    return {t["theme"]: bid for bid, t in towers(xml_dir).items()}


def weekday(when=None):
    """C# DayOfWeek for a date: Sunday 0 .. Saturday 6."""
    when = when or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return (when.weekday() + 1) % 7


def available(bid, when=None, xml_dir=DEFAULT_XML):
    t = towers(xml_dir).get(bid)
    return bool(t) and weekday(when) in t["openDays"]


def next_open(bid, when=None, xml_dir=DEFAULT_XML):
    """Midnight UTC of the next day this tower opens, or the current day if it is
    open now. A tower with no open days would never return, so it reports never."""
    t = towers(xml_dir).get(bid)
    if not t or not t["openDays"]:
        return None
    when = when or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    midnight = when.replace(hour=0, minute=0, second=0, microsecond=0)
    for ahead in range(8):
        day = midnight + datetime.timedelta(days=ahead)
        if weekday(day) in t["openDays"]:
            return day
    return None


def floor_id(theme, floor):
    return theme * 100000 + floor


def floors(xml_dir=DEFAULT_XML):
    """{floorId: {"reward": [...], "passReward": [...], "power": n}}."""
    out = {}
    for el in _root("BabelFloors.xml", xml_dir):
        if el.get("ID") is None:
            continue
        out[int(el.get("ID"))] = {
            "reward": [missions.reward_attrs(r) for r in el.findall("Reward")],
            "passReward": [missions.reward_attrs(r) for r in el.findall("PassReward")],
            "power": int(el.findtext("RecommendedCombatPower", 0)),
        }
    return out




def floor_reward(theme, floor, xml_dir=DEFAULT_XML):
    return floors(xml_dir).get(floor_id(theme, floor), {}).get("reward", [])


def _self_check():
    ts = towers()
    assert len(ts) == 6, f"{len(ts)} towers, expected 6"
    assert all(t["maxFloor"] > 0 for t in ts.values())
    assert all(t["openDays"] for t in ts.values()), "a tower opens on no day at all"
    assert all(set(t["openDays"]) <= set(range(7)) for t in ts.values()), \
        "an OpenDays entry is outside 0..6"

    # Every weekday must open at least one tower, or the mode is dead that day.
    for d in range(7):
        assert any(d in t["openDays"] for t in ts.values()), f"no tower opens on day {d}"

    # Sunday-first, not Monday-first: a known Sunday must read as 0.
    assert weekday(datetime.datetime(2026, 7, 26)) == SUNDAY, "the weekday base is off"
    assert weekday(datetime.datetime(2026, 7, 25)) == 6, "Saturday is not 6"

    fs = floors()
    assert len(fs) >= 1200, f"only {len(fs)} floors parsed"
    for bid, t in ts.items():
        first = floor_id(t["theme"], 1)
        assert first in fs, f"tower {bid} has no floor 1 at id {first}"
        assert fs[first]["reward"], f"tower {bid} floor 1 pays nothing"
        # next_open must land on a day the tower is actually open.
        nxt = next_open(bid, datetime.datetime(2026, 7, 22))
        assert nxt and weekday(nxt) in t["openDays"], \
            f"tower {bid} next opens {nxt}, which is not in {t['openDays']}"

    open_now = [b for b in ts if available(b)]
    print(f"ok: {len(ts)} towers to floor {max(t['maxFloor'] for t in ts.values())}, "
          f"{len(fs)} floors, open today: {sorted(open_now)}")


if __name__ == "__main__":
    _self_check()
