"""The rest of /player: profile icon, journey and the anniversary event.

Seventeen routes answered an empty model. Most are one-way telemetry where an
acknowledgement is the whole correct answer; the three that carry state are worth
checking, because each has a way to fail that pays out for free.

Journey is a timed ladder, so re-initialising must not restart the clock and a
claim before the wait has elapsed must pay nothing. The anniversary tracks pay per
day and only once. And a profile icon that is not a hero the player owns draws a
blank white avatar, so the route has to refuse it rather than store it.
"""
import datetime, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import player_events
import server


def _fresh():
    st = server.load_state()
    st.pop("yearEvent", None)
    st["keyValues"] = []
    st["inventory"] = {"itemIds": [], "counts": []}
    st["gold"] = 0
    st["cash"] = 0
    server.save_state(st)
    return server.load_state()


def check_profile_icon_must_be_an_owned_hero():
    st = _fresh()
    owned = int(next(iter(st["cards"])))
    server.r_change_profile_icon({"profileIconId": owned}, server.load_state())
    assert server._key_value(server.load_state(), "profileIconId") == owned

    server.r_change_profile_icon({"profileIconId": 999999}, server.load_state())
    assert server._key_value(server.load_state(), "profileIconId") == owned, \
        "an id that resolves to no hero was stored - the avatar renders blank"
    print(f"ok icon: hero {owned} accepted, 999999 refused")


def check_the_journey_arms_once():
    st = _fresh()
    server.r_journey_init({}, server.load_state())
    first = server._key_value(server.load_state(), server.JOURNEY_NEXT)
    assert first, "the journey was never armed"
    assert server._key_value(server.load_state(), server.JOURNEY_LAST) == "-1"

    server.r_journey_init({}, server.load_state())
    assert server._key_value(server.load_state(), server.JOURNEY_NEXT) == first, \
        "re-initialising restarted the timer - the wait can be skipped by reopening"
    print(f"ok journey init: armed once, due {first}")


def check_a_journey_reward_waits_for_its_timer():
    st = _fresh()
    server.r_journey_init({}, server.load_state())
    out = server.r_journey_reward({}, server.load_state())
    assert not out["rewardList"]["rewardList"], "the first reward paid with no wait"

    # Wind the clock back by making the reward due in the past.
    st = server.load_state()
    server._set_key_value(st, server.JOURNEY_NEXT, server.now_iso(-1))
    server.save_state(st)
    out = server.r_journey_reward({}, server.load_state())
    paid = out["rewardList"]["rewardList"]
    assert paid, "an elapsed reward paid nothing"
    want = player_events.journey_rewards(server.XML_DIR)[0]["reward"]
    assert paid[0]["count"] == want["count"], f"paid {paid[0]}, table says {want}"
    assert server._key_value(server.load_state(), server.JOURNEY_LAST) == "0", \
        "the ladder did not advance"
    assert server.load_state()["gold"] == want["count"], \
        "the journey reward never reached the save"

    again = server.r_journey_reward({}, server.load_state())
    assert not again["rewardList"]["rewardList"], "the next reward paid instantly"
    print(f"ok journey claim: {paid[0]['count']} gold once the wait elapsed")


def check_the_journey_ends():
    st = _fresh()
    server.r_journey_init({}, server.load_state())
    ladder = player_events.journey_rewards(server.XML_DIR)
    for _ in ladder:
        s = server.load_state()
        server._set_key_value(s, server.JOURNEY_NEXT, server.now_iso(-1))
        server.save_state(s)
        server.r_journey_reward({}, server.load_state())
    last = server._key_value(server.load_state(), server.JOURNEY_LAST)
    assert int(last) == ladder[-1]["id"], f"the ladder stopped at {last}"
    out = server.r_journey_reward({}, server.load_state())
    assert not out["rewardList"]["rewardList"], "the finished ladder kept paying"
    print(f"ok journey end: {len(ladder)} rewards, then nothing")


def check_the_year_event_reports_a_window():
    _fresh()
    out = server.r_year_event({}, server.load_state())
    assert out["eventStartAt"] < out["eventUntilAt"], "the event ends before it starts"
    assert out["currentAttendanceDay"] >= 1, "the event is running but day 0"
    att, _ = player_events.year_days(server.XML_DIR)
    assert out["currentAttendanceDay"] <= server.RCFG["yearEvent"]["lengthDays"]
    print(f"ok year window: day {out['currentAttendanceDay']}, "
          f"{att}-day attendance board")


def check_year_tracks_pay_each_day_once():
    st = _fresh()
    out = server.r_year_attendance_reward({}, server.load_state())
    day = out["eventResponseModel"]["currentAttendanceDay"]
    paid = out["rewardListResponseData"]["rewardList"]
    table = player_events.year_attendance_rewards(server.XML_DIR)
    want = sum(len(table[d]) for d in table if d <= day)
    assert len(paid) == want, f"day {day} paid {len(paid)} rewards, table lists {want}"
    assert out["eventResponseModel"]["lastAttendanceRewardDay"] == day

    again = server.r_year_attendance_reward({}, server.load_state())
    assert not again["rewardListResponseData"]["rewardList"], \
        "the same days paid a second time"
    print(f"ok year attendance: {len(paid)} rewards for days 1-{day}, then nothing")


def check_the_continuous_bonus_needs_the_whole_board():
    st = _fresh()
    y = server._year_state(st)
    att = player_events.year_attendance_rewards(server.XML_DIR)
    y["lastAttendanceDay"] = max(att) - 1
    # Push the start back far enough that every day of the board is available.
    y["startedAt"] = server.now_iso(-max(att) - 1)
    server.save_state(st)
    out = server.r_year_attendance_reward({}, server.load_state())
    paid = out["rewardListResponseData"]["rewardList"]
    bonus = player_events.year_continuous_reward(server.XML_DIR)
    assert len(paid) == len(att[max(att)]) + len(bonus), \
        f"completing the board paid {len(paid)}, expected the last day plus {len(bonus)}"
    assert server.load_state()["yearEvent"]["continuousPaid"] is True

    again = server.r_year_attendance_reward({}, server.load_state())
    assert not again["rewardListResponseData"]["rewardList"], \
        "the continuous bonus paid twice"
    print(f"ok year streak: {len(bonus)} bonus rewards on completion, once")


def check_pass_points_cost_cash():
    st = _fresh()
    cfg = server.RCFG["yearEvent"]
    out = server.r_year_buy_pass_point({}, server.load_state())
    assert out["eventResponseModel"]["passPoint"] == 0, \
        "pass points were granted with no cash"

    st = server.load_state()
    st["cash"] = cfg["buyPassPointCashPrice"]
    server.save_state(st)
    out = server.r_year_buy_pass_point({}, server.load_state())
    assert out["eventResponseModel"]["passPoint"] == cfg["buyPassPointCount"]
    assert out["playerCash"] == 0, f"cash left at {out['playerCash']}"
    print(f"ok pass points: {cfg['buyPassPointCount']} for "
          f"{cfg['buyPassPointCashPrice']} cash, refused when broke")


def check_the_ad_counter_moves():
    st = _fresh()
    st.pop("dailyAdCount", None)
    server.save_state(st)
    first = server.r_player_ad({}, server.load_state())["dailyAdCount"]
    second = server.r_player_ad({}, server.load_state())["dailyAdCount"]
    assert (first, second) == (1, 2), f"counted {first} then {second}"
    print("ok ad: the daily counter increments")


def check_other_player_is_this_player():
    st = server.load_state()
    out = server.r_player_other({"targetId": 1}, st)
    assert out["name"] == st.get("name"), "the profile shows somebody else"
    assert out["heroCount"] == len(st.get("cards", {}))
    assert out["currentDeck"], "the profile draws a deck and got none"
    print(f"ok other: {out['heroCount']} heroes, {len(out['currentDeck'])} in the deck")


def check_every_player_route_answers():
    _fresh()
    for path, fn in server.DYNAMIC_OVERRIDES.items():
        if not path.startswith("/player"):
            continue
        out = fn({}, server.load_state())
        assert isinstance(out, dict), f"{path} returned {type(out)}"
    print("ok safety: every /player route answers on a fresh save")


if __name__ == "__main__":
    check_profile_icon_must_be_an_owned_hero()
    check_the_journey_arms_once()
    check_a_journey_reward_waits_for_its_timer()
    check_the_journey_ends()
    check_the_year_event_reports_a_window()
    check_year_tracks_pay_each_day_once()
    check_the_continuous_bonus_needs_the_whole_board()
    check_pass_points_cost_cash()
    check_the_ad_counter_moves()
    check_other_player_is_this_player()
    check_every_player_route_answers()
    print("\nall player-event checks passed")
