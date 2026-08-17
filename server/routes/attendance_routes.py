"""Attendance routes: the daily boards and the surprise event.

Neither system has a claim route for the reads: the check-in IS opening the game
that day, which is why the reward tables carry no button. Surprise rewards are
paid by the reward route, one day at a time.
"""
import datetime

from common import now_iso
from config import XML_DIR
from state import save_state
import attendance

srv = None      # live server module, injected via register()


def register(app, server_module):
    global srv
    srv = server_module
    srv.ATTENDANCE_OVERRIDES = handlers()


def handlers():
    return {
        "/player/dailyAttendanceEvents": r_daily_attendance_events,
        "/player/surprise-attendance-event": r_surprise_attendance,
        "/player/surprise-attendance-event-daily-attendance-reward": r_surprise_attendance_reward,
    }


def _today_str():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")


def _attend(st):
    a = st.setdefault("attendance", {})
    a.setdefault("daily", {})       # eventId -> {"day": n, "on": "YYYYMMDD"}
    a.setdefault("surprise", {})    # {"id", "day", "lastRewardDay", "on", "continuous"}
    return a


def r_daily_attendance_events(body, st):
    """Advance every daily board by at most one day, and pay for the day landed on.

    Capped at one advance per UTC day per event: this route is called on every lobby
    refresh, so advancing per call would walk a 14-day board in fourteen taps."""
    a = _attend(st)
    today = _today_str()
    events = attendance.daily_events(XML_DIR)
    granted = []
    for eid in sorted(events):
        rec = a["daily"].setdefault(str(eid), {"day": -1, "on": ""})
        length = attendance.daily_length(eid, XML_DIR)
        if rec["on"] != today and rec["day"] + 1 < length:
            rec["day"] += 1
            rec["on"] = today
            for r in events[eid].get(rec["day"], []):
                granted.append(srv._grant_mission_reward(st, r))
    if granted:
        save_state(st)
    ids = sorted(events)
    return {"eventIds": ids,
            # attendances is parallel to eventIds and counts days attended, so a board
            # sitting on 0-based day 0 has attended one day.
            "attendances": [a["daily"].get(str(i), {}).get("day", -1) + 1 for i in ids],
            "rewardList": srv._reward_list_data(granted)}


def _surprise_state(st, ev):
    a = _attend(st)
    s = a["surprise"]
    if not ev:
        return s
    if s.get("id") != ev["id"]:
        # A new event replaces the old board rather than resuming it.
        s.clear()
        s.update({"id": ev["id"], "day": 0, "lastRewardDay": 0, "on": "",
                  "continuous": True})
    return s


def _surprise_response(st, ev):
    s = _surprise_state(st, ev)
    if not ev:
        return {"eventId": 0, "currentAttendanceDay": 0, "lastAttendanceRewardDay": 0,
                "isContinuous": False, "eventUntilAt": ""}
    end = datetime.datetime.strptime(str(ev["end"]), "%Y%m%d") + datetime.timedelta(days=1)
    return {"eventId": ev["id"], "currentAttendanceDay": s.get("day", 0),
            "lastAttendanceRewardDay": s.get("lastRewardDay", 0),
            "isContinuous": bool(s.get("continuous", True)),
            "eventUntilAt": end.strftime("%Y-%m-%dT%H:%M:%S.000Z")}


def r_surprise_attendance(body, st):
    """Opening the panel is the check-in; the reward is claimed by the other route."""
    ev = attendance.current_surprise(xml_dir=XML_DIR)
    s = _surprise_state(st, ev)
    if ev:
        today = _today_str()
        if s.get("on") != today and s.get("day", 0) < len(ev["rewards"]):
            # A skipped day breaks the streak, which is what the continuous bonus
            # at the end of the board is gated on.
            if s.get("on") and s["on"] != (datetime.datetime.strptime(today, "%Y%m%d")
                                           - datetime.timedelta(days=1)).strftime("%Y%m%d"):
                s["continuous"] = False
            s["day"] = s.get("day", 0) + 1
            s["on"] = today
            save_state(st)
    return _surprise_response(st, ev)


def r_surprise_attendance_reward(body, st):
    """Pay every day reached but not yet claimed, plus the continuous bonus once the
    whole board is done without a break."""
    ev = attendance.current_surprise(xml_dir=XML_DIR)
    if not ev:
        return {"eventResponseModel": _surprise_response(st, ev),
                "rewardListResponseData": srv._reward_list_data([])}
    s = _surprise_state(st, ev)
    granted = []
    while s.get("lastRewardDay", 0) < s.get("day", 0):
        s["lastRewardDay"] += 1
        for r in ev["rewards"].get(s["lastRewardDay"], []):
            granted.append(srv._grant_mission_reward(st, r))
    if (s["lastRewardDay"] >= len(ev["rewards"]) and s.get("continuous")
            and not s.get("continuousPaid")):
        s["continuousPaid"] = True
        for r in ev["continuous"]:
            granted.append(srv._grant_mission_reward(st, r))
    if granted:
        save_state(st)
    return {"eventResponseModel": _surprise_response(st, ev),
            "rewardListResponseData": srv._reward_list_data(granted)}