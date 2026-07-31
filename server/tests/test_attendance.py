"""Attendance check-ins: the four rolling daily boards and the timed surprise event.

Both were served from static payloads that did not use the model's field names -
DailyAttendanceEventsResponseModel is {eventIds, attendances}, two parallel lists,
not {attendedDays, events} - so the grid rendered blank whatever the player had done.

Neither system has a claim route, so the read is what grants. That makes the failure
mode expensive rather than cosmetic: this route is called on every lobby refresh, and
without a per-day cap a fourteen-day board pays out in fourteen taps.
"""
import contextlib
import datetime, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import attendance
from tests.seed import one_account
one_account()          # multiplayer needs a session; load_state() has no fallback
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
    # The window is a date range in master data, so "is one running today" depends on
    # the calendar, not on the code: the day the last event expires this check starts
    # failing on a server that is completely correct. Drive the lookup instead - ask
    # for a day inside a known window and assert THAT event comes back.
    events = attendance.surprise_events(server.XML_DIR)
    assert events, "no surprise event in master data - the lookup has nothing to read"
    want = max(events, key=lambda e: e["start"])
    mid = (want["start"] + want["end"]) // 2
    picked = attendance.current_surprise(today=mid, xml_dir=server.XML_DIR)
    assert picked and picked["id"] == want["id"], \
        f"day {mid} is inside event {want['id']}'s window but got {picked}"
    assert attendance.current_surprise(today=want["end"] + 1,
                                       xml_dir=server.XML_DIR) != picked, \
        "an expired event is still served the day after it ends"

    live = attendance.current_surprise(xml_dir=server.XML_DIR)
    if live is None:
        print(f"ok live: no event today; window lookup picks {want['id']} correctly")
        return

    out = server.r_surprise_attendance({}, _fresh())
    assert out["eventId"] == live["id"], f"served event {out['eventId']}, live is {live['id']}"
    assert out["currentAttendanceDay"] == 1, "opening the panel did not check in"
    assert out["eventUntilAt"] > datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"), \
        "the live event is already reported as over"
    print(f"ok live: event {live['id']} ({live['title']}) until {out['eventUntilAt']}")


def check_surprise_reward_pays_each_day_once():
    # Needs an event running, and whether one is is a date range in master data - so
    # between events this would assert nothing. Pin one, the same way the continuous
    # check does, and the claim logic is tested every day of the year.
    with _pinned_event():
        _reward_once_body()


def _reward_once_body():
    st = _fresh()
    server.r_surprise_attendance({}, st)
    first = server.r_surprise_attendance_reward({}, server.load_state())
    assert first["rewardListResponseData"]["rewardList"], "day one paid nothing"
    assert first["eventResponseModel"]["lastAttendanceRewardDay"] == 1

    again = server.r_surprise_attendance_reward({}, server.load_state())
    assert not again["rewardListResponseData"]["rewardList"], "the same day paid twice"
    print(f"ok claim: {len(first['rewardListResponseData']['rewardList'])} reward(s) once")


@contextlib.contextmanager
def _pinned_event(want_continuous=False):
    """Run the block with one surprise event pinned live.

    Whether an event is running today is a date window in master data, so a check
    that needs one only works while the devs happen to have one open - it broke the
    day the 2026-07-16 event expired, on a server that was entirely correct. Pinning
    tests the code instead of the calendar.
    """
    events = attendance.surprise_events(server.XML_DIR)
    live = next((e for e in events if e["continuous"]), None) if want_continuous \
        else max(events, key=lambda e: e["start"])
    assert live, "no surprise event in master data to pin"
    real = attendance.current_surprise
    attendance.current_surprise = lambda today=None, xml_dir=None: live
    try:
        yield live
    finally:
        attendance.current_surprise = real


def check_surprise_continuous_bonus_needs_the_whole_streak():
    # The event live today has no ContinuousReward, so running this against it would
    # assert nothing about the bonus. Drive it with one that does.
    with _pinned_event(want_continuous=True) as live:
        _continuous_body(live)


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
    with _pinned_event():
        _reset_body()


def _reset_body():
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
