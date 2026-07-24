"""The two timed tables the /player routes serve: journey and the anniversary event.

Both answered an empty model, so the journey button never lit up and the
anniversary panel opened blank.

**Journey** is the idle-reward ladder behind the lobby's little gift button:
sixteen rewards in a fixed order, each with its own wait (`JourneyRewards.xml`).
The client tracks it through two key-values it reads back off the response -
`JourneyLastRewardId` and `JourneyNextRewardTime` - so those two strings, not a
model field, are what actually drive the button.

**The anniversary event** (`FifthHalfYearEventRewards.xml`) is a 30-day pass
track plus a 10-day attendance board with a continuous-streak bonus. Whether it
is running at all is the server's call - the table carries no dates - so the
window comes from `response_config.json`.

    python3 player_events.py     # self-check
"""
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

import missions

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

_cache = {}


def _root(name, xml_dir):
    key = (name, str(xml_dir))
    if key not in _cache:
        _cache[key] = ET.parse(Path(xml_dir) / name).getroot()
    return _cache[key]


# --- Journey ------------------------------------------------------------------

def _seconds(text):
    """"HH:MM:SS" -> seconds. The resource keeps this as an int[] it re-joins into
    a TimeSpan, so a plain split is the same reading."""
    parts = [int(p) for p in (text or "0").strip().split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def journey_rewards(xml_dir=DEFAULT_XML):
    """[{id, wait, reward}] in claim order."""
    out = []
    for group in _root("JourneyRewards.xml", xml_dir):
        for item in group:
            r = item.find("Reward")
            if r is None:
                continue
            out.append({"id": int(item.get("ID", 0) or 0),
                        "wait": _seconds(item.findtext("Time")),
                        "reward": missions.reward_attrs(r)})
    return sorted(out, key=lambda i: i["id"])


def journey_next(last_id, xml_dir=DEFAULT_XML):
    """The reward that comes after `last_id`, or None at the end of the ladder."""
    for item in journey_rewards(xml_dir):
        if item["id"] > last_id:
            return item
    return None


# --- Anniversary event --------------------------------------------------------

def _rewards_of(node):
    """Every <Reward> under a node, or the node itself when it carries the Type.

    <ContinuousReward> holds its rewards as children, but an <AttendanceReward>
    day can do either - reading only children silently empties the ones that do
    not, which is the same trap attendance.py hit."""
    if node is None:
        return []
    if node.get("Type"):
        return [missions.reward_attrs(node)]
    return [missions.reward_attrs(r) for r in node.findall("Reward")]


def _year_root(xml_dir):
    root = _root("FifthHalfYearEventRewards.xml", xml_dir)
    kids = list(root)
    return kids[0] if kids else None


def _section(node, name):
    """A named child's element list, empty when the section is absent. Written out
    because `node.find(x) or []` is truthiness on an Element, which is deprecated
    and reads False for a section that exists but has no children."""
    if node is None:
        return []
    sec = node.find(name)
    return [] if sec is None else list(sec)


def year_pass_rewards(xml_dir=DEFAULT_XML):
    """{day: [rewards]} for the 30-day pass track."""
    out = {}
    for el in _section(_year_root(xml_dir), "PassRewards"):
        out[int(el.get("Day", 0) or 0)] = _rewards_of(el)
    return out


def year_attendance_rewards(xml_dir=DEFAULT_XML):
    out = {}
    for el in _section(_year_root(xml_dir), "AttendanceRewards"):
        out[int(el.get("Day", 0) or 0)] = _rewards_of(el)
    return out


def year_continuous_reward(xml_dir=DEFAULT_XML):
    """Paid on top once the attendance board is completed without a gap."""
    node = _year_root(xml_dir)
    return _rewards_of(node.find("ContinuousReward") if node is not None else None)


def year_days(xml_dir=DEFAULT_XML):
    """(attendance days, pass days) - the two tracks are different lengths."""
    return (max(year_attendance_rewards(xml_dir) or [0]),
            max(year_pass_rewards(xml_dir) or [0]))


def elapsed_days(start, now=None):
    """Whole days since `start`, 1-based: the first day of an event is day 1."""
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return max(1, (now.date() - start.date()).days + 1)


def _self_check():
    js = journey_rewards()
    assert len(js) >= 10, f"{len(js)} journey rewards parsed"
    assert [i["id"] for i in js] == sorted(i["id"] for i in js), "journey is out of order"
    assert all(i["wait"] > 0 for i in js), "a journey reward has no wait"
    assert all(i["reward"]["count"] > 0 for i in js), "a journey reward pays nothing"
    assert _seconds("12:00:00") == 43200 and _seconds("00:05:00") == 300
    assert journey_next(-1)["id"] == js[0]["id"], "the ladder does not start at the first"
    assert journey_next(js[-1]["id"]) is None, "the ladder never ends"
    # Every id must be reachable by walking the ladder, or a reward is skipped.
    seen, last = [], -1
    while True:
        nxt = journey_next(last)
        if nxt is None:
            break
        seen.append(nxt["id"])
        last = nxt["id"]
    assert seen == [i["id"] for i in js], "walking the ladder skips a reward"

    att, pas = year_attendance_rewards(), year_pass_rewards()
    assert att and pas, "the anniversary tables are empty"
    assert sorted(att) == list(range(1, len(att) + 1)), f"attendance days: {sorted(att)}"
    assert sorted(pas) == list(range(1, len(pas) + 1)), f"pass days: {sorted(pas)}"
    assert all(v for v in att.values()), "an attendance day pays nothing"
    assert all(v for v in pas.values()), "a pass day pays nothing"
    cont = year_continuous_reward()
    assert cont, "the continuous bonus is empty - the Type-on-self case regressed"
    assert year_days() == (len(att), len(pas))

    base = datetime.datetime(2026, 7, 1)
    assert elapsed_days(base, base) == 1, "the first day of an event is not day 1"
    assert elapsed_days(base, base + datetime.timedelta(days=3)) == 4
    assert elapsed_days(base, base - datetime.timedelta(days=5)) == 1, \
        "a clock before the start went negative"

    print(f"ok: {len(js)} journey rewards, anniversary {len(att)}-day attendance + "
          f"{len(pas)}-day pass + {len(cont)} continuous")


if __name__ == "__main__":
    _self_check()
