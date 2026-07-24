"""The four seasonal mini-games: tycoon, stocks, marble, event cards.

All 23 routes answered an empty auto-generated model, which for these means null
lists and null sub-models - and each of these panels walks those before it checks
whether the event is running at all.

Three of the four have a window in master data and every window has closed, so the
right answer is a well-formed "no event", not an empty body. Territory Tycoon is
the exception: its tokens are ordinary inventory rows, so its numbers are real and
have to agree with the inventory the rest of the server reads.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import server

MODES = ("/territory-tycoon", "/stock-event", "/kg-marble", "/event-card-collecting")


def _fresh():
    st = server.load_state()
    st["inventory"] = {"itemIds": [], "counts": []}
    for k in ("tycoonStoredGold", "stockTokens", "marblePlayer"):
        st.pop(k, None)
    server.save_state(st)
    return server.load_state()


def check_every_seasonal_route_is_wired():
    import route_coverage
    client = [p for p in route_coverage.client_paths()
              if any(p.startswith(m) for m in MODES)]
    routed = set(server.DYNAMIC_OVERRIDES)
    missing = sorted(p for p in client if p not in routed)
    assert not missing, f"nothing answers: {missing}"
    print(f"ok wired: {len(client)} seasonal-mode routes")


def check_tycoon_tokens_are_the_inventory():
    st = _fresh()
    server._grant_reward(st, "Item", server.TYCOON_TOKENS["silverToken"], 7)
    server.save_state(st)
    out = server.r_tycoon_tokens({}, server.load_state())
    assert out["silverToken"] == 7, f"the panel reads {out['silverToken']}, inventory has 7"
    assert out["bronzeToken"] == 0 and out["goldToken"] == 0
    print("ok tycoon: token counts come from the real inventory")


def check_collecting_gold_moves_it_into_the_inventory():
    st = _fresh()
    st["tycoonStoredGold"] = 4
    server.save_state(st)
    out = server.r_tycoon_collect_gold({}, server.load_state())
    assert out["goldToken"] == 4, f"collected {out['goldToken']}"
    assert out["storedGoldToken"] == 0, "the bank was not emptied"

    again = server.r_tycoon_collect_gold({}, server.load_state())
    assert again["goldToken"] == 4, "collecting an empty bank minted a token"
    print("ok tycoon gold: 4 banked -> 4 held, an empty bank pays nothing")


def check_the_tycoon_player_block_is_complete():
    out = server.r_tycoon_player({}, server.load_state())
    for key in ("level", "bronzeToken", "silverToken", "goldToken",
                "storedGoldToken", "skipRewardUsedCount", "buildings"):
        assert key in out, f"the tycoon block is missing {key}"
    assert isinstance(out["buildings"], list), "buildings is not a list"
    print(f"ok tycoon block: {len(out)} fields, buildings is a list")


def check_the_stock_event_reports_a_closed_event():
    st = _fresh()
    out = server.r_stock_attendance({}, server.load_state())
    assert out["rewardTokenCount"] == 0, "a closed event paid a daily wage"
    assert out["nextDailyAttendanceDate"], "the panel has no next date to count down to"

    hint = server.r_stock_buy_hint({}, server.load_state())
    assert hint["hint"] is None, "a hint was invented with no round running"
    assert hint["currentTokenCount"] == st.get("stockTokens", 0), \
        "buying a hint that does not exist still charged tokens"

    info = server.r_stock_my_info({}, server.load_state())
    assert isinstance(info["hints"], list) and isinstance(info["portfolios"], list), \
        "a null list here is dereferenced before the panel checks the event"
    print("ok stocks: closed event, no wage, no hint, no null lists")


def check_the_stock_board_lists_the_player():
    out = server.r_stock_ranking({}, server.load_state())
    assert out["ranking"], "the board is empty"
    assert out["playerRanking"]["userRank"] == 1
    assert out["playerRanking"]["profile"]["userName"], "the row has no name"
    print("ok stock board: one row, the player, rank 1")


def check_the_marble_board_is_never_null():
    out = server.r_marble({}, server.load_state())
    assert out["init"] is False, "a board was handed out with no event running"
    m = out["kgMarbleModel"]
    assert m is not None, "the board model is null - the panel walks it before init"
    for key in ("boardData", "boardExecuted", "rewards", "passRewards",
                "executeEvents"):
        assert isinstance(m[key], list), f"{key} is {type(m[key])}"
    assert isinstance(out["diceValues"], list)
    print(f"ok marble: init False, {len(m)} model fields, every list present")


def check_the_marble_token_sticks():
    _fresh()
    server.r_marble_set_player({"player": 2}, server.load_state())
    assert server.r_marble({}, server.load_state())["kgMarbleModel"]["player"] == 2, \
        "the chosen token was not kept"
    print("ok marble token: the choice sticks")


def check_event_cards_report_no_collection():
    out = server.r_event_cards({}, server.load_state())
    assert out["collectionStates"] == {} and out["eventCardCounts"] == {}
    assert out["collectionCompleted"] is False
    wrapped = server.r_event_cards_reward({}, server.load_state())
    assert wrapped["playerEventCardCollectingResponseModel"] == out, \
        "the wrapped model disagrees with the plain one"
    assert wrapped["rewardListData"]["rewardList"] == [], "a closed season paid out"
    print("ok event cards: season 55 is over, nothing collected, nothing paid")


def check_no_seasonal_route_returns_a_null_container():
    """The whole point of this wave: no null list, dict or sub-model anywhere."""
    _fresh()
    bad = []

    def scan(path, node, where=""):
        if node is None and where:
            bad.append(f"{path}{where}")
        elif isinstance(node, dict):
            for k, v in node.items():
                scan(path, v, f"{where}.{k}")

    for path, fn in server.DYNAMIC_OVERRIDES.items():
        if not any(path.startswith(m) for m in MODES):
            continue
        out = fn({}, server.load_state())
        assert isinstance(out, dict), f"{path} returned {type(out)}"
        scan(path, out)
    # Legitimately null: `hint` (no round to hint at), and the three optional
    # sub-results every _reward_list_data carries - the client reads those as
    # "this reward was not an artifact/treasure/accessory".
    allowed = (".hint", ".artifactResult", ".treasureResult", ".accessoryResult")
    bad = [b for b in bad if not b.endswith(allowed)]
    assert not bad, f"null containers the client would dereference: {bad}"
    print("ok nulls: every seasonal route answers with real containers")


if __name__ == "__main__":
    check_every_seasonal_route_is_wired()
    check_tycoon_tokens_are_the_inventory()
    check_collecting_gold_moves_it_into_the_inventory()
    check_the_tycoon_player_block_is_complete()
    check_the_stock_event_reports_a_closed_event()
    check_the_stock_board_lists_the_player()
    check_the_marble_board_is_never_null()
    check_the_marble_token_sticks()
    check_event_cards_report_no_collection()
    check_no_seasonal_route_returns_a_null_container()
    print("\nall seasonal-mode checks passed")
