"""Attendance check-ins: the rolling daily events and the timed surprise event.

Two systems, both served from static payloads that did not even use the right field
names. `/player/dailyAttendanceEvents` answered {"attendedDays", "events"} while
DailyAttendanceEventsResponseModel is {eventIds, attendances} - two parallel lists -
so the grid rendered blank whatever the player had done.

The surprise event is the one that is live today: SurpriseAttendanceEvents.xml entry
4 runs 20260716..20260729. It has a participation window (join inside it) that is
separate from MaxDay (how long the board stays open once joined), so a player who
joins on the last day still gets their full run.

Neither system has a claim route. GetDailyAttendanceEvents and
GetPlayerSurpriseAttendanceEvent are reads that also grant - the check-in is the act
of opening the game that day, which is why the reward tables carry no button.

    python3 attendance.py     # self-check
"""
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

# Reward fields that name an inventory item by their own tag, as the shop and mission
# tables do. UnitExpCount is 경험의 서, the exp book.
UNIT_EXP_ITEM = 110

_cache = {}


def _root(name, xml_dir):
    key = (name, str(xml_dir))
    if key not in _cache:
        _cache[key] = ET.parse(Path(xml_dir) / name).getroot()
    return _cache[key]


def _int(el, tag, dflt=0):
    txt = el.findtext(tag)
    try:
        return int(str(txt).strip())
    except (TypeError, ValueError):
        return dflt


def _daily_rewards(el):
    """One DailyAttendanceEvent row -> reward list.

    Each reward is its own tag rather than a Type attribute, so an unrecognised tag
    is silently nothing - hence the explicit list."""
    out = []
    if _int(el, "Gold"):
        out.append({"type": "Gold", "id": 0, "count": _int(el, "Gold")})
    if _int(el, "Cash"):
        out.append({"type": "Cash", "id": 0, "count": _int(el, "Cash")})
    if _int(el, "Heart"):
        out.append({"type": "Heart", "id": 0, "count": _int(el, "Heart")})
    if _int(el, "UnitExpCount"):
        out.append({"type": "Item", "id": UNIT_EXP_ITEM, "count": _int(el, "UnitExpCount")})
    if _int(el, "KeyID"):
        out.append({"type": "Key", "id": _int(el, "KeyID"),
                    "count": _int(el, "KeyCount", 1) or 1})
    item = el.find("InventoryItem")
    if item is not None:
        out.append({"type": "Item", "id": int(item.get("ID", 0)),
                    "count": int(item.get("Count", 1))})
    if _int(el, "NewUnitGacha"):
        out.append({"type": "NewUnitGacha", "id": 0, "count": _int(el, "NewUnitGacha")})
    return out


def daily_events(xml_dir=DEFAULT_XML):
    """{eventId: {day: [rewards]}}. Day is 0-based in the master data."""
    out = {}
    for el in _root("DailyAttendanceEvents.xml", xml_dir):
        if el.get("ID") is None:
            continue
        out.setdefault(_int(el, "EventID"), {})[_int(el, "Day")] = _daily_rewards(el)
    return out


def daily_length(event_id, xml_dir=DEFAULT_XML):
    days = daily_events(xml_dir).get(event_id, {})
    return max(days) + 1 if days else 0


def _surprise_rewards(node):
    """A day's <AttendanceReward> holds one or more <Reward> children, but
    <ContinuousReward> carries the Type on itself - reading only the children makes
    every continuous bonus silently empty."""
    out = []
    for r in [node] if node.get("Type") else node.findall("Reward"):
        t = r.get("Type") or ""
        cnt = int(r.get("Count", 1))
        rid = int(r.get("ID", 0))
        if t == "InventoryItem":
            out.append({"type": "Item", "id": rid, "count": cnt})
        elif t in ("Gold", "Cash", "Heart", "Key"):
            out.append({"type": t, "id": rid, "count": cnt})
        else:
            # Treasure_Special and friends are display-only, the same policy the mail
            # and mission rewards follow.
            out.append({"type": t, "id": rid, "count": cnt})
    return out


def surprise_events(xml_dir=DEFAULT_XML):
    out = []
    for el in _root("SurpriseAttendanceEvents.xml", xml_dir):
        if el.get("ID") is None:
            continue
        cont = el.find("ContinuousReward")
        out.append({
            "id": int(el.get("ID")),
            "title": el.findtext("Title") or "",
            "start": _int(el, "ParticipateStartAt"),
            "end": _int(el, "ParticipateEndAt"),
            "maxDay": _int(el, "MaxDay"),
            "rewards": {int(a.get("Day")): _surprise_rewards(a)
                        for a in el.findall("AttendanceRewards/AttendanceReward")},
            "continuous": _surprise_rewards(cont) if cont is not None else [],
        })
    return out


def current_surprise(today=None, xml_dir=DEFAULT_XML):
    """The event whose participation window contains `today` (YYYYMMDD int), or None.

    Windows do not overlap in the shipped data, but if they ever do the later one
    wins - a new event replacing an old one is the only reason two would."""
    if today is None:
        today = int(datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d"))
    live = [e for e in surprise_events(xml_dir) if e["start"] <= today <= e["end"]]
    return max(live, key=lambda e: e["start"]) if live else None


def _self_check():
    ev = daily_events()
    assert len(ev) >= 4, f"only {len(ev)} daily attendance events"
    for eid, days in ev.items():
        assert sorted(days) == list(range(len(days))), \
            f"event {eid} has gaps in its day list: {sorted(days)}"
        assert daily_length(eid) in (7, 14), f"event {eid} runs {daily_length(eid)} days"
        for d, rs in days.items():
            assert rs, f"event {eid} day {d} pays nothing"
            assert all(r["count"] >= 1 for r in rs), f"event {eid} day {d} has a zero count"

    ss = surprise_events()
    assert ss, "no surprise attendance events parsed"
    for e in ss:
        assert e["start"] < e["end"], f"event {e['id']} ends before it starts"
        assert e["maxDay"] >= len(e["rewards"]), \
            f"event {e['id']} closes after {e['maxDay']} days but has {len(e['rewards'])}"
        assert sorted(e["rewards"]) == list(range(1, len(e["rewards"]) + 1)), \
            f"event {e['id']} days are not 1..N: {sorted(e['rewards'])}"
        assert all(rs for rs in e["rewards"].values()), f"event {e['id']} has an empty day"
    # ContinuousReward puts its Type on the element itself; reading only <Reward>
    # children leaves every bonus empty and the streak pays nothing at the end.
    assert any(e["continuous"] for e in ss), "no surprise event has a continuous bonus"

    # The window must actually select: a date inside one event and outside another.
    inside = current_surprise(20260724)
    assert inside and inside["id"] == 4, f"20260724 selected {inside and inside['id']}"
    assert current_surprise(20260101) is None, "a date in no window still found an event"
    # Joining on the final day must still leave a full run - that is what MaxDay is for.
    assert inside["maxDay"] >= len(inside["rewards"])

    print(f"ok: {len(ev)} daily events ({[daily_length(i) for i in sorted(ev)]} days), "
          f"{len(ss)} surprise events, live today: {inside['title']} "
          f"({len(inside['rewards'])} days, until {inside['end']})")


if __name__ == "__main__":
    _self_check()
