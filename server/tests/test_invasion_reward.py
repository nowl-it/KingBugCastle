"""Invasion first-clear rewards.

The three /invasion/reward routes fell through to the auto-generated model, so the
invasion reward track showed nothing and claiming did nothing.

The failure that matters here is a claim that can be repeated: rewardState is a
bitmask, and getting the bit wrong turns the whole 200-row track into an infinite
source of gems and keys.
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

from tests.seed import one_account
one_account()          # multiplayer needs a session; load_state() has no fallback
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
    assert len(rows) == 16, f"{len(rows)} entries, expected 16 (8 groups + 2 pass-1 + 6 markers)"
    for r in rows:
        assert {"index", "pass", "rewardState"} == set(r), r
        assert r["index"] >= 0 and r["pass"] >= 0 and r["rewardState"] == 0, r
    pairs = [(r["index"], r["pass"]) for r in rows]
    for p in range(8):
        assert (p, p) in pairs, f"no {p} group/marker entry"
    assert (0, 1) in pairs and (2, 1) in pairs, "pass-1 entries for themes 1-20 missing"
    print(f"ok catalog: {len(rows)} RewardData entries {{index, pass, rewardState}}, none claimed")


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


def check_claim_state_reaches_listing():
    """The claim lands in the entry the client's probe actually reads: theme 6 is
    group {index 0, pass 2}, and the client reads bit (d-1) + 5*((theme-1)%10), so
    d3 on theme 6 is bit 2 + 25 = 27 of that entry."""
    st = _fresh()
    server.r_invasion_reward({"theme": 6, "difficulty": 3, "pass": 1}, st)
    rows = {(r["index"], r["pass"]): r for r in server.r_invasion_reward({}, st)["rewardDatas"]}
    entry = rows[(0, 2)]
    assert entry["rewardState"] & (1 << 27), \
        f"theme 6 d3 claim missing from pass-2 entry: {entry}"
    assert not (entry["rewardState"] & (1 << 26)), \
        f"claim bled into the wrong bit: {entry['rewardState']:#b}"
    print("ok state: theme 6 d3 claim shows up in {index 0, pass 2} at bit 27")


def check_locked_difficulty_refused():
    unlocked = server.RCFG["player"]["invasionUnlockedDifficulty"]
    st = _fresh()
    out = server.r_invasion_reward({"theme": 1, "difficulty": unlocked + 1}, st)
    assert not out["rewardListData"]["rewardList"], \
        f"difficulty {unlocked + 1} paid out despite only {unlocked} being unlocked"
    assert not server.load_state().get("invasionRewardState", {}).get("1")
    print(f"ok gate: difficulty {unlocked + 1} refused (unlocked = {unlocked})")


def check_winning_unlocks_the_next_difficulty():
    st = _fresh()
    st["invasionRecords"] = {"1": {"cleared": 11, "unlocked": 11}}
    server.r_game_complete(
        {"gameId": "difficulty-11", "win": True, "theme": 1, "stage": 10,
         "difficulty": 11}, st)
    record = server.load_state()["invasionRecords"]["1"]
    assert record == {"cleared": 11, "unlocked": 12}, record
    print("ok progress: winning difficulty 11 unlocks difficulty 12")


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
    for t in sorted({t for (t, d) in server.INVASION_REWARDS}):
        i, p = server._invasion_pass_index(t), server._invasion_pass_of(t)
        entry = next(r for r in listed if r["index"] == i and r["pass"] == p)
        got = (entry["rewardState"] >> (5 * ((t - 1) % 10))) & 0b11111
        assert got == 0b11111, f"theme {t}: entry {entry} shows {got:#b}, expected all 5 claimed"
    for i in (0, 2):
        entry = next(r for r in listed if r["index"] == i and r["pass"] == 1)
        assert entry["rewardState"] == (1 << 50) - 1, \
            f"pass-1 entry {entry} not full after receive-all"
    print(f"ok receive-all: {n} rewards, idempotent, every theme's 5 bits set")


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
    check_claim_state_reaches_listing()
    check_locked_difficulty_refused()
    check_winning_unlocks_the_next_difficulty()
    check_pass_rewards_are_opt_in()
    check_receive_all_then_nothing_left()
    check_no_item_zero()
    print("\nall invasion reward checks passed")
