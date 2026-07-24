"""Attendance check-ins: the four rolling daily boards and the timed surprise event.

Both were served from static payloads that did not use the model's field names -
DailyAttendanceEventsResponseModel is {eventIds, attendances}, two parallel lists,
not {attendedDays, events} - so the grid rendered blank whatever the player had done.

Neither system has a claim route, so the read is what grants. That makes the failure
mode expensive rather than cosmetic: this route is called on every lobby refresh, and
without a per-day cap a fourteen-day board pays out in fourteen taps.
"""
import datetime, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import attendance
import server


def _fresh():
    st = server.load_state()
    st.pop("attendance", None)
    st["inventory"] = {"itemIds": [], "counts": []}
    st["gold"] = st["cash"] = st["heart"] = 0
    server.save_state(st)
    return st


def _yesterday():
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=1)).strftime("%Y%m%d")


def _rewind_daily(days=1):
    """Backdate every board so the next call counts as a new day."""
    st = server.load_state()
    stamp = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=days)).strftime("%Y%m%d")
    for rec in st["attendance"]["daily"].values():
        rec["on"] = stamp
    server.save_state(st)


def check_daily_shape_matches_the_model():
    out = server.r_daily_attendance_events({}, _fresh())
    assert out["eventIds"] == sorted(attendance.daily_events(server.XML_DIR)), \
        "eventIds does not list every board"
    assert len(out["attendances"]) == len(out["eventIds"]), \
        "attendances is not parallel to eventIds"
    assert all(n == 1 for n in out["attendances"]), \
        f"a fresh save is not on day one of every board: {out['attendances']}"
    print(f"ok shape: {out['eventIds']} -> {out['attendances']}")


def check_daily_advances_once_per_day():
    st = _fresh()
    first = server.r_daily_attendance_events({}, st)
    assert first["rewardList"]["rewardList"], "day one paid nothing"
    gold = server.load_state()["gold"]

    again = server.r_daily_attendance_events({}, server.load_state())
    assert not again["rewardList"]["rewardList"], "a second call the same day paid again"
    assert again["attendances"] == first["attendances"], "the board advanced twice in a day"
    assert server.load_state()["gold"] == gold

    _rewind_daily()
    third = server.r_daily_attendance_events({}, server.load_state())
    assert third["attendances"] == [n + 1 for n in first["attendances"]], \
        f"a new day gave {third['attendances']}, expected one more than {first['attendances']}"
    assert third["rewardList"]["rewardList"], "day two paid nothing"
    print(f"ok daily: one advance per UTC day, {len(first['rewardList']['rewardList'])} "
          f"rewards on day one")


def check_daily_stops_at_the_end_of_the_board():
    st = _fresh()
    longest = max(attendance.daily_events(server.XML_DIR),
                  key=lambda i: attendance.daily_length(i, server.XML_DIR))
    length = attendance.daily_length(longest, server.XML_DIR)
    for _ in range(length + 5):
        out = server.r_daily_attendance_events({}, server.load_state())
        _rewind_daily()
    idx = out["eventIds"].index(longest)
    assert out["attendances"][idx] == length, \
        f"board {longest} reached day {out['attendances'][idx]} of {length}"
    assert not out["rewardList"]["rewardList"], "a finished board still pays out"
    print(f"ok end: board {longest} stopped at its {length}th day")


def check_surprise_event_is_the_live_one():
    out = server.r_surprise_attendance({}, _fresh())
    live = attendance.current_surprise(xml_dir=server.XML_DIR)
    assert live, "no surprise event is live - this check needs one in the window"
    assert out["eventId"] == live["id"], f"served event {out['eventId']}, live is {live['id']}"
    assert out["currentAttendanceDay"] == 1, "opening the panel did not check in"
    assert out["eventUntilAt"] > datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"), \
        "the live event is already reported as over"
    print(f"ok live: event {live['id']} ({live['title']}) until {out['eventUntilAt']}")


def check_surprise_reward_pays_each_day_once():
    st = _fresh()
    server.r_surprise_attendance({}, st)
    first = server.r_surprise_attendance_reward({}, server.load_state())
    assert first["rewardListResponseData"]["rewardList"], "day one paid nothing"
    assert first["eventResponseModel"]["lastAttendanceRewardDay"] == 1

    again = server.r_surprise_attendance_reward({}, server.load_state())
    assert not again["rewardListResponseData"]["rewardList"], "the same day paid twice"
    print(f"ok claim: {len(first['rewardListResponseData']['rewardList'])} reward(s) once")


def check_surprise_continuous_bonus_needs_the_whole_streak():
    # The event live today has no ContinuousReward, so running this against it would
    # assert nothing about the bonus. Drive it with one that does.
    live = next(e for e in attendance.surprise_events(server.XML_DIR) if e["continuous"])
    real = attendance.current_surprise
    attendance.current_surprise = lambda today=None, xml_dir=None: live
    try:
        _continuous_body(live)
    finally:
        attendance.current_surprise = real


def _continuous_body(live):
    days = len(live["rewards"])

    # A clean run: every day in a row, then the continuous bonus lands exactly once.
    st = _fresh()
    for i in range(days):
        server.r_surprise_attendance({}, server.load_state())
        s = server.load_state()
        s["attendance"]["surprise"]["on"] = _yesterday()
        server.save_state(s)
    out = server.r_surprise_attendance_reward({}, server.load_state())
    paid = out["rewardListResponseData"]["rewardList"]
    expected = sum(len(live["rewards"][d]) for d in range(1, days + 1)) + len(live["continuous"])
    assert len(paid) == expected, f"a full streak paid {len(paid)}, expected {expected}"
    assert out["eventResponseModel"]["isContinuous"], "an unbroken streak was not continuous"
    after = server.r_surprise_attendance_reward({}, server.load_state())
    assert not after["rewardListResponseData"]["rewardList"], "the bonus paid twice"

    # A broken streak: same days attended, no continuous bonus.
    st = _fresh()
    for i in range(days):
        server.r_surprise_attendance({}, server.load_state())
        s = server.load_state()
        s["attendance"]["surprise"]["on"] = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=3)).strftime("%Y%m%d")
        server.save_state(s)
    out = server.r_surprise_attendance_reward({}, server.load_state())
    assert not out["eventResponseModel"]["isContinuous"], "a gap did not break the streak"
    broken = len(out["rewardListResponseData"]["rewardList"])
    assert broken == expected - len(live["continuous"]), \
        f"a broken streak paid {broken}, expected {expected - len(live['continuous'])}"
    print(f"ok streak: {days} days -> {expected} rewards, a gap costs the "
          f"{len(live['continuous'])}-reward bonus")


def check_a_new_event_resets_the_board():
    """Boards do not resume across events - the state names its event id for exactly
    this reason."""
    st = _fresh()
    server.r_surprise_attendance({}, st)
    s = server.load_state()
    s["attendance"]["surprise"]["id"] = 999
    s["attendance"]["surprise"]["day"] = 6
    s["attendance"]["surprise"]["lastRewardDay"] = 6
    server.save_state(s)
    out = server.r_surprise_attendance({}, server.load_state())
    assert out["currentAttendanceDay"] == 1, \
        f"a stale board carried {out['currentAttendanceDay']} days into a new event"
    assert out["lastAttendanceRewardDay"] == 0, "stale claims carried over"
    print("ok reset: a different event id starts the board over")


if __name__ == "__main__":
    check_daily_shape_matches_the_model()
    check_daily_advances_once_per_day()
    check_daily_stops_at_the_end_of_the_board()
    check_surprise_event_is_the_live_one()
    check_surprise_reward_pays_each_day_once()
    check_surprise_continuous_bonus_needs_the_whole_streak()
    check_a_new_event_resets_the_board()
    print("\nall attendance checks passed")
