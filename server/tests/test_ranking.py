"""Leaderboards.

All twelve boards answered an empty auto-generated model, so each rendered as a
blank list with no row for the player either. There is nobody else on a private
server, so the honest board is one row: you, first.

An empty `ranking` with a filled `playerRank` is not equivalent - several panels
scan the list to find themselves and show "unranked" when they cannot - so the two
must agree, which is the thing worth asserting.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

from tests.seed import one_account
one_account()          # multiplayer needs a session; load_state() has no fallback
import server

BOARDS = {
    "/ranking/ranking": server.r_ranking,
    "/ranking/pvp-ranking": server.r_pvp_ranking,
    "/ranking/colosseum-ranking": server.r_colosseum_ranking,
    "/ranking/roguelike-ranking": server.r_roguelike_ranking,
    "/ranking/challenge-mode-ranking": server.r_challenge_ranking,
}


def check_every_ranking_route_is_wired():
    routed = [p for p in server.DYNAMIC_OVERRIDES if p.startswith("/ranking/")]
    import route_coverage
    client = [p for p in route_coverage.client_paths() if p.startswith("/ranking/")]
    missing = sorted(set(client) - set(routed))
    assert not missing, f"the client calls these boards and nothing answers: {missing}"
    print(f"ok wired: {len(routed)} ranking routes for {len(client)} the client calls")


def check_player_appears_in_their_own_board():
    st = server.load_state()
    for path, fn in BOARDS.items():
        out = fn({}, st)
        assert out["ranking"], f"{path} returned an empty board"
        assert out["playerRank"], f"{path} has no player row"
        assert out["ranking"][0]["accountId"] == out["playerRank"]["accountId"], \
            f"{path}: the listed row is a different account from playerRank"
        assert out["ranking"][0]["rank"] == 1, f"{path}: the only player is not first"
        assert out["playerRank"]["userName"], f"{path}: the player row has no name"
    print(f"ok rows: {len(BOARDS)} boards each list the player at rank 1")


def check_player_row_is_a_copy():
    """playerRank and ranking[0] must not be the same object, or a client-side edit to
    one silently rewrites the other after serialisation round-trips in tests."""
    out = server.r_pvp_ranking({}, server.load_state())
    assert out["playerRank"] is not out["ranking"][0]
    out["playerRank"]["rank"] = 99
    assert out["ranking"][0]["rank"] == 1, "the two rows share state"
    print("ok copy: playerRank is a separate row")


def check_generic_board_carries_a_deck():
    st = server.load_state()
    out = server.r_ranking({}, st)
    deck = out["ranking"][0]["deck"]
    assert deck, "the generic board draws hero portraits and got none"
    assert all(isinstance(u, int) and u > 0 for u in deck), f"bad deck {deck}"
    known = set(st.get("cards", {}))
    assert all(str(u) in known for u in deck), "the board lists heroes the player has not got"
    print(f"ok deck: {len(deck)} heroes on the generic board")


def check_deck_falls_back_to_a_filled_preset():
    st = server.load_state()
    presets = st.get("decks") or []
    filled = next(i for i, d in enumerate(presets) if d.get("deck"))
    empty = next(i for i, d in enumerate(presets) if not d.get("deck"))
    st["currentDeckPreset"] = empty
    server.save_state(st)
    deck = server.r_ranking({}, server.load_state())["ranking"][0]["deck"]
    assert deck, f"preset {empty} is empty and the board fell back to nothing"
    st["currentDeckPreset"] = filled
    server.save_state(st)
    print(f"ok fallback: empty preset {empty} still draws a deck")


def check_scores_track_state():
    st = server.load_state()
    st["colosseumScore"] = 4321
    st["rogueLikeScore"] = 77
    server.save_state(st)
    assert server.r_colosseum_ranking({}, server.load_state())["playerRank"]["score"] == 4321
    rl = server.r_roguelike_ranking({}, server.load_state())["playerRank"]
    assert rl["score"] == 77
    assert "building" in rl, "the roguelike row is missing its building field"
    print("ok scores: boards read the player's own score, not a constant")


def check_clan_board_is_empty_without_a_clan():
    st = server.load_state()
    st.pop("clanId", None)
    server.save_state(st)
    out = server.r_clan_point_ranking({}, server.load_state())
    assert out["ranking"] == [], "a player in no clan was listed on the clan board"
    assert out["playerClanRank"]["clanId"] == 0
    print("ok clan: no clan, no row")


def check_unit_statistics_invents_nothing():
    out = server.r_unit_statistics({}, server.load_state())
    assert out == {"topPotentialUsage": [], "topTreasureUsage": [], "topAccessoryUsage": []}, \
        "usage rates were invented from a one-player sample"
    print("ok stats: no fabricated usage rates")


if __name__ == "__main__":
    check_every_ranking_route_is_wired()
    check_player_appears_in_their_own_board()
    check_player_row_is_a_copy()
    check_generic_board_carries_a_deck()
    check_deck_falls_back_to_a_filled_preset()
    check_scores_track_state()
    check_clan_board_is_empty_without_a_clan()
    check_unit_statistics_invents_nothing()
    print("\nall ranking checks passed")
