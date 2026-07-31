"""The two ladders that run on a clock: the Journey and the anniversary event.

Both hand out a reward per elapsed step. The Journey's whole protocol is two
key-values the client reads back off the response - JourneyLastRewardId and
JourneyNextRewardTime - not model fields, which is why arming it writes through
`_set_key_value` rather than returning a shape.

FifthHalfYearEventRewards.xml carries no dates of its own, so whether the anniversary
event is running is the server's call and lives in response_config.

Uses the `register(app, srv)` pattern.

    python3 seasonal.py     # self-check
"""
import datetime

import player_events
from common import admin_log, now_iso
from config import RCFG, XML_DIR
from state import save_state

srv = None      # the live server module, set by register()

# --- Journey ------------------------------------------------------------------
# The client drives this entirely off two key-values it reads back off the response,
# not off a model field: JourneyLastRewardId and JourneyNextRewardTime.

JOURNEY_LAST = "JourneyLastRewardId"
JOURNEY_NEXT = "JourneyNextRewardTime"


def _journey_arm(st, last_id):
    """Point the ladder at the reward after `last_id` and start its clock."""
    nxt = player_events.journey_next(last_id, XML_DIR)
    srv._set_key_value(st, JOURNEY_LAST, str(last_id))
    srv._set_key_value(st, JOURNEY_NEXT, "" if nxt is None
                   else now_iso(seconds=nxt["wait"]))
    return nxt


def r_journey_init(body, st):
    """Start the ladder. Re-initialising an armed journey must not reset its timer,
    or the panel becomes a way to never wait."""
    if srv._key_value(st, JOURNEY_NEXT) is None:
        _journey_arm(st, -1)
        save_state(st)
    return {"rewardList": srv._reward_list_data([]), "keyValues": srv._key_values(st)}


def r_journey_reward(body, st):
    """Claim the reward whose wait has elapsed, then arm the next one."""
    last = int(srv._key_value(st, JOURNEY_LAST, -1) or -1)
    due = srv._key_value(st, JOURNEY_NEXT)
    item = player_events.journey_next(last, XML_DIR)
    if item is None or not due or now_iso(0) < due:
        return {"rewardList": srv._reward_list_data([]), "keyValues": srv._key_values(st)}
    paid = [srv._grant_mission_reward(st, item["reward"])]
    _journey_arm(st, item["id"])
    save_state(st)
    admin_log(f"[journey] reward {item['id']} claimed -> {paid}")
    return {"rewardList": srv._reward_list_data(paid), "keyValues": srv._key_values(st)}


def _year_state(st):
    y = st.setdefault("yearEvent", {})
    y.setdefault("startedAt", now_iso(RCFG["yearEvent"]["startDayOffset"]))
    y.setdefault("lastAttendanceDay", 0)
    y.setdefault("lastPassDay", 0)
    y.setdefault("passPoint", 0)
    y.setdefault("continuous", True)
    return y


def _year_day(st):
    y = _year_state(st)
    start = datetime.datetime.fromisoformat(y["startedAt"].replace("Z", ""))
    cfg = RCFG["yearEvent"]
    return min(player_events.elapsed_days(start), cfg["lengthDays"]), start


def r_year_event(body, st):
    cfg = RCFG["yearEvent"]
    y = _year_state(st)
    day, start = _year_day(st)
    save_state(st)
    return {"eventStartAt": y["startedAt"],
            "eventUntilAt": now_iso(cfg["startDayOffset"] + cfg["lengthDays"]),
            "currentAttendanceDay": day if cfg["enabled"] else 0,
            "lastAttendanceRewardDay": y["lastAttendanceDay"],
            "isContinuous": y["continuous"],
            "lastPassRewardDay": y["lastPassDay"],
            "passPoint": y["passPoint"]}


def _year_claim(st, track, table):
    """Pay every unclaimed day of a track up to today. Both tracks pay per day and
    only once, so the last claimed day is the whole bookkeeping."""
    cfg = RCFG["yearEvent"]
    y = _year_state(st)
    if not cfg["enabled"]:
        return []
    day, _ = _year_day(st)
    paid = []
    for d in sorted(table):
        if d <= y[track] or d > day:
            continue
        for r in table[d]:
            paid.append(srv._grant_mission_reward(st, r))
        y[track] = d
    return paid


def r_year_attendance_reward(body, st):
    table = player_events.year_attendance_rewards(XML_DIR)
    paid = _year_claim(st, "lastAttendanceDay", table)
    y = _year_state(st)
    # The continuous bonus is paid on top, once, when the board is completed
    # without a gap - claiming the last day late still leaves isContinuous true
    # here because there is nobody to break the streak on a single-player save.
    if y["lastAttendanceDay"] >= max(table or [0]) and not y.get("continuousPaid"):
        for r in player_events.year_continuous_reward(XML_DIR):
            paid.append(srv._grant_mission_reward(st, r))
        y["continuousPaid"] = True
    save_state(st)
    return {"eventResponseModel": r_year_event(body, st),
            "rewardListResponseData": srv._reward_list_data(paid)}


def r_year_pass_reward(body, st):
    paid = _year_claim(st, "lastPassDay", player_events.year_pass_rewards(XML_DIR))
    save_state(st)
    return {"eventResponseModel": r_year_event(body, st),
            "rewardListResponseData": srv._reward_list_data(paid)}


def r_year_buy_pass_point(body, st):
    """Buy pass points with cash. Refuses rather than going negative - the client
    re-reads the balance from this response."""
    cfg = RCFG["yearEvent"]
    y = _year_state(st)
    price = cfg["buyPassPointCashPrice"]
    if st.get("cash", 0) >= price:
        st["cash"] -= price
        y["passPoint"] += cfg["buyPassPointCount"]
        save_state(st)
    return {"eventResponseModel": r_year_event(body, st),
            "playerCash": st.get("cash", 0)}


def register(app, server_module):
    global srv
    srv = server_module
    srv.SEASONAL_OVERRIDES = handlers()


def handlers():
    return {
        "/player/initialize-journey": r_journey_init,
        "/player/journey-reward": r_journey_reward,
        "/player/year-event": r_year_event,
        "/player/year-event-attendance-reward": r_year_attendance_reward,
        "/player/year-event-pass-reward": r_year_pass_reward,
        "/player/year-event-buy-pass-point": r_year_buy_pass_point,
    }


if __name__ == "__main__":
    import pathlib as _pl
    import sys
    import tempfile

    import playerdb
    playerdb.DB_PATH = _pl.Path(tempfile.mkdtemp()) / "t.db"
    playerdb.init()
    import server                                        # noqa: E402
    register(server.app, sys.modules["server"])

    st = server.copy.deepcopy(server.DEFAULT_PLAYER)
    st["uid"] = "t"
    playerdb.save("t", st)
    playerdb.set_active("t")

    # Arming the journey sets its clock; re-initialising must not restart it.
    r_journey_init({}, st)
    due = srv._key_value(st, JOURNEY_NEXT)
    assert due is not None, "the journey never armed"
    r_journey_init({}, st)
    assert srv._key_value(st, JOURNEY_NEXT) == due, "re-init reset the timer - a free skip"

    # Claiming before the wait elapses pays nothing.
    before = st.get("gold", 0)
    out = r_journey_reward({}, st)
    assert out["rewardList"]["rewardList"] == [], "an unelapsed wait still paid out"
    assert st.get("gold", 0) == before

    y = r_year_event({}, st)
    for k in ("eventStartAt", "eventUntilAt", "currentAttendanceDay"):
        assert y[k] is not None and y[k] != "", f"{k} null - the client DateTime.Parses it"
    for k in ("startedAt", "lastAttendanceDay"):
        assert k in st["yearEvent"], k

    paths = handlers()
    assert len(paths) == 6, f"{len(paths)} routes registered"
    assert all(callable(h) for h in paths.values())
    print(f"seasonal self-check ok ({len(paths)} routes)")
