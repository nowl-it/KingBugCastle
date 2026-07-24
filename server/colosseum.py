"""Colosseum and Arena: score, tier and the reward tables behind them.

Both PvP modes answered fixed numbers out of `response_config.json`, so a win
changed nothing: the score sat at 1000 forever, the tier never moved, and the
tier-reward panel had nothing to hand out.

The real progression is entirely in master data. `ColosseumRankScoreTable.xml`
gives the score delta per bracket (48 rows, finer than the tier list), and
`ColosseumRankTiers.xml` gives the tier boundaries plus the one-off reward each
tier pays the first time it is reached. `ArenaSettings.xml` holds the arena's
win-count reward steps.

Two traps live here. Five of the tiers do not have a score of their own: 70/71
both sit at 2200 and 80/81/82 all sit at 2400, separated only by a leaderboard
bracket spelled in the NameComment ("갓(31~100위)", "킹갓(1위)"). That is why the
client resolves the top of the ladder with `GetByScoreAndRank(score, rank)` and
not by score - reading score alone hands every player the rank-1 payout, which is
1500 cash a season. And the arena steps are cumulative win counts, not per-step
increments, so reaching step 3 does not mean the earlier steps were paid.

    python3 colosseum.py     # self-check
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

# Reward Type -> the inventory row it is really n of, same pinning as missions.py.
ARENA_TOKEN = 2002
TOKEN_ITEMS = {"Token_ARENA": ARENA_TOKEN, "ArenaToken": ARENA_TOKEN,
               "Token_COLOSSEUM": ARENA_TOKEN}

_cache = {}


def _root(name, xml_dir):
    key = (name, str(xml_dir))
    if key not in _cache:
        _cache[key] = ET.parse(Path(xml_dir) / name).getroot()
    return _cache[key]


def _reward(el):
    t = el.get("Type") or ""
    out = {"type": TOKEN_ITEMS.get(t) and "Item" or t,
           "id": int(el.get("ID", TOKEN_ITEMS.get(t, 0)) or 0),
           "count": int(el.get("Count", 1) or 1)}
    if t == "InventoryItem":
        out["type"] = "Item"
    return out


_BRACKET = re.compile(r"\((\d+)(?:~(\d+))?위\)")


def _rank_bracket(name):
    """(min, max) leaderboard places a tier name claims, or None if it takes any."""
    m = _BRACKET.search(name or "")
    if not m:
        return None
    lo = int(m.group(1))
    return lo, int(m.group(2) or lo)


def tiers(xml_dir=DEFAULT_XML):
    """[{id, reqScore, winScore, loseScore, name, rank, rewards}] in ascending order."""
    out = []
    for el in _root("ColosseumRankTiers.xml", xml_dir):
        if el.get("ID") is None:
            continue
        items = el.find("RewardItems")
        name = el.findtext("NameComment") or ""
        out.append({
            "id": int(el.get("ID")),
            "name": name,
            "rank": _rank_bracket(name),
            "reqScore": int(el.findtext("ReqScore", 0) or 0),
            "winScore": int(el.findtext("WinScore", 0) or 0),
            "loseScore": int(el.findtext("LoseScore", 0) or 0),
            "rewards": [_reward(r) for r in (items if items is not None else [])],
        })
    return sorted(out, key=lambda t: t["id"])


def tier_for(score, rank=0, xml_dir=DEFAULT_XML):
    """The tier a score sits in.

    Above 2200 the score no longer decides on its own - several tiers share it and
    the NameComment bracket picks between them by leaderboard place. Rank 0 means
    unranked, which takes the lowest bracket rather than the best one."""
    reached = [t for t in tiers(xml_dir) if score >= t["reqScore"]]
    if not reached:
        return tiers(xml_dir)[0]
    share = [t for t in reached if t["reqScore"] == reached[-1]["reqScore"]]
    if rank >= 1:
        for t in share:
            b = t["rank"]
            if b is None or b[0] <= rank <= b[1]:
                return t
    return share[0]


def score_delta(score, win, xml_dir=DEFAULT_XML):
    """Points a win or a loss moves the score by, from the finer score table."""
    rows = sorted(
        ((int(e.get("ReqScore", 0) or 0), int(e.get("WinScore", 0) or 0),
          int(e.get("LoseScore", 0) or 0))
         for e in _root("ColosseumRankScoreTable.xml", xml_dir)
         if e.get("ReqScore") is not None))
    row = rows[0]
    for r in rows:
        if score >= r[0]:
            row = r
    return row[1] if win else row[2]


def apply_result(score, win, xml_dir=DEFAULT_XML):
    """New score after a game. Score never drops below the bottom tier's floor -
    the client's tier lookup has no answer for a negative score."""
    floor = tiers(xml_dir)[0]["reqScore"]
    return max(floor, score + score_delta(score, win, xml_dir))


def tier_rewards_up_to(tier_id, claimed, xml_dir=DEFAULT_XML):
    """Every tier reward at or below `tier_id` that is not in `claimed`.

    Returns (rewards, newly claimed ids). The panel pays these as a batch, and a
    tier only ever pays once, so the claimed set is what stops a re-reach from
    paying twice."""
    got, ids = [], []
    for t in tiers(xml_dir):
        if t["id"] > tier_id or t["id"] in claimed:
            continue
        got += t["rewards"]
        ids.append(t["id"])
    return got, ids


def arena_win_steps(xml_dir=DEFAULT_XML):
    """[{step, winCount, rewards}] - winCount is cumulative, not per step."""
    out = []
    node = _root("ArenaSettings.xml", xml_dir).find("WinRewards")
    for el in (node if node is not None else []):
        out.append({"step": int(el.get("Step", 0) or 0),
                    "winCount": int(el.get("WinCount", 0) or 0),
                    "rewards": [_reward(r) for r in el.findall("Reward")]})
    return sorted(out, key=lambda s: s["step"])


def arena_rewards_for(wins, claimed, xml_dir=DEFAULT_XML):
    got, ids = [], []
    for s in arena_win_steps(xml_dir):
        if wins < s["winCount"] or s["step"] in claimed:
            continue
        got += s["rewards"]
        ids.append(s["step"])
    return got, ids


def _self_check():
    ts = tiers()
    assert len(ts) >= 20, f"{len(ts)} tiers parsed"
    assert ts[0]["reqScore"] == 0, "the bottom tier does not start at 0"
    assert all(t["rewards"] for t in ts), "a tier pays nothing"
    assert [t["reqScore"] for t in ts] == sorted(t["reqScore"] for t in ts), \
        "tiers are not in ascending score order"

    # The top of the ladder is decided by rank, not score.
    top = ts[-1]
    share = [t for t in ts if t["reqScore"] == top["reqScore"]]
    assert len(share) > 1, "the top tiers no longer share a score - re-read the table"
    assert tier_for(top["reqScore"] + 500)["id"] == share[0]["id"], \
        "a high score alone was given a top-rank tier"
    assert tier_for(top["reqScore"] + 500, rank=1)["id"] == top["id"], \
        "rank 1 was not given the top tier"
    assert tier_for(top["reqScore"], rank=9999)["id"] == share[0]["id"], \
        "a rank outside every bracket did not fall back to the lowest"
    for t in share:
        if t["rank"]:
            assert tier_for(t["reqScore"], rank=t["rank"][0])["id"] == t["id"], \
                f"tier {t['id']} does not answer its own rank bracket"
    assert tier_for(-999)["id"] == ts[0]["id"], "a negative score fell off the table"

    assert score_delta(0, True) > 0 and score_delta(0, False) < 0, "deltas have no sign"
    assert score_delta(2400, True) < score_delta(0, True), \
        "a win at the top pays as much as at the bottom"
    assert apply_result(0, False) == ts[0]["reqScore"], "a loss at the floor went negative"
    assert apply_result(1000, True) > 1000

    # A tier pays once: claiming everything up to it leaves nothing to claim again.
    got, ids = tier_rewards_up_to(ts[-1]["id"], set())
    assert got and len(ids) == len(ts), f"{len(ids)} of {len(ts)} tiers paid"
    again, _ = tier_rewards_up_to(ts[-1]["id"], set(ids))
    assert not again, "a claimed tier paid a second time"

    steps = arena_win_steps()
    assert steps and all(s["rewards"] for s in steps), "an arena step pays nothing"
    assert [s["winCount"] for s in steps] == sorted(s["winCount"] for s in steps), \
        "arena steps are not cumulative"
    assert all(r["type"] == "Item" and r["id"] == ARENA_TOKEN
               for s in steps for r in s["rewards"]), \
        "an arena token reward did not resolve to an inventory row"
    paid, sids = arena_rewards_for(steps[1]["winCount"], set())
    assert len(sids) == 2, f"{len(sids)} steps paid at {steps[1]['winCount']} wins"

    print(f"ok: {len(ts)} tiers ({ts[0]['reqScore']}..{ts[-1]['reqScore']}), "
          f"{len(steps)} arena steps, win at 1000 -> {apply_result(1000, True)}")


if __name__ == "__main__":
    _self_check()
