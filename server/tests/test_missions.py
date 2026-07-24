"""Mission listing, progress and reward claiming.

/mission answered `{"missions": []}`, so the mission tab was empty and its claim
button did nothing.

The failure worth guarding against is the opposite one: a progress evaluator that
reads unknown conditions as satisfied hands the player every reward in the game on
first login, and unlike an under-reporting tab that is not recoverable.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import missions
import server


def _fresh():
    st = server.load_state()
    st["inventory"] = {"itemIds": [], "counts": []}
    st["counters"] = {}
    st["claimedMissions"] = []
    st["cards"] = {}
    st["accessories"] = []
    st["gold"] = st["cash"] = st["heart"] = 0
    # A brand-new account is level 1. The seeded save is level 100, and
    # CastleLevel missions read off the account level (본성 = the main castle,
    # whose level IS the player level), so leaving it at 100 makes 58 missions
    # legitimately complete and hides whether the evaluator works.
    st["level"] = 1
    server.save_state(st)
    return st


def check_listing():
    out = server.r_mission({}, _fresh())
    assert out["missions"], "the mission list is empty"
    ids = [m["missionId"] for m in out["missions"]]
    assert len(set(ids)) == len(ids), "duplicate mission ids in the listing"
    for m in out["missions"]:
        assert m["goalValue"] >= 1
        assert 0 <= m["value"] <= m["goalValue"], f"{m}: value out of range"
    print(f"ok listing: {len(out['missions'])} missions")


def check_nothing_complete_on_a_blank_save():
    out = server.r_mission({}, _fresh())
    done = [m["missionId"] for m in out["missions"] if m["clear"]]
    assert not done, f"{len(done)} missions already complete on a blank save: {done[:5]}"
    print("ok blank save: nothing is pre-cleared")


def check_counter_advances_a_mission():
    """ClearGame is the plainest server-observable condition: /game/complete drives it."""
    st = _fresh()
    target = next(m for m in missions.load(server.XML_DIR).values()
                  if missions.condition(m) == "ClearGame")
    goal = missions.goal_value(target)
    for _ in range(goal):
        server.r_game_complete({"win": True, "theme": 1, "stage": 1},
                               server.load_state())
    st = server.load_state()
    assert st["counters"]["clearGame"] == goal, \
        f"clearGame is {st['counters'].get('clearGame')} after {goal} wins"
    row = next(m for m in server.r_mission({}, st)["missions"]
               if m["missionId"] == int(target.get("ID")))
    assert row["clear"], f"mission {target.get('ID')} not cleared at {goal}/{goal}"
    print(f"ok progress: mission {target.get('ID')} cleared after {goal} wins")


def check_claim_grants_and_is_idempotent():
    st = _fresh()
    target = next(m for m in missions.load(server.XML_DIR).values()
                  if missions.condition(m) == "ClearGame")
    mid = int(target.get("ID"))
    goal = missions.goal_value(target)
    for _ in range(goal):
        server.r_game_complete({"win": True, "theme": 1, "stage": 1}, server.load_state())

    before = server.load_state()
    out = server.r_mission_reward_all({"missionIdList": [mid]}, server.load_state())
    got = out["rewardListResponseData"]["rewardList"]
    assert got, f"claiming mission {mid} granted nothing"
    st = server.load_state()
    for r in missions.rewards_of(target):
        if r["type"] == "Cash":
            assert st["cash"] == before.get("cash", 0) + r["count"], \
                f"cash {before.get('cash', 0)} -> {st['cash']}, expected +{r['count']}"

    # Claiming twice must not pay twice.
    purse = (st["gold"], st["cash"], st["heart"])
    server.r_mission_reward_all({"missionIdList": [mid]}, server.load_state())
    st = server.load_state()
    assert (st["gold"], st["cash"], st["heart"]) == purse, "a second claim paid out again"
    assert st["claimedMissions"].count(mid) == 1
    print(f"ok claim: mission {mid} paid {len(got)} reward(s), second claim was a no-op")


def check_uncleared_cannot_be_claimed():
    st = _fresh()
    out = server.r_mission({}, st)
    unclear = next(m["missionId"] for m in out["missions"] if not m["clear"])
    server.r_mission_reward_all({"missionIdList": [unclear]}, server.load_state())
    st = server.load_state()
    assert unclear not in st["claimedMissions"], f"claimed uncleared mission {unclear}"
    assert st["gold"] == 0 and st["cash"] == 0, "an uncleared mission paid out"
    print(f"ok gate: uncleared mission {unclear} pays nothing")


def check_reward_all_only_pays_cleared():
    st = _fresh()
    for _ in range(3):
        server.r_game_complete({"win": True, "theme": 1, "stage": 1}, server.load_state())
    st = server.load_state()
    eligible = {m["missionId"] for m in server.r_mission({}, st)["missions"] if m["clear"]}
    server.r_mission_reward_all({}, server.load_state())
    st = server.load_state()
    assert set(st["claimedMissions"]) == eligible, \
        (f"reward-all claimed {len(st['claimedMissions'])} but "
         f"{len(eligible)} were cleared")
    print(f"ok reward-all: paid exactly the {len(eligible)} cleared missions")


def check_key_rewards_resolve():
    """A Key reward names a ShopItem, not an inventory row. Granting it unresolved
    would put item 0 in the inventory, which the client renders as a blank slot."""
    st = _fresh()
    granted = [server._grant_mission_reward(st, r)
               for m in missions.load(server.XML_DIR).values()
               for r in missions.rewards_of(m) if r["type"] == "Key"]
    assert granted, "no Key rewards in the mission set - this check is vacuous"
    assert not [g for g in granted if g["type"] == "Key"], \
        "some Key rewards did not resolve to an item or an artifact box"
    assert 0 not in [i for i in st["inventory"]["itemIds"]], "item 0 landed in the inventory"
    boxes = st.get("artifactBoxKey") or []
    print(f"ok keys: {len(granted)} Key rewards resolved, artifactBoxKey={boxes}")


if __name__ == "__main__":
    check_listing()
    check_nothing_complete_on_a_blank_save()
    check_counter_advances_a_mission()
    check_claim_grants_and_is_idempotent()
    check_uncleared_cannot_be_claimed()
    check_reward_all_only_pays_cleared()
    check_key_rewards_resolve()
    print("\nall mission checks passed")
