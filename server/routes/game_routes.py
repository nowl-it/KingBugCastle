"""Battle routes: game start/complete/revive and the Babel towers.

Game completion is also where progression is recorded (best-cleared themes,
challenge difficulty track, level ups) and where mission counters advance -
the client reports the battle outcome here, so everything that must react to
a win lives in this one handler.
"""
import secrets
from common import body_int, body_str, now_iso
from config import RCFG, XML_DIR
from state import save_state
import babel

srv = None      # live server module, injected via register()


def register(app, server_module):
    global srv
    srv = server_module
    srv.GAME_OVERRIDES = handlers()


def handlers():
    return {
        "/game": r_game_start,
        "/game/start": r_game_start,
        "/game/complete": r_game_complete,
        "/game/skip": r_game_complete,
        "/game/revive": r_game_revive,
        "/babel": r_babel,
    }


def r_game_start(body, st):
    print(f"  [GAME/START] body={body}")
    gc = RCFG["gameStart"]
    theme = body_int(body.get("theme"), 1, lo=0)
    stage = body_int(body.get("stage"), 1, lo=0)
    heart_cost = gc["heartCostLow"] if theme <= gc["heartCostThemeThreshold"] else gc["heartCostHigh"]
    heart = max(0, st.get("heart", 999) - heart_cost)
    st["heart"] = heart
    gid = secrets.token_hex(8)
    srv._game_store[gid] = {"theme": theme, "stage": stage, "heartCost": heart_cost}
    save_state(st)
    return {
        "heart": heart,
        "lastHeartTime": st.get("lastHeartTime", now_iso(0)),
        "buildingData": srv._get_building_data(st),
        "cards": srv.cards_list(st),
        "gameId": gid,
        "eventFlag": st.get("eventFlag", 0),
    }


def r_game_complete(body, st):
    gc = RCFG["gameComplete"]
    babel_rewards = []
    print(f"  [GAME/COMPLETE] body={body}")
    gid = body_str(body.get("gameId"))
    win = bool(body.get("win", False))
    theme = body_int(body.get("theme"), 1, lo=0)
    stage = body_int(body.get("stage"), 1, lo=0)
    srv._game_store.pop(gid, None)
    add_gold = gc["baseGold"] + theme * gc["goldPerTheme"] + (gc["winBonusGold"] if win else 0)
    add_exp = gc["baseExp"] + theme * gc["expPerTheme"]
    st["gold"] += add_gold
    st["exp"] += add_exp
    if win:
        st["winCount"] = st.get("winCount", 0) + 1
        # Real invasion progress: the complete request carries the cleared difficulty
        # for invasion themes too - store it so the records derive from actual clears
        # (the seed grants cleared=unlocked=11; real clears never downgrade it).
        diff = body_int(body.get("difficulty"), 0)
        if diff >= 1:
            from routes.player_routes import invasion_theme_list
            if theme in set(invasion_theme_list()):
                rec = st.setdefault("invasionRecords", {}).setdefault(
                    str(theme), {"cleared": 0, "unlocked": 0})
                rec["cleared"] = max(rec["cleared"], diff)
                rec["unlocked"] = max(rec["unlocked"], min(diff + 1, 5))
        # Hard invasion themes (51-70) advance bestClearedHardTheme instead of
        # bestClearedTheme.  The Invasion II section panel gates on the former, so
        # without this update the section stays locked even after clearing I-10 Hard.
        if theme >= 51:
            if theme > st.get("bestClearedHardTheme", 0):
                st["bestClearedHardTheme"] = theme
                st["bestClearedHardStage"] = stage
            elif theme == st.get("bestClearedHardTheme", 0) and stage > st.get("bestClearedHardStage", 0):
                st["bestClearedHardStage"] = stage
        else:
            if theme > st.get("bestClearedTheme", 0):
                st["bestClearedTheme"] = theme
                st["bestClearedStage"] = stage
            elif theme == st.get("bestClearedTheme", 0) and stage > st.get("bestClearedStage", 0):
                st["bestClearedStage"] = stage
    # The ranking-stage ("Measure Combat Power") battle reports its score here:
    # GameCompleteRequestModel.eliteRankingScore. The weekly board reads it back,
    # so dropping it is how scores silently stopped updating.
    elite = body.get("eliteRankingScore")
    if isinstance(elite, (int, float)) and elite > 0:
        st["eliteRankingScore"] = max(int(elite), int(st.get("eliteRankingScore", 0)))
    st["playedCount"] = st.get("playedCount", 0) + 1
    srv.bump(st, "playGame")
    srv.bump(st, "playTheme", sub=theme)
    if win:
        srv.bump(st, "clearGame")
        srv.bump(st, "clearTheme", sub=theme)
        # Challenge runs report their difficulty alongside the theme; without this the
        # challenge reward track can never advance past zero. Themes below 4000 are
        # the ordinary story/invasion ones and carry no challenge difficulty.
        if theme >= srv._CHALLENGE_THEME_MIN and body.get("difficulty"):
            cs = srv._challenge_state(st)
            cs["bestDifficulty"] = max(cs["bestDifficulty"],
                                       body_int(body.get("difficulty"), 0))
            cs["clearedBattles"] = max(cs["clearedBattles"], int(stage) + 1)
        # A Babel floor pays its own reward on first clear; nothing else advances the
        # tower, so without this hook every tower stays on floor 0 forever.
        babel_rewards = _babel_clear(st, theme, int(stage))
    if st.get("exp", 0) >= gc["expPerLevel"]:
        st["level"] = min(srv.MAX_PLAYER_LEVEL, st["level"] + st["exp"] // gc["expPerLevel"])
        st["exp"] = st["exp"] % gc["expPerLevel"] if st["level"] < srv.MAX_PLAYER_LEVEL else 0
    save_state(st)
    out = {"addGold": add_gold, "addExp": add_exp,
           "playerGold": st["gold"], "playerLevel": st["level"], "playerExp": st["exp"]}
    out.update(gc["fixed"])
    if babel_rewards:
        out["rewardListData"] = srv._reward_list_data(babel_rewards)
    return out


def _babel(st):
    return st.setdefault("babel", {})     # babelId (str) -> {"floor": n, "passes": []}


def r_babel(body, st):
    b = _babel(st)
    out = []
    for bid, t in sorted(babel.towers(XML_DIR).items()):
        rec = b.get(str(bid), {})
        nxt = babel.next_open(bid, xml_dir=XML_DIR)
        out.append({"id": bid,
                    "available": babel.available(bid, xml_dir=XML_DIR),
                    "maxClearedFloor": rec.get("floor", 0),
                    "boughtPasses": rec.get("passes", []),
                    "availableAt": nxt.strftime("%Y-%m-%dT%H:%M:%S.000Z") if nxt else ""})
    return {"babels": out}


def _babel_clear(st, theme, floor):
    """Record a cleared floor and pay it, once. Returns the granted rewards.

    Only a new best floor pays: the towers can be re-run for practice, and paying
    every run turns floor 1 of an always-open tower into an unlimited faucet."""
    bid = babel.theme_to_id(XML_DIR).get(theme)
    if bid is None:
        return []
    rec = _babel(st).setdefault(str(bid), {"floor": 0, "passes": []})
    if floor <= rec["floor"] or floor > babel.towers(XML_DIR)[bid]["maxFloor"]:
        return []
    rec["floor"] = floor
    return [srv._grant_mission_reward(st, r)
            for r in babel.floor_reward(theme, floor, XML_DIR)]


def r_game_revive(body, st):
    """Reviving mid-battle. The coupon is free; otherwise it costs cash, and a player
    who cannot pay must not be revived silently for nothing."""
    gc = RCFG["gameComplete"]
    if not body.get("useReviveCoupon"):
        price = gc.get("revivePrice", 30)
        if st.get("cash", 0) < price:
            return {"msg": "not enough cash", "playerGold": st.get("gold", 0),
                    "playerLevel": st.get("level", 1), "playerExp": st.get("exp", 0)}
        st["cash"] -= price
        save_state(st)
    return {"addGold": 0, "addExp": 0, "playerGold": st.get("gold", 0),
            "playerLevel": st.get("level", 1), "playerExp": st.get("exp", 0)}