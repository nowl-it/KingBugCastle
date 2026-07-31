"""Colosseum and Arena: the two PvP panels and the 41 routes behind them.

Twenty-two of those routes answered an empty model, so both panels opened onto
nothing: no match log, no statistics, no tier rewards to claim, and a score frozen at
the 1000 the config seeds. What is missing is progression, not matchmaking - the live
game plays these over a websocket against a real opponent, and there is no second
player here, so the honest shape is a mode you play against the bot side that already
exists client-side, with the server keeping score.

Score, tier boundaries and every reward come from master data (colosseum.py). The
server owns the running total; the client owns the battle.

Uses the `register(app, srv)` pattern; `srv` is the live server module, so the shared
helpers it owns (`_opponents`, `_grant_reward`, `_deck_units`, ...) resolve at request
time. `card_infos()` is public because /player/other draws the same deck row.

    python3 pvp.py      # self-check
"""
import time

import colosseum
from common import admin_log, body_int, now_iso
from config import PLAYER_DEFAULTS as _PC, RCFG, XML_DIR
from decoration import block as _deco
from state import save_state

srv = None      # the live server module, set by register()

# Both modes keep flat state keys so the leaderboards can read a score without
# knowing anything about this section.
_PVP_MODES = {
    "colosseum": {"prefix": "colosseum", "config": "colosseum"},
    "arena": {"prefix": "pvp", "config": "pvpInfo"},
}


def _pvp_state(st, mode):
    """(prefix, seeded config) for a mode, so a fresh save starts where the panel
    expects rather than at zero."""
    m = _PVP_MODES[mode]
    cfg = RCFG[m["config"]]["fixed"]
    p = m["prefix"]
    st.setdefault(p + "Score", cfg.get("score", 1000))
    st.setdefault(p + "Win", 0)
    st.setdefault(p + "Lose", 0)
    st.setdefault(p + "Claimed", [])
    st.setdefault(p + "Logs", [])
    return p, cfg

def _pvp_record(st, mode, win):
    """Apply one finished game. Returns the score delta so the result popup can
    show it - the client draws the arrow off this number, not off the new total."""
    p, _ = _pvp_state(st, mode)
    before = int(st[p + "Score"])
    after = colosseum.apply_result(before, win, XML_DIR)
    st[p + "Score"] = after
    st[p + "Win" if win else p + "Lose"] += 1
    st[p + "Tier"] = colosseum.tier_for(after, int(st.get(p + "Rank", 0)), XML_DIR)["id"]
    return after - before

def _pvp_log(st, mode, win, delta, extra=None):
    """Append a match to the mode's history, newest last, capped.

    The panel re-reads the whole list every time it opens, so it cannot grow
    without bound; 50 is more than the log view scrolls through."""
    p, cfg = _pvp_state(st, mode)
    logs = st[p + "Logs"]
    # The id counts every game ever played, not the length of the kept list -
    # deriving it from len() makes ids repeat as soon as the cap starts trimming,
    # and the log view keys its rows on them.
    st[p + "LogSeq"] = int(st.get(p + "LogSeq", 0)) + 1
    entry = {"logId": st[p + "LogSeq"], "myScoreDelta": delta,
             "semiSeason": cfg.get("semiSeason", 1),
             "startedAt": now_iso(0), "endedAt": now_iso(0), "win": win}
    entry.update(extra or {})
    logs.append(entry)
    del logs[:-50]
    return entry

def _pvp_deck_preview(st, mode, log_id=0):
    """A DeckInfoPreview row: who played, drawn beside each log line."""
    d = _PC["defaults"]
    deco = _deco(st)
    return {"logId": log_id, "accountId": st.get("accountId", d["accountId"]),
            "playerName": st.get("name", d["name"]),
            "castleName": st.get("castleName", d["castleName"]),
            "playerLevel": st.get("level", 1), "profileIcon": d["profileIconId"],
            "nameTagId": deco["nameTag"]}

def card_infos(st):
    """CardInfo[] for the current deck. The opponent preview draws portraits from
    this, so an empty array is a row of blank slots."""
    out = []
    for unit_id in srv._deck_units(st):
        c = srv._card(st, unit_id) or {}
        out.append({"cardId": unit_id, "level": c.get("level", 1),
                    "skin": c.get("currentSkin", 0),
                    "potentialTier": c.get("potentialTier", 0),
                    "overcome": c.get("overcome", 0),
                    "dimensionLevel": c.get("dimensionLevel", 0),
                    "isLevelSyncApplied": False,
                    "treasure": None, "accessories": []})
    return out

def _colosseum_player(st):
    """ColosseumPlayerData for the one player there is."""
    d = _PC["defaults"]
    deco = _deco(st)
    return {"userId": str(st.get("accountId", d["accountId"])),
            "cardInfos": card_infos(st),
            "potentials": [], "firstComerIndex": 0, "artifactModels": [],
            "buildingLevels": srv._get_building_data(st)[0].get("buildingLevels", []),
            "territoryStatBuffPers": [],
            "riftWeaponModels": [],
            "castleName": st.get("castleName", d["castleName"]),
            "userName": st.get("name", d["name"]),
            "profileIconId": d["profileIconId"], "nameTagId": deco["nameTag"],
            "mapSkinId": deco["mapSkin"], "flagModel": dict(deco["flag"]),
            "isBot": False, "roundData": [], "reported": False, "blinded": False}

def _pvp_deck_info(st, mode="arena"):
    """PvPDeckInfo - the arena's equivalent of the colosseum player block."""
    p, cfg = _pvp_state(st, mode)
    d = _PC["defaults"]
    deco = _deco(st)
    return {"id": 0, "season": cfg.get("season", 1), "score": int(st[p + "Score"]),
            "tier": colosseum.tier_for(int(st[p + "Score"]), 0, XML_DIR)["id"],
            "accountId": st.get("accountId", d["accountId"]),
            "playerName": st.get("name", d["name"]),
            "castleName": st.get("castleName", d["castleName"]),
            "profileIcon": d["profileIconId"], "flagId": deco["flag"]["flagId"],
            "nameTagId": deco["nameTag"], "mapSkinId": deco["mapSkin"],
            "cards": card_infos(st), "buildings": [], "pvpDeckRecordData": [],
            "artifacts": [], "potentials": [], "territoryStatBuffPers": [],
            "riftWeapons": [], "encryptedUID": "", "playerLevel": st.get("level", 1)}

def _pvp_season_dates(cfg_key):
    c = RCFG[cfg_key]
    return ([now_iso(n) for n in c["seasonDayOffsets"]],
            [now_iso(n) for n in c["nextSeasonDayOffsets"]])

def _semi_season_scores(st, prefix, count):
    """One {score, rank} per semi-season. SetTier reads this by semi-season index,
    so a list shorter than the current semi-season leaves the tier badge blank."""
    score = int(st.get(prefix + "Score", 0))
    return [{"score": score, "rank": int(st.get(prefix + "Rank", 0))}
            for _ in range(max(1, count))]

def r_pvp_info(body, st):
    p, cfg = _pvp_state(st, "arena")
    until, nxt = _pvp_season_dates("pvpInfo")
    out = dict(cfg)
    score = int(st[p + "Score"])
    out.update({
        "seasonUntilAtDates": until, "nextSeasonStartAtDates": nxt,
        "score": score, "tier": colosseum.tier_for(score, 0, XML_DIR)["id"],
        "maxScore": max(score, int(st.get(p + "BestScore", score))),
        "winCount": st[p + "Win"], "loseCount": st[p + "Lose"],
        "semiSeasonScoreDatas": _semi_season_scores(st, p, cfg.get("semiSeason", 1)),
        "deckInfo": _pvp_deck_info(st), "receivedRewards": list(st[p + "Claimed"]),
        "winRewardReceived": list(st.setdefault(p + "WinSteps", [])),
        "currentSemiSeasonWinCount": st[p + "Win"],
    })
    out["maxTier"] = colosseum.tier_for(out["maxScore"], 0, XML_DIR)["id"]
    return out

def r_colosseum(body, st):
    p, cfg = _pvp_state(st, "colosseum")
    until, nxt = _pvp_season_dates("colosseum")
    out = dict(cfg)
    score = int(st[p + "Score"])
    rank = int(st.get(p + "Rank", 0))
    out.update({
        "seasonUntilAtDates": until, "nextSeasonStartAtDates": nxt,
        "score": score, "tier": colosseum.tier_for(score, rank, XML_DIR)["id"],
        "rank": rank,
        "maxScore": max(score, int(st.get(p + "BestScore", score))),
        "winCount": st[p + "Win"], "loseCount": st[p + "Lose"],
        "gameCount": st[p + "Win"] + st[p + "Lose"],
        "bestScore": max(score, int(st.get(p + "BestScore", score))),
        "receivedRewards": list(st[p + "Claimed"]),
        "semiSeasonScoreDatas": _semi_season_scores(st, p, cfg.get("semiSeason", 1)),
        # ponytail: the free-reward box count is not in any XML we parse, and a
        # wrong length indexes out of range. Empty is the length the client can
        # loop over safely; size it once a box is known to exist.
        "freeRewardCountPerBox": [],
    })
    out["bestTier"] = colosseum.tier_for(out["bestScore"], rank, XML_DIR)["id"]
    out["maxTier"] = out["bestTier"]
    return out

def r_colosseum_complete_round(body, st):
    """One colosseum round finished. `win` decides the score move."""
    win = bool(body.get("win", body.get("isWin", False)))
    delta = _pvp_record(st, "colosseum", win)
    _pvp_log(st, "colosseum", win, delta,
             {"gameId": str(body.get("gameId", "")), "rank": body_int(body.get("rank"), 0),
              "round": body_int(body.get("round"), 0)})
    save_state(st)
    admin_log(f"[colosseum] round {'win' if win else 'loss'} {delta:+d} "
              f"-> {st['colosseumScore']}")
    return {"score": st["colosseumScore"], "scoreDelta": delta,
            "tier": st.get("colosseumTier", 0)}

def r_colosseum_round_data(body, st):
    """Snapshot of a round in progress. Nothing to keep - the client replays its own
    rounds - but it must answer, or the battle stalls waiting on the round save."""
    return {"round": body_int(body.get("round"), 0)}

def r_colosseum_logs(body, st):
    _pvp_state(st, "colosseum")
    logs = []
    for e in reversed(st["colosseumLogs"]):
        logs.append({"logId": e["logId"], "myScoreDelta": e["myScoreDelta"],
                     "semiSeason": e["semiSeason"], "startedAt": e["startedAt"],
                     "gameId": e.get("gameId", ""), "endedAt": e["endedAt"],
                     "playerDecks": [dict(_pvp_deck_preview(st, "colosseum", e["logId"]),
                                          rank=e.get("rank", 1),
                                          round=e.get("round", 0), isBot=False)]})
    return {"logList": logs, "targetUserData": _colosseum_player(st)}

def r_colosseum_statistics(body, st):
    p, cfg = _pvp_state(st, "colosseum")
    # countsByRank is a placement histogram: index 0 is first place. One entry per
    # possible rank, which the mode fixes at four players.
    counts = [st[p + "Win"], st[p + "Lose"], 0, 0]
    return {"dataList": [{"semiSeason": cfg.get("semiSeason", 1),
                          "winCount": st[p + "Win"], "loseCount": st[p + "Lose"],
                          "countsByRank": counts}]}

def r_colosseum_players(body, st):
    # Colosseum is a 4-player mode: you plus up to three real opponents. The client
    # bot-fills whatever is short, so a solo server still starts.
    return {"colosseumPlayerDataList": [_colosseum_player(st)]
                                        + srv._opponents(st, 3, _colosseum_player, fallback=False),
            "isCustomMatch": bool(body.get("isCustomMatch", False))}

def r_colosseum_tier_rewards(body, st):
    """Claim every tier reward the player's best score has earned.

    Rewards are per tier and pay once, so the claimed set is what stops a score
    that crosses the same boundary twice from paying twice."""
    p, _ = _pvp_state(st, "colosseum")
    best = max(int(st[p + "Score"]), int(st.get(p + "BestScore", 0)))
    tier = colosseum.tier_for(best, int(st.get(p + "Rank", 0)), XML_DIR)
    claimed = set(st[p + "Claimed"])
    rewards, new_ids = colosseum.tier_rewards_up_to(tier["id"], claimed, XML_DIR)
    for r in rewards:
        srv._grant_reward(st, r["type"], r["id"], r["count"])
    st[p + "Claimed"] = sorted(claimed | set(new_ids))
    save_state(st)
    admin_log(f"[colosseum] tier rewards up to {tier['id']} -> {len(rewards)} rewards")
    return {"rewardListResponseData": srv._reward_list_data(rewards),
            "receivedRewards": st[p + "Claimed"]}

def r_arena_win_reward(body, st):
    """The arena's cumulative win-count steps from ArenaSettings.xml."""
    p, _ = _pvp_state(st, "arena")
    steps = set(st.setdefault(p + "WinSteps", []))
    rewards, new_ids = colosseum.arena_rewards_for(st[p + "Win"], steps, XML_DIR)
    for r in rewards:
        srv._grant_reward(st, r["type"], r["id"], r["count"])
    st[p + "WinSteps"] = sorted(steps | set(new_ids))
    save_state(st)
    return {"rewardListResponseData": srv._reward_list_data(rewards),
            "winRewardReceived": st[p + "WinSteps"]}

def r_arena_logs(body, st):
    _pvp_state(st, "arena")
    me = _pvp_deck_preview(st, "arena")
    logs = []
    for e in reversed(st["pvpLogs"]):
        row = dict(me, logId=e["logId"], score=int(st["pvpScore"]),
                   tier=st.get("pvpTier", 0))
        logs.append({"logId": e["logId"], "myScoreDelta": e["myScoreDelta"],
                     "semiSeason": e["semiSeason"], "startedAt": e["startedAt"],
                     "myDeckId": 0, "myDeck": row, "enemyDeckId": 0,
                     "enemyDeck": dict(row, playerName=e.get("enemyName", "Bot"))})
    return {"logList": logs, "targetUserData": _pvp_deck_info(st)}

def r_arena_statistics(body, st):
    p, cfg = _pvp_state(st, "arena")
    return {"trainingCount": st.get(p + "Training", 0),
            "dataList": [{"semiSeason": cfg.get("semiSeason", 1),
                          "winCount": st[p + "Win"], "loseCount": st[p + "Lose"],
                          "trainingCount": st.get(p + "Training", 0)}]}

def r_arena_matching(body, st):
    """PvPMatchResponseModel. Offer up to three real opponents; a solo server falls
    back to the player's own deck, which is what training mode does anyway."""
    return {"targets": srv._opponents(st, 3, _pvp_deck_info)}

def r_colosseum_match(body, st):
    """ColosseumMatchResponseModel. No realtime match server exists here, so the
    address is empty and the client falls through to its own bot stage - the same
    path /colosseum/test-single-play takes."""
    return {"gameId": str(body.get("gameId") or f"local-{int(time.time())}"),
            "serverAddress": ""}

def r_colosseum_custom_match(body, st):
    return {"lobbyId": str(body.get("lobbyId") or ""), "endPoint": ""}


def register(app, server_module):
    global srv
    srv = server_module
    srv.PVP_OVERRIDES = handlers()


def handlers():
    """path -> handler. `r_ack` stays in server.py: most of its users are telemetry
    routes that have nothing to do with PvP."""
    ack = srv.r_ack
    return {
        "/pvp/info": r_pvp_info,
        "/pvp/matching": r_arena_matching,
        "/pvp/test-matching": r_arena_matching,
        "/pvp/fetch-log-history": r_arena_logs,
        "/pvp/fetch-log-detail": r_arena_logs,
        "/pvp/fetch-statistics-data": r_arena_statistics,
        "/pvp/win-reward": r_arena_win_reward,
        "/pvp/all-rewards": r_arena_win_reward,
        "/pvp/dormant-progress": ack,
        "/colosseum": r_colosseum,
        "/colosseum/test-single-play": r_colosseum_match,
        "/colosseum/test-free-match": r_colosseum_match,
        "/colosseum/match": r_colosseum_match,
        "/colosseum/match/ping": r_colosseum_match,
        "/colosseum/server-address": r_colosseum_match,
        "/colosseum/match/cancel": ack,
        "/colosseum/create-custom-match": r_colosseum_custom_match,
        "/colosseum/join-custom-match": r_colosseum_custom_match,
        "/colosseum/round-data": r_colosseum_round_data,
        "/colosseum/complete-round-data": r_colosseum_complete_round,
        "/colosseum/check-end": ack,
        "/colosseum/record-minimum-rank": ack,
        "/colosseum/reenter-tried": ack,
        "/colosseum/reenter-succeed": ack,
        "/colosseum/open-mission-reward": lambda b, st: {
            "rewardListResponseData": srv._reward_list_data([])},
        "/colosseum/fetch-players-data": r_colosseum_players,
        "/colosseum/fetch-log-history": r_colosseum_logs,
        "/colosseum/fetch-log-detail": r_colosseum_logs,
        "/colosseum/fetch-statistics-data": r_colosseum_statistics,
        "/colosseum/get-reward": r_colosseum_tier_rewards,
        "/colosseum/all-tier-rewards": r_colosseum_tier_rewards,
    }


if __name__ == "__main__":
    import pathlib as _pl
    import sys
    import tempfile

    import playerdb
    playerdb.DB_PATH = _pl.Path(tempfile.mkdtemp()) / "t.db"
    playerdb.init()
    import server                                        # noqa: E402
    register(server.app, sys.modules["server"])

    st = server.copy.deepcopy(server.DEFAULT_PLAYER)
    st["uid"] = "t"
    playerdb.save("t", st)
    playerdb.set_active("t")

    seed = int(r_colosseum({}, st)["score"])
    delta = _pvp_record(st, "colosseum", True)
    assert delta > 0 and int(st["colosseumScore"]) == seed + delta, "a win must raise the score"
    assert _pvp_record(st, "colosseum", False) < 0, "a loss must lower it"

    for _ in range(60):
        _pvp_log(st, "colosseum", True, 1)
    logs = st["colosseumLogs"]
    assert len(logs) == 50, f"log cap not enforced ({len(logs)})"
    ids = [e["logId"] for e in logs]
    assert len(set(ids)) == len(ids), "log ids repeat once the cap trims - rows collide"

    info = r_pvp_info({}, st)
    assert info["semiSeasonScoreDatas"], "an empty list leaves the tier badge blank"
    assert len(info["seasonUntilAtDates"]) >= 2, "PvP season dates are indexed [semiSeason-1]"

    paths = handlers()
    assert len(paths) == 31, f"{len(paths)} routes registered"
    assert all(callable(h) for h in paths.values())
    print(f"pvp self-check ok ({len(paths)} routes, score {seed} -> {st['colosseumScore']})")
