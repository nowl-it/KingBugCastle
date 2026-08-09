"""Story-mode Challenge reward track.

The three /story-mode/challenge routes fell through to the auto-generated model, so
the panel showed an empty track and neither button paid out. This is the mode Season
71 added boss unit 30000000 for.

rewardStates is a positional List<int> parallel to the track's document order, so the
failure to guard is an index that drifts: a claim would then pay out the wrong entry
and mark a different one as taken.
"""
import sys, tempfile
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import challenge
from tests.seed import one_account
one_account()          # multiplayer needs a session; load_state() has no fallback
import server


def _fresh(best=0, battles=0):
    st = server.load_state()
    st["challenge"] = {"bestDifficulty": best, "clearedBattles": battles,
                       "claimed": [], "dailyClaimedOn": ""}
    st["inventory"] = {"itemIds": [], "counts": []}
    st["gold"] = st["cash"] = 0
    server.save_state(st)
    return st


def check_info_shape():
    out = server.r_challenge_info({}, _fresh())
    track = challenge.track(xml_dir=server.XML_DIR)
    assert len(out["rewardStates"]) == len(track), \
        f"rewardStates has {len(out['rewardStates'])} entries for a {len(track)}-entry track"
    assert set(out["rewardStates"]) == {0}, "something is claimable at zero progress"
    assert out["unlockedDifficulty"] >= 1 and out["seasonEnabled"]
    print(f"ok info: season {challenge.current_season(server.XML_DIR)}, "
          f"{len(track)} entries, all locked at zero progress")


def check_states_track_progress():
    st = _fresh(best=5, battles=1)
    states = server.r_challenge_info({}, st)["rewardStates"]
    track = challenge.track(xml_dir=server.XML_DIR)
    for i, e in enumerate(track):
        want = 1 if challenge.earned(e, 5, 1) else 0
        assert states[i] == want, \
            f"entry {i} ({e['kind']}={e['value']}) state {states[i]}, expected {want}"
    assert 1 in states, "no entry became claimable at difficulty 5"
    print(f"ok progress: {states.count(1)} of {len(track)} claimable at difficulty 5")


def check_claim_pays_the_named_index():
    """The index the client sends must select that exact track entry."""
    st = _fresh(best=21, battles=99)
    track = challenge.track(xml_dir=server.XML_DIR)
    idx = next(i for i, e in enumerate(track) if e["kind"] == "ClearDifficulty")
    want = track[idx]["rewards"]
    out = server.r_challenge_reward({"index": idx}, st)
    got = out["rewardResponse"]["rewardList"]
    assert len(got) == len(want), f"entry {idx} pays {len(want)} rewards, got {len(got)}"
    assert out["rewardStates"][idx] == 2, f"entry {idx} not marked claimed"
    assert out["rewardStates"].count(2) == 1, "claiming one entry marked several"
    print(f"ok index: entry {idx} paid exactly its own {len(got)} reward(s)")


def check_claim_is_idempotent():
    st = _fresh(best=21, battles=99)
    first = server.r_challenge_reward({}, st)["rewardResponse"]["rewardList"]
    assert first, "claiming everything earned paid nothing"
    st = server.load_state()
    purse = (st["gold"], dict(zip(st["inventory"]["itemIds"], st["inventory"]["counts"])))
    again = server.r_challenge_reward({}, server.load_state())["rewardResponse"]["rewardList"]
    st = server.load_state()
    assert not again, "the track paid out a second time"
    assert (st["gold"],
            dict(zip(st["inventory"]["itemIds"], st["inventory"]["counts"]))) == purse
    print(f"ok claim: {len(first)} rewards once, second pass is a no-op")


def check_unearned_cannot_be_claimed():
    st = _fresh(best=0, battles=0)
    out = server.r_challenge_reward({}, st)
    assert not out["rewardResponse"]["rewardList"], "an unearned track paid out"
    assert set(out["rewardStates"]) == {0}
    print("ok gate: nothing claimable at zero progress")


def check_daily_once_per_day():
    st = _fresh(best=11)
    first = server.r_challenge_daily({}, st)["rewardResponse"]["rewardList"]
    assert first, "the daily reward paid nothing at difficulty 11"
    st = server.load_state()
    purse = st["gold"]
    again = server.r_challenge_daily({}, server.load_state())["rewardResponse"]["rewardList"]
    assert not again, "the daily reward paid twice in one day"
    assert server.load_state()["gold"] == purse
    print(f"ok daily: {len(first)} rewards, second claim same day is a no-op")


def check_daily_tier_matches_difficulty():
    """The tier paid must be the highest one at or below the player's best."""
    tiers = challenge.daily_track(xml_dir=server.XML_DIR)
    best = 3
    want = tiers[max(d for d in tiers if d <= best)]
    st = _fresh(best=best)
    got = server.r_challenge_daily({}, st)["rewardResponse"]["rewardList"]
    assert len(got) == len(want), f"difficulty {best} paid {len(got)}, tier has {len(want)}"
    # The response carries the client's reward vocabulary (Item -> InventoryItem etc.),
    # the tier table carries the server's - compare through the same translation.
    for w in server._wire_rewards(want):
        assert any(g["type"] == w["type"] and g["count"] == w["count"] for g in got), \
            f"missing {w} from the difficulty {best} tier"
    print(f"ok daily tier: difficulty {best} paid its own tier ({len(got)} rewards)")


def check_game_complete_advances_the_track():
    """Nothing else writes bestDifficulty, so without this hook the track is dead."""
    st = _fresh()
    server.r_game_complete({"win": True, "theme": 4100, "stage": 2, "difficulty": 7},
                           server.load_state())
    cs = server.load_state()["challenge"]
    assert cs["bestDifficulty"] == 7, f"bestDifficulty is {cs['bestDifficulty']}"
    assert cs["clearedBattles"] == 3, f"clearedBattles is {cs['clearedBattles']}"
    # A story win must not touch it - themes below 4000 carry no challenge difficulty.
    server.r_game_complete({"win": True, "theme": 12, "stage": 40, "difficulty": 99},
                           server.load_state())
    cs = server.load_state()["challenge"]
    assert cs["bestDifficulty"] == 7, "a story win advanced the challenge track"
    # And it must never go backwards on an easier clear.
    server.r_game_complete({"win": True, "theme": 4100, "stage": 0, "difficulty": 2},
                           server.load_state())
    cs = server.load_state()["challenge"]
    assert cs["bestDifficulty"] == 7, "an easier clear lowered bestDifficulty"
    print("ok game hook: challenge wins advance the track, story wins do not")


def check_no_item_zero():
    st = _fresh(best=21, battles=99)
    server.r_challenge_reward({}, st)
    server.r_challenge_daily({}, server.load_state())
    ids = server.load_state()["inventory"]["itemIds"]
    assert 0 not in ids, "item 0 landed in the inventory - a Key did not resolve"
    print(f"ok items: {len(ids)} distinct items, none id 0")


if __name__ == "__main__":
    check_info_shape()
    check_states_track_progress()
    check_claim_pays_the_named_index()
    check_claim_is_idempotent()
    check_unearned_cannot_be_claimed()
    check_daily_once_per_day()
    check_daily_tier_matches_difficulty()
    check_game_complete_advances_the_track()
    check_no_item_zero()
    print("\nall challenge checks passed")
