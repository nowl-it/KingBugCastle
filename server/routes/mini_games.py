"""The roguelike save blob and the four seasonal mini-games.

The roguelike run lives entirely client-side: the client serialises the whole thing
into one opaque string and posts it. The server's only job is to hold that string so
a run survives closing the app - which is exactly what the static placeholder could
not do, since it always answered with an empty save.

The four mini-games - Territory Tycoon, the stock event, KG Marble and event-card
collecting - had all 23 of their routes answering an empty auto-generated model, which
for these means null lists and null sub-models, and every one of those panels
dereferences them before it checks whether the event is running.

Three of the four have a window in master data and every window has closed:
StockConstants ran 2025-10-22 to 2025-11-12, the event cards are season 55 against the
current 71, and KG Marble's board is handed out by the server, which is not handing
one out. So the correct answer is a well-formed "no event", not an empty body.
Territory Tycoon is the exception: its tokens are ordinary inventory items, so its
numbers are real.

Uses the `register(app, srv)` pattern.

    python3 mini_games.py     # self-check
"""
from common import admin_log, body_int, now_iso
from config import PLAYER_DEFAULTS as _PC
from decoration import block as _deco
from state import save_state

srv = None      # the live server module, set by register()

# InventoryItems.xml 2008/2009/2010 해변축제 브론즈/실버/골드 토큰, same pinning
# missions.py uses.
TYCOON_TOKENS = {"bronzeToken": 2008, "silverToken": 2009, "goldToken": 2010}


def _rogue(st, theme):
    return st.setdefault("rogueLike", {}).setdefault(str(body_int(theme, 0)), {
        "saveData": "", "ownCardSnapshot": "", "state": "", "saveVersion": 0,
        "lastHeartPaidFloor": 0, "lastGameStartedSeason": 0})


def r_rogue_save(body, st):
    """Store the run blob. An empty blob is a legitimate 'run over' write, so it is
    stored as sent rather than being treated as a missing field."""
    r = _rogue(st, body.get("themeId", 0))
    r["saveData"] = body.get("rogueLikeSaveData", "")
    r["state"] = body.get("state", "")
    r["saveVersion"] = body_int(body.get("saveVersion"), 0)
    save_state(st)
    return {}


def r_rogue_snapshot(body, st):
    """The hero roster the run was started with, frozen so later lobby upgrades do
    not change a run in progress."""
    r = _rogue(st, body.get("themeId", 0))
    r["ownCardSnapshot"] = body.get("ownCardSnapshot", "")
    save_state(st)
    return {}


def r_rogue_load(body, st):
    r = _rogue(st, body.get("themeId", 0))
    save_state(st)
    return {"rogueLikeSaveData": r["saveData"],
            "rogueLikeOwnCardSnapshot": r["ownCardSnapshot"],
            "state": r["state"], "saveVersion": r["saveVersion"],
            "lastHeartPaidFloor": r["lastHeartPaidFloor"],
            "lastGameStartedSeason": r["lastGameStartedSeason"]}


def r_rogue_delete(body, st):
    """Abandon a run. The game index has to move, or the client keeps replaying the
    same index and the next run's saves collide with the deleted one's."""
    theme = body.get("rogueLikeThemeId", body.get("themeId", 0))
    st.setdefault("rogueLike", {}).pop(str(body_int(theme, 0)), None)
    st["rogueLikeGameIndex"] = int(st.get("rogueLikeGameIndex", 0)) + 1
    save_state(st)
    admin_log(f"[roguelike] run on theme {theme} deleted -> "
              f"index {st['rogueLikeGameIndex']}")
    return {"rogueLikeGameIndex": st["rogueLikeGameIndex"],
            "dimensionRiftGameIndex": st.get("dimensionRiftGameIndex", 0),
            "returnHeart": 0}


def r_rogue_revive(body, st):
    """Reviving inside a run costs the same cash as reviving in a normal battle."""
    return srv.r_game_revive(body, st)


def r_rogue_can_revive_by_ad(body, st):
    """No ad network is wired up here, so the ad revive is never offered - reported
    as unavailable rather than left empty, which the button reads as an error."""
    return {"canReviveByAd": False, "remainCount": 0}


def r_rogue_statistics(body, st):
    """Clear rates across the playerbase. One player is not a sample, and inventing
    one would print made-up percentages next to real mission names."""
    return {"rogueLikeMissionStatistics": [], "totalRogueLikeUser": 1}


def _tycoon_tokens(st):
    return {k: srv._item_count(st, item) for k, item in TYCOON_TOKENS.items()}


def r_tycoon_tokens(body, st):
    out = _tycoon_tokens(st)
    out["storedGoldToken"] = st.get("tycoonStoredGold", 0)
    return out


def r_tycoon_collect_gold(body, st):
    """Move banked gold tokens into the inventory, where every other panel reads
    them from. Nothing banked means nothing moves, rather than a free token."""
    stored = int(st.get("tycoonStoredGold", 0))
    if stored > 0:
        srv._grant_reward(st, "Item", TYCOON_TOKENS["goldToken"], stored)
        st["tycoonStoredGold"] = 0
        save_state(st)
    return r_tycoon_tokens(body, st)


def r_tycoon_firework(body, st):
    out = _tycoon_tokens(st)
    out["tycoonPoint"] = st.get("tycoonPoint", 0)
    out["skipRewardUsedCount"] = st.get("tycoonSkipRewardUsed", 0)
    return out


def r_tycoon_player(body, st):
    out = _tycoon_tokens(st)
    out.update({"level": st.get("tycoonLevel", 1),
                "storedGoldToken": st.get("tycoonStoredGold", 0),
                "skipRewardUsedCount": st.get("tycoonSkipRewardUsed", 0),
                "buildings": st.get("tycoonBuildings", [])})
    return out


def r_stock_my_info(body, st):
    """The stock event's own wallet. Its token is not an inventory item - it only
    exists inside the event - so it lives on the save under its own key."""
    return {"currentTokenCount": st.get("stockTokens", 0),
            "highestTokenCount": st.get("stockTokensHigh", 0),
            "remainingBuyCount": 0, "shopState": 0, "premiumShopState": 0,
            "timeOffset": 0, "hints": [], "portfolios": [],
            "nextDailyAttendanceDate": now_iso(1)}


def r_stock_attendance(body, st):
    """The daily wage. The event has ended, so it pays nothing - reported as a zero
    reward with the real balance, not as an empty body the panel reads as a
    failure."""
    return {"rewardTokenCount": 0,
            "currentTokenCount": st.get("stockTokens", 0),
            "highestTokenCount": st.get("stockTokensHigh", 0),
            "nextDailyAttendanceDate": now_iso(1)}


def r_stock_buy_hint(body, st):
    """A hint costs tokens and names a stock in a round. With no round running there
    is nothing to hint at, so no token is taken."""
    return {"hint": None, "currentTokenCount": st.get("stockTokens", 0)}


def r_stock_mission(body, st):
    return {"state": 0, "rewardList": srv._reward_list_data([])}


def r_stock_ranking(body, st):
    """One player, so one row - the same shape the other boards use."""
    d = _PC["defaults"]
    deco = _deco(st)
    row = {"round": 0, "userRank": 1, "percentileRank": 100.0,
           "accountId": st.get("accountId", d["accountId"]),
           "rateOfReturn": 0.0,
           "profile": {"userName": st.get("name", d["name"]),
                       "castleName": st.get("castleName", d["castleName"]),
                       "kingPostfix": 0, "castlePostfix": 0,
                       "profileIcon": d["profileIconId"], "nameTagId": deco["nameTag"]}}
    return {"playerRanking": row, "ranking": [row]}


def r_marble(body, st):
    """KG Marble. The board itself comes from the server and there is none to hand
    out, so `init` is false and every list is present but empty - the panel walks
    boardData and rewards by index before it looks at init."""
    return {"init": False,
            "kgMarbleModel": {"accountId": st.get("accountId", 0), "round": 0,
                              "dailyRound": 0, "boardData": [], "boardExecuted": [],
                              "position": 0, "player": st.get("marblePlayer", 0),
                              "boughtPass": False, "dailyFreeCount": 0,
                              "rewards": [], "passRewards": [], "executeEvents": []},
            "rewardRet": srv._reward_list_data([]), "addedEventIdx": -1,
            "diceValueSum": 0, "diceValues": [], "reverseMove": False,
            "teleportMove": False, "eventTokenCount": 0, "forceBoardRefresh": False}


def r_marble_set_player(body, st):
    """Which token the player moves around the board. Cosmetic, and the only part
    of the mode that means anything with no board running."""
    st["marblePlayer"] = body_int(body.get("player"), 0)
    save_state(st)
    return r_marble(body, st)


def r_event_cards(body, st):
    """Event-card collecting. The cards in master data are season 55 against the
    current 71, so there is no collection to be part-way through."""
    return {"collectionStates": {}, "eventCardCounts": {}, "appliedEventCard": 0,
            "point": 0, "collectionCompleted": False, "freeGachaAvailable": False}


def r_event_cards_exchange(body, st):
    return {"playerEventCardCollectingResponseModel": r_event_cards(body, st),
            "exchangedEventCardId": 0}


def r_event_cards_reward(body, st):
    return {"playerEventCardCollectingResponseModel": r_event_cards(body, st),
            "rewardListData": srv._reward_list_data([])}


def register(app, server_module):
    global srv
    srv = server_module
    srv.MINI_GAME_OVERRIDES = handlers()


def handlers():
    return {
        "/rogueLike/save-rogueLike": r_rogue_save,
        "/rogueLike/load-rogueLike-data": r_rogue_load,
        "/rogueLike/save-own-card-snapshot": r_rogue_snapshot,
        "/rogueLike/delete-roguelike": r_rogue_delete,
        "/rogueLike/revive": r_rogue_revive,
        "/rogueLike/can-revive-by-ad": r_rogue_can_revive_by_ad,
        "/mission/roguelike-statistics": r_rogue_statistics,
        "/territory-tycoon/fetch-token": r_tycoon_tokens,
        "/territory-tycoon/collect-gold-token": r_tycoon_collect_gold,
        "/territory-tycoon/firework": r_tycoon_firework,
        "/territory-tycoon/recover-seasonal-token": r_tycoon_player,
        "/territory-tycoon/attendance-check": r_tycoon_player,
        "/stock-event/my-info": r_stock_my_info,
        "/stock-event/daily-attendance": r_stock_attendance,
        "/stock-event/buy-hint": r_stock_buy_hint,
        "/stock-event/mission": r_stock_mission,
        "/stock-event/ranking": r_stock_ranking,
        "/stock-event/orders": r_stock_ranking,
        "/stock-event/prices": r_stock_my_info,
        "/kg-marble": r_marble,
        "/kg-marble/roll": r_marble,
        "/kg-marble/reward": r_marble,
        "/kg-marble/execute-event": r_marble,
        "/kg-marble/set-player": r_marble_set_player,
        "/event-card-collecting/fetch": r_event_cards,
        "/event-card-collecting/apply": r_event_cards,
        "/event-card-collecting/collect": r_event_cards,
        "/event-card-collecting/gacha": r_event_cards,
        "/event-card-collecting/exchange": r_event_cards_exchange,
        "/event-card-collecting/receive-reward": r_event_cards_reward,
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

    # A run must survive the round-trip - that is this module's whole job.
    r_rogue_save({"themeId": 4000, "rogueLikeSaveData": "BLOB", "saveVersion": 3}, st)
    got = r_rogue_load({"themeId": 4000}, st)
    assert got["rogueLikeSaveData"] == "BLOB", got
    r_rogue_delete({"themeId": 4000}, st)
    assert "BLOB" not in str(r_rogue_load({"themeId": 4000}, st)), "a deleted run came back"

    # Banked gold tokens move into the inventory, and nothing banked moves nothing.
    st["tycoonStoredGold"] = 0
    before = srv._item_count(st, TYCOON_TOKENS["goldToken"])
    r_tycoon_collect_gold({}, st)
    assert srv._item_count(st, TYCOON_TOKENS["goldToken"]) == before, "a free token appeared"
    st["tycoonStoredGold"] = 5
    r_tycoon_collect_gold({}, st)
    assert srv._item_count(st, TYCOON_TOKENS["goldToken"]) == before + 5
    assert st["tycoonStoredGold"] == 0, "the bank was not emptied"

    # The closed events must answer a well-formed "no event", never a null sub-model.
    for fn in (r_stock_my_info, r_stock_mission, r_stock_ranking, r_marble, r_event_cards):
        out = fn({}, st)
        assert isinstance(out, dict) and out, f"{fn.__name__} answered empty"
        assert not any(v is None for v in out.values()), f"{fn.__name__} sent a null: {out}"

    paths = handlers()
    assert len(paths) == 30, f"{len(paths)} routes registered"
    assert all(callable(h) for h in paths.values())
    print(f"mini_games self-check ok ({len(paths)} routes)")
