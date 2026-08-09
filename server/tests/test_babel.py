"""Babel: the six towers.

/babel is the mode's only route and it answered an empty model, so the tower select
screen listed nothing - no floors, no progress, nothing openable.

Two things fail quietly here. The weekday rota is Sunday-first (C# DayOfWeek), and
reading it Monday-first shifts every tower by a day, which offers the player a
battle whose stage the client will not load. And nothing but /game/complete advances
a tower, so a floor reward that pays on every run rather than on a new best turns
floor 1 of an always-open tower into an unlimited faucet.
"""
import datetime, sys, tempfile
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import babel
from tests.seed import one_account
one_account()          # multiplayer mode does not mint a save; give load_state() one
import server


def _fresh():
    st = server.load_state()
    st.pop("babel", None)
    st["inventory"] = {"itemIds": [], "counts": []}
    st["gold"] = 0
    server.save_state(st)
    return st


def check_every_tower_is_listed():
    out = server.r_babel({}, _fresh())["babels"]
    towers = babel.towers(server.XML_DIR)
    assert len(out) == len(towers), f"{len(out)} towers listed, {len(towers)} exist"
    assert [b["id"] for b in out] == sorted(towers), "the towers are out of order"
    assert all(b["maxClearedFloor"] == 0 for b in out), "a fresh save has cleared floors"
    for b in out:
        assert b["availableAt"], f"tower {b['id']} never opens"
    print(f"ok list: {len(out)} towers, "
          f"{sum(b['available'] for b in out)} open today")


def check_the_rota_is_sunday_first():
    """C# DateTime.DayOfWeek puts Sunday at 0. Off by one and every tower shifts."""
    assert babel.weekday(datetime.datetime(2026, 7, 26)) == 0, "Sunday is not 0"
    assert babel.weekday(datetime.datetime(2026, 7, 27)) == 1, "Monday is not 1"
    assert babel.weekday(datetime.datetime(2026, 8, 1)) == 6, "Saturday is not 6"

    # Availability must follow the tower's own list on a specific day, not today's.
    towers = babel.towers(server.XML_DIR)
    picky = next(bid for bid, t in towers.items() if len(t["openDays"]) < 7)
    for day in range(7):
        when = datetime.datetime(2026, 7, 26) + datetime.timedelta(days=day)
        assert babel.available(picky, when, server.XML_DIR) == \
            (babel.weekday(when) in towers[picky]["openDays"]), \
            f"tower {picky} availability disagrees with OpenDays on {when.date()}"
    print(f"ok rota: tower {picky} opens on {towers[picky]['openDays']}, Sunday-first")


def check_next_open_lands_on_an_open_day():
    towers = babel.towers(server.XML_DIR)
    for bid, t in towers.items():
        for day in range(7):
            when = datetime.datetime(2026, 7, 26) + datetime.timedelta(days=day)
            nxt = babel.next_open(bid, when, server.XML_DIR)
            assert nxt is not None, f"tower {bid} never opens after {when.date()}"
            assert babel.weekday(nxt) in t["openDays"], \
                f"tower {bid} next opens {nxt.date()}, not in {t['openDays']}"
            assert nxt >= when.replace(hour=0, minute=0, second=0, microsecond=0), \
                f"tower {bid} next open is in the past"
    print("ok next: every tower's next opening is on one of its own days")


def check_a_floor_pays_once():
    st = _fresh()
    theme = babel.towers(server.XML_DIR)[1]["theme"]
    want = babel.floor_reward(theme, 1, server.XML_DIR)
    assert want, "tower 1 floor 1 pays nothing in the master data"

    out = server.r_game_complete({"win": True, "theme": theme, "stage": 1},
                                 server.load_state())
    got = out.get("rewardListData", {}).get("rewardList", [])
    assert len(got) == len(want), f"floor 1 paid {len(got)}, table lists {len(want)}"
    assert server.r_babel({}, server.load_state())["babels"][1]["maxClearedFloor"] == 1

    again = server.r_game_complete({"win": True, "theme": theme, "stage": 1},
                                   server.load_state())
    assert not again.get("rewardListData"), "re-running a cleared floor paid again"
    print(f"ok reward: theme {theme} floor 1 paid {len(got)} once")


def check_progress_only_moves_forward():
    st = _fresh()
    theme = babel.towers(server.XML_DIR)[1]["theme"]
    server.r_game_complete({"win": True, "theme": theme, "stage": 5}, server.load_state())
    server.r_game_complete({"win": True, "theme": theme, "stage": 2}, server.load_state())
    floor = server.r_babel({}, server.load_state())["babels"][1]["maxClearedFloor"]
    assert floor == 5, f"an easier floor moved progress to {floor}"

    # A loss must not count, and neither must a floor past the top of the tower.
    server.r_game_complete({"win": False, "theme": theme, "stage": 9}, server.load_state())
    assert server.r_babel({}, server.load_state())["babels"][1]["maxClearedFloor"] == 5, \
        "a lost run advanced the tower"
    top = babel.towers(server.XML_DIR)[1]["maxFloor"]
    server.r_game_complete({"win": True, "theme": theme, "stage": top + 1},
                           server.load_state())
    assert server.r_babel({}, server.load_state())["babels"][1]["maxClearedFloor"] == 5, \
        f"a floor above the tower's {top} was accepted"
    print(f"ok progress: best floor 5 held against a lower clear, a loss and floor {top + 1}")


def check_other_modes_do_not_touch_the_towers():
    st = _fresh()
    server.r_game_complete({"win": True, "theme": 12, "stage": 40}, server.load_state())
    assert all(b["maxClearedFloor"] == 0
               for b in server.r_babel({}, server.load_state())["babels"]), \
        "a story clear advanced a tower"
    print("ok isolation: a story clear leaves every tower at zero")


if __name__ == "__main__":
    check_every_tower_is_listed()
    check_the_rota_is_sunday_first()
    check_next_open_lands_on_an_open_day()
    check_a_floor_pays_once()
    check_progress_only_moves_forward()
    check_other_modes_do_not_touch_the_towers()
    print("\nall babel checks passed")
