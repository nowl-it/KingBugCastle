"""Colosseum and Arena.

Twenty-two PvP routes answered an empty model, so both panels opened onto nothing
and the score sat at the 1000 the config seeds no matter how many games were played.

The parts that fail quietly: the top five tiers share two scores and are separated
only by a leaderboard bracket in their name, so resolving a tier by score alone
hands out the rank-1 payout (1500 cash) to everyone; tier rewards must pay once,
not once per crossing; and the arena's win steps are cumulative counts, so a save
that reaches step 3 has to be paid for steps 0-3, not step 3 alone.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import colosseum
from tests.seed import one_account
one_account()          # multiplayer mode does not mint a save; give load_state() one
import server


def _fresh():
    st = server.load_state()
    for k in list(st):
        if k.startswith("colosseum") or k.startswith("pvp"):
            st.pop(k)
    st["inventory"] = {"itemIds": [], "counts": []}
    st["cash"] = 0
    server.save_state(st)
    return server.load_state()


def check_every_pvp_route_is_wired():
    import route_coverage
    client = [p for p in route_coverage.client_paths()
              if p.startswith("/colosseum") or p.startswith("/pvp/")]
    handled = route_coverage.handled_paths()
    known = handled["dynamic"] | handled["static"] | handled["direct"]
    missing = sorted(set(client) - known)
    assert not missing, f"the client calls these and nothing answers: {missing}"
    print(f"ok wired: {len(client)} colosseum/pvp routes answered")


def check_a_win_moves_the_score():
    st = _fresh()
    before = server.r_colosseum({}, st)["score"]
    out = server.r_colosseum_complete_round({"win": True}, server.load_state())
    assert out["scoreDelta"] > 0, f"a win paid {out['scoreDelta']}"
    assert out["score"] == before + out["scoreDelta"]
    after = server.r_colosseum({}, server.load_state())
    assert after["score"] == out["score"], "the panel disagrees with the result"
    assert after["winCount"] == 1 and after["loseCount"] == 0
    assert after["gameCount"] == 1

    loss = server.r_colosseum_complete_round({"win": False}, server.load_state())
    assert loss["scoreDelta"] < 0, f"a loss paid {loss['scoreDelta']}"
    assert server.r_colosseum({}, server.load_state())["loseCount"] == 1
    print(f"ok score: win {out['scoreDelta']:+d}, loss {loss['scoreDelta']:+d}")


def check_the_score_never_goes_negative():
    st = _fresh()
    for _ in range(30):
        server.r_colosseum_complete_round({"win": False}, server.load_state())
    out = server.r_colosseum({}, server.load_state())
    floor = colosseum.tiers(server.XML_DIR)[0]["reqScore"]
    assert out["score"] == floor, f"30 losses left the score at {out['score']}"
    assert out["tier"] == colosseum.tiers(server.XML_DIR)[0]["id"], \
        "the bottom score did not resolve to the bottom tier"
    print(f"ok floor: 30 losses bottom out at {out['score']}, not below")


def check_the_tier_follows_the_score():
    st = _fresh()
    ts = colosseum.tiers(server.XML_DIR)
    mid = ts[len(ts) // 2]
    st["colosseumScore"] = mid["reqScore"]
    server.save_state(st)
    out = server.r_colosseum({}, server.load_state())
    assert out["tier"] == mid["id"], f"score {mid['reqScore']} read as tier {out['tier']}"
    print(f"ok tier: score {mid['reqScore']} -> tier {mid['id']} ({mid['name']})")


def check_the_top_tier_needs_rank_not_score():
    """80/81/82 all sit at 2400 and only the name bracket separates them."""
    st = _fresh()
    ts = colosseum.tiers(server.XML_DIR)
    share = [t for t in ts if t["reqScore"] == ts[-1]["reqScore"]]
    assert len(share) > 1, "the top tiers no longer share a score"
    st["colosseumScore"] = ts[-1]["reqScore"] + 1000
    server.save_state(st)
    assert server.r_colosseum({}, server.load_state())["tier"] == share[0]["id"], \
        "an unranked player with a huge score was given the rank-1 tier"
    st = server.load_state()
    st["colosseumRank"] = 1
    server.save_state(st)
    assert server.r_colosseum({}, server.load_state())["tier"] == ts[-1]["id"], \
        "rank 1 was not given the top tier"
    print(f"ok rank: {len(share)} tiers at {ts[-1]['reqScore']}, rank decides")


def check_tier_rewards_pay_once():
    st = _fresh()
    ts = colosseum.tiers(server.XML_DIR)
    st["colosseumScore"] = ts[3]["reqScore"]
    server.save_state(st)
    out = server.r_colosseum_tier_rewards({}, server.load_state())
    paid = out["rewardListResponseData"]["rewardList"]
    assert paid, "reaching tier 4 paid nothing"
    assert out["receivedRewards"] == [t["id"] for t in ts[:4]], \
        f"claimed {out['receivedRewards']}, expected the first four tiers"

    again = server.r_colosseum_tier_rewards({}, server.load_state())
    assert not again["rewardListResponseData"]["rewardList"], \
        "the same tiers paid a second time"
    assert server.r_colosseum({}, server.load_state())["receivedRewards"] == \
        out["receivedRewards"], "the panel lost the claimed list"
    print(f"ok rewards: {len(paid)} paid for 4 tiers, nothing on the re-claim")


def check_tier_rewards_land_in_state():
    st = _fresh()
    ts = colosseum.tiers(server.XML_DIR)
    st["colosseumScore"] = ts[0]["reqScore"]
    server.save_state(st)
    want = ts[0]["rewards"][0]
    assert want["type"] == "Item", f"tier 0 pays {want['type']}, adjust the check"
    server.r_colosseum_tier_rewards({}, server.load_state())
    inv = server.load_state()["inventory"]
    assert want["id"] in inv["itemIds"], "the tier reward never reached the inventory"
    got = inv["counts"][inv["itemIds"].index(want["id"])]
    assert got == want["count"], f"granted {got}, table says {want['count']}"
    print(f"ok grant: item {want['id']} x{got} in the inventory")


def check_arena_win_steps_are_cumulative():
    st = _fresh()
    steps = colosseum.arena_win_steps(server.XML_DIR)
    st["pvpWin"] = steps[2]["winCount"]
    server.save_state(st)
    out = server.r_arena_win_reward({}, server.load_state())
    assert out["winRewardReceived"] == [0, 1, 2], \
        f"reaching step 2 paid {out['winRewardReceived']}, not every step below it"
    total = sum(r["count"] for s in steps[:3] for r in s["rewards"])
    paid = sum(r["count"] for r in out["rewardListResponseData"]["rewardList"])
    assert paid == total, f"paid {paid} tokens, steps 0-2 are worth {total}"
    assert not server.r_arena_win_reward({}, server.load_state()) \
        ["rewardListResponseData"]["rewardList"], "a claimed step paid again"
    print(f"ok arena: {paid} tokens for steps 0-2, nothing on the re-claim")


def check_logs_record_matches_newest_first():
    st = _fresh()
    for win in (True, False, True):
        server.r_colosseum_complete_round({"win": win, "gameId": "g", "round": 3},
                                          server.load_state())
    out = server.r_colosseum_logs({}, server.load_state())
    assert len(out["logList"]) == 3, f"{len(out['logList'])} games logged"
    assert [e["logId"] for e in out["logList"]] == [3, 2, 1], "the log is not newest first"
    assert out["logList"][0]["myScoreDelta"] > 0, "the newest entry lost its delta"
    assert out["logList"][0]["playerDecks"], "a log line has nobody in it"
    assert out["targetUserData"]["userName"], "the log's player block has no name"
    print("ok logs: 3 games, newest first, each with a player row")


def check_the_log_is_capped():
    st = _fresh()
    for _ in range(80):
        server.r_colosseum_complete_round({"win": True}, server.load_state())
    logs = server.r_colosseum_logs({}, server.load_state())["logList"]
    assert len(logs) == 50, f"{len(logs)} entries kept"
    assert logs[0]["logId"] == 80, "capping dropped the newest, not the oldest"
    print(f"ok cap: {len(logs)} of 80 kept, newest retained")


def check_statistics_agree_with_the_panel():
    st = _fresh()
    server.r_colosseum_complete_round({"win": True}, server.load_state())
    server.r_colosseum_complete_round({"win": False}, server.load_state())
    stats = server.r_colosseum_statistics({}, server.load_state())["dataList"][0]
    panel = server.r_colosseum({}, server.load_state())
    assert stats["winCount"] == panel["winCount"] == 1
    assert stats["loseCount"] == panel["loseCount"] == 1
    assert len(stats["countsByRank"]) == 4, "the placement histogram is the wrong length"
    print("ok stats: the statistics tab agrees with the main panel")


def check_the_arena_panel_is_live():
    st = _fresh()
    st["pvpScore"] = 1600
    st["pvpWin"] = 7
    server.save_state(st)
    out = server.r_pvp_info({}, server.load_state())
    assert out["score"] == 1600, f"the arena panel shows {out['score']}"
    assert out["tier"] == colosseum.tier_for(1600, 0, server.XML_DIR)["id"]
    assert out["winCount"] == 7
    assert out["deckInfo"]["score"] == 1600, "the deck block has a different score"
    assert len(out["semiSeasonScoreDatas"]) >= out["semiSeason"], \
        "semiSeasonScoreDatas is shorter than the current semi-season"
    assert len(out["seasonUntilAtDates"]) >= out["semiSeason"], \
        "GetCurrentSeasonUntilAt would index past the end of seasonUntilAtDates"
    print(f"ok arena panel: score {out['score']}, tier {out['tier']}, 7 wins")


def check_the_season_arrays_survive_the_known_index_trap():
    """PvPInfo/PlayerColosseumInfo both index seasonUntilAtDates[semiSeason-1]."""
    for name, fn in (("colosseum", server.r_colosseum), ("arena", server.r_pvp_info)):
        out = fn({}, server.load_state())
        semi = out["semiSeason"]
        assert semi >= 1, f"{name} semiSeason is {semi}"
        for key in ("seasonUntilAtDates", "nextSeasonStartAtDates"):
            assert len(out[key]) >= semi, \
                f"{name} {key} has {len(out[key])} entries for semiSeason {semi}"
    print("ok index: both panels can resolve their own semi-season")


def check_match_routes_answer_without_a_match_server():
    st = server.load_state()
    m = server.r_colosseum_match({}, st)
    assert m["gameId"], "a match with no id"
    assert m["serverAddress"] == "", "an address was invented for a server that is not there"
    c = server.r_colosseum_custom_match({"lobbyId": "abc"}, st)
    assert c["lobbyId"] == "abc" and c["endPoint"] == ""
    assert server.r_colosseum_players({}, st)["colosseumPlayerDataList"][0]["cardInfos"], \
        "the player block has no heroes in it"
    print("ok match: match and custom-match answer, no address invented")


def check_every_pvp_route_answers_on_a_fresh_save():
    _fresh()
    for path, fn in server.DYNAMIC_OVERRIDES.items():
        if not (path.startswith("/colosseum") or path.startswith("/pvp/")):
            continue
        out = fn({}, server.load_state())
        assert isinstance(out, dict), f"{path} returned {type(out)}"
    print("ok safety: every colosseum/pvp route answers on a save that has played nothing")


if __name__ == "__main__":
    check_every_pvp_route_is_wired()
    check_a_win_moves_the_score()
    check_the_score_never_goes_negative()
    check_the_tier_follows_the_score()
    check_the_top_tier_needs_rank_not_score()
    check_tier_rewards_pay_once()
    check_tier_rewards_land_in_state()
    check_arena_win_steps_are_cumulative()
    check_logs_record_matches_newest_first()
    check_the_log_is_capped()
    check_statistics_agree_with_the_panel()
    check_the_arena_panel_is_live()
    check_the_season_arrays_survive_the_known_index_trap()
    check_match_routes_answer_without_a_match_server()
    check_every_pvp_route_answers_on_a_fresh_save()
    print("\nall colosseum checks passed")
