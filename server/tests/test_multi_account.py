"""Boards, matchmaking and other-player lookups across more than one account.

Every one of these used to read only the current save, so the requesting player
was the entire world: rank 1 of one, matched against their own deck, and
/player/other answered with themselves no matter whose id was asked for. With two
real accounts in the DB the board must rank both, matchmaking must offer the other
one, and /player/other must return the account whose id was passed.

The single-account case is covered by test_all_routes_respond (one row, rank 1);
this is specifically the multi-account behaviour that was missing.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"
playerdb.init()

import server


def _mk(uid, account_id, name, **kv):
    st = server.copy.deepcopy(server.DEFAULT_PLAYER)
    st["uid"] = uid
    st["accountId"] = account_id
    st["name"] = name
    st.update(kv)
    playerdb.save(uid, st)
    return st


def _as(uid):
    """Run the next calls as this player, the way the middleware binds identity."""
    server.CURRENT_UID.set(uid)


def check_board_ranks_every_account_not_just_the_caller():
    _mk("u-low", 111, "Low", pvpScore=800)
    _mk("u-high", 222, "High", pvpScore=1500)
    _as("u-low")
    out = server.r_pvp_ranking({}, server.load_state())
    ranks = [(r["userName"], r["rank"]) for r in out["ranking"]]
    assert ("High", 1) in ranks and ("Low", 2) in ranks, ranks
    assert out["playerRank"]["userName"] == "Low", "caller's own row is wrong"
    assert out["playerRank"]["rank"] == 2, "caller is not ranked against the other"
    print(f"ok board: {ranks}, caller is Low at rank 2")


def check_other_player_resolves_the_requested_id():
    _as("u-low")
    out = server.r_player_other({"targetId": 222}, server.load_state())
    assert out["name"] == "High", f"asked for 222, got {out['name']}"
    mine = server.r_player_other({"targetId": 111}, server.load_state())
    assert mine["name"] == "Low"
    unknown = server.r_player_other({"targetId": 999999}, server.load_state())
    assert unknown["name"] == "Low", "unknown id should fall back to the caller"
    print("ok other: id 222 -> High, 111 -> Low, unknown -> caller")


def check_matchmaking_offers_a_real_opponent():
    _as("u-low")
    targets = server.r_arena_matching({}, server.load_state())["targets"]
    names = {t["playerName"] for t in targets}
    assert "High" in names, f"no real opponent offered: {names}"
    assert "Low" not in names, "the caller was offered as their own opponent"
    print(f"ok match: opponents {names}")


def check_solo_server_is_unchanged():
    """One account -> the board is just [you, rank 1] and matchmaking trains you
    against yourself, exactly as before."""
    solo = Path(tempfile.mkdtemp()) / "solo.db"
    playerdb.DB_PATH = solo
    playerdb.init()
    _mk("only", 1, "Solo", pvpScore=1000)
    _as("only")
    out = server.r_pvp_ranking({}, server.load_state())
    assert len(out["ranking"]) == 1 and out["ranking"][0]["rank"] == 1
    targets = server.r_arena_matching({}, server.load_state())["targets"]
    assert len(targets) == 1 and targets[0]["playerName"] == "Solo"
    print("ok solo: one row rank 1, matched against self - unchanged")


if __name__ == "__main__":
    check_board_ranks_every_account_not_just_the_caller()
    check_other_player_resolves_the_requested_id()
    check_matchmaking_offers_a_real_opponent()
    check_solo_server_is_unchanged()
    print("\nall multi-account checks passed")
