"""
Game APIs - battle start/complete/revive/skip
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def game_start(
    theme: int,
    difficulty: int,
    cards: list,
    buildings: list,
    deck_preset: int = 0,
    target_boss: int = 0,
    target_deck: int = 0,
    is_retrying: bool = False,
    babel_floor: int = 0,
    roguelike_first_hero: int = 0,
    roguelike_challenge_level: int = 0,
    artifacts: list = None,
    challenge_mode_difficulty: int = 0,
) -> dict:
    """
    POST /game/start
    Bắt đầu một trận đấu.

    theme: 1=Normal, 2=Challenge, 4=Story, 6=Babel, 7=Roguelike
    difficulty: 1-5
    cards: list unit ID trong deck [10000, 10010, ...]
    buildings: list building levels [1, 2, 3, 4, 5, ...]
    """
    body = {
        "theme": theme,
        "currentDeckPreset": deck_preset,
        "difficulty": difficulty,
        "targetDeck": target_deck,
        "isArenaTraining": False,
        "foodBoosterLevel": 0,
        "targetBoss": target_boss,
        "targetDifficulty": 0,
        "isTestBattle": False,
        "isPracticeBattle": False,
        "isRetrying": is_retrying,
        "barrackPreset": 0,
        "babelFloor": babel_floor,
        "isEventModeContinued": False,
        "rogueLikeSelectedFirstHero": roguelike_first_hero,
        "rogueLikeChallengeLevel": roguelike_challenge_level,
        "isForceFreeRetry": False,
        "deckInfo": {
            "cards": cards,
            "buildings": buildings,
            "artifacts": artifacts or [],
        },
        "challengeModeDifficulty": challenge_mode_difficulty,
    }
    return post("/game/start", body)


def game_complete(
    round_data: list,
    merchant_result: dict = None,
    devel_result: dict = None,
    craft_result: dict = None,
) -> dict:
    """
    POST /game/complete
    Gửi kết quả trận đấu lên server.

    round_data: list RoundData, mỗi round có fieldUnits, barricade, v.v.
    """
    default_merchant = {
        "item1": 0, "item2": 0, "item3": 0,
        "itemOptions1": [], "itemOptions2": [], "itemOptions3": [],
        "buy1": False, "buy2": False, "buy3": False,
        "hasAd": False,
    }
    default_devel = {"stage": 0, "condition": "", "reward": 0, "accepted": False}
    default_craft = {"item1": 0, "item2": 0, "item3": 0, "selectedItem": 0, "reRollCount": 0}

    body = {
        "roundData": round_data,
        "merchantResult": merchant_result or default_merchant,
        "develResult": devel_result or default_devel,
        "craftResult": craft_result or default_craft,
    }
    return post("/game/complete", body)


def game_revive(use_revive_coupon: bool = False) -> dict:
    """
    POST /game/revive?useReviveCoupon={bool}
    Hồi sinh trong trận. use_revive_coupon=False thì tốn gem.
    """
    return post(f"/game/revive", params={"useReviveCoupon": str(use_revive_coupon).lower()})


def game_skip(skip_data: dict = None) -> dict:
    """
    POST /game/skip
    Bỏ qua màn (cần có skip ticket).
    """
    return post("/game/skip", skip_data or {})


def get_event_mode() -> dict:
    """GET /game/eventMode - lấy event mode hiện tại"""
    return get("/game/eventMode")


def game_ad_bonus(ad_type: str, placement: str) -> dict:
    """
    POST /game/adBonus
    Nhận bonus sau khi xem quảng cáo.
    ad_type: "gold_bonus", "revive", v.v.
    """
    return post("/game/adBonus", {"adType": ad_type, "placement": placement})


def check_dimension_rift_complete() -> dict:
    """POST /game/check-dimension-rift-complete-success"""
    return post("/game/check-dimension-rift-complete-success")


def make_field_unit(
    unit_id: int,
    level: int,
    pos_x: int,
    pos_y: int,
    item1: int = 0,
    item2: int = 0,
    item3: int = 0,
    item4: int = 0,
) -> dict:
    """Helper tạo EndFieldUnit cho game_complete()"""
    return {
        "unitId": unit_id,
        "level": level,
        "item1": item1, "item2": item2, "item3": item3, "item4": item4,
        "itemOption1": [], "itemOption2": [], "itemOption3": [], "itemOption4": [],
        "posX": pos_x,
        "posY": pos_y,
    }


def make_round_data(field_units: list, barricade: int = 100) -> dict:
    """Helper tạo RoundData cho game_complete()"""
    return {
        "fieldUnits": field_units,
        "fieldUnitAIs": "",
        "barricade": barricade,
        "cloneUnitRemovedIdx": -1,
    }


if __name__ == "__main__":
    import json

    print("=== Get Event Mode ===")
    try:
        result = get_event_mode()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error (cần login): {e}")

    # Demo cấu trúc game_start
    print("\n=== Game Start body example ===")
    import json
    body_example = {
        "theme": 1,
        "difficulty": 3,
        "cards": [10000, 10010, 10020, 10030],
        "buildings": [1, 2, 3, 4, 5],
    }
    print(json.dumps(body_example, indent=2))
