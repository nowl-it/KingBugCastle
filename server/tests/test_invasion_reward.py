"""Invasion first-clear rewards.

The three /invasion/reward routes fell through to the auto-generated model, so the
invasion reward track showed nothing and claiming did nothing.

The failure that matters here is a claim that can be repeated: rewardState is a
bitmask, and getting the bit wrong turns the whole 200-row track into an infinite
source of gems and keys.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import server


def _fresh():
    st = server.load_state()
    st["invasionRewardState"] = {}
    st["inventory"] = {"itemIds": [], "counts": []}
    st["gold"] = st["cash"] = st["heart"] = 0
    server.save_state(st)
    return st


def check_catalog():
    out = server.r_invasion_reward({}, _fresh())
    rows = out["rewardDatas"]
    assert len(rows) == len(server.INVASION_REWARDS), "listing dropped rows"
    for r in rows:
        assert r["theme"] >= 1 and 1 <= r["difficulty"] <= 5, r
        assert r["rewards"] or r["passRewards"], f"theme {r['theme']} d{r['difficulty']} is empty"
        assert not r["received"]
    print(f"ok catalog: {len(rows)} theme/difficulty rows, none claimed on a fresh save")


def check_claim_once():
    st = _fresh()
    out = server.r_invasion_reward({"theme": 1, "difficulty": 1, "pass": 1}, st)
    got = out["rewardListData"]["rewardList"]
    assert got, "claiming theme 1 d1 granted nothing"
    st = server.load_state()
    assert st["cash"] == 10, f"cash is {st['cash']}, expected the 10 from theme 1 d1"
    assert out["rewardState"] == 1, f"rewardState {out['rewardState']}, expected bit 0 set"

    again = server.r_invasion_reward({"theme": 1, "difficulty": 1, "pass": 1},
                                     server.load_state())
    assert not again["rewardListData"]["rewardList"], "the same reward was claimed twice"
    assert server.load_state()["cash"] == 10, "a repeat claim paid out again"
    print(f"ok claim: {len(got)} rewards once, second claim is a no-op")


def check_bitmask_is_per_difficulty():
    """One bit per difficulty - a shared bit would lock the whole theme after d1."""
    st = _fresh()
    for d in (1, 2, 3):
        out = server.r_invasion_reward({"theme": 1, "difficulty": d}, server.load_state())
        assert out["rewardListData"]["rewardList"], f"theme 1 d{d} granted nothing"
    assert server.load_state()["invasionRewardState"]["1"] == 0b111, \
        f"mask is {bin(server.load_state()['invasionRewardState']['1'])}, expected 0b111"
    print("ok bitmask: difficulties 1-3 claim independently")


def check_locked_difficulty_refused():
    unlocked = server.RCFG["player"]["invasionUnlockedDifficulty"]
    st = _fresh()
    out = server.r_invasion_reward({"theme": 1, "difficulty": unlocked + 1}, st)
    assert not out["rewardListData"]["rewardList"], \
        f"difficulty {unlocked + 1} paid out despite only {unlocked} being unlocked"
    assert not server.load_state().get("invasionRewardState", {}).get("1")
    print(f"ok gate: difficulty {unlocked + 1} refused (unlocked = {unlocked})")


def check_pass_rewards_are_opt_in():
    st = _fresh()
    plain = server.r_invasion_reward({"theme": 1, "difficulty": 1},
                                     st)["rewardListData"]["rewardList"]
    st = _fresh()
    withpass = server.r_invasion_reward({"theme": 1, "difficulty": 1, "pass": 1},
                                        st)["rewardListData"]["rewardList"]
    assert len(withpass) > len(plain), \
        f"pass=1 gave {len(withpass)} rewards, same as without ({len(plain)})"
    print(f"ok pass: {len(plain)} rewards without, {len(withpass)} with")


def check_receive_all_then_nothing_left():
    st = _fresh()
    out = server.r_invasion_reward_all({"pass": 1}, st)
    n = len(out["rewardListData"]["rewardList"])
    assert n > 100, f"receive-all only paid {n} rewards across 200 rows"
    again = server.r_invasion_reward_all({"pass": 1}, server.load_state())
    assert not again["rewardListData"]["rewardList"], "receive-all paid out twice"
    listed = server.r_invasion_reward({}, server.load_state())["rewardDatas"]
    unlocked = server.RCFG["player"]["invasionUnlockedDifficulty"]
    left = [r for r in listed if not r["received"] and r["difficulty"] <= unlocked]
    assert not left, f"{len(left)} unlocked rows still unclaimed after receive-all"
    print(f"ok receive-all: {n} rewards, idempotent, nothing unlocked left")


def check_no_item_zero():
    """A Key reward names a ShopItem; unresolved it would grant item 0."""
    st = _fresh()
    server.r_invasion_reward_all({"pass": 1}, st)
    st = server.load_state()
    assert 0 not in st["inventory"]["itemIds"], "item 0 landed in the inventory"
    print(f"ok items: {len(st['inventory']['itemIds'])} distinct items, none id 0")


if __name__ == "__main__":
    check_catalog()
    check_claim_once()
    check_bitmask_is_per_difficulty()
    check_locked_difficulty_refused()
    check_pass_rewards_are_opt_in()
    check_receive_all_then_nothing_left()
    check_no_item_zero()
    print("\nall invasion reward checks passed")
