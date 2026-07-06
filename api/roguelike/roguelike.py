"""
RogueLike APIs - load, save, start/end floor
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def load_roguelike_data() -> dict:
    """POST /rogueLike/load-rogueLike-data"""
    return post("/rogueLike/load-rogueLike-data")


def load_out_game_data(theme_id: int) -> dict:
    """GET /rogueLike/out-game?themeId={id}"""
    return get("/rogueLike/out-game", params={"themeId": theme_id})


def save_roguelike(data: dict) -> dict:
    """POST /rogueLike/save-rogueLike"""
    return post("/rogueLike/save-rogueLike", data)


def save_own_card_snapshot(card_data: dict) -> dict:
    """POST /rogueLike/save-own-card-snapshot"""
    return post("/rogueLike/save-own-card-snapshot", card_data)


def delete_roguelike(theme_id: int) -> dict:
    """POST /rogueLike/delete-roguelike"""
    return post("/rogueLike/delete-roguelike", {"themeId": theme_id})


def get_season_info(theme_id: int) -> dict:
    """GET /rogueLike/season-info?themeId={id}"""
    return get("/rogueLike/season-info", params={"themeId": theme_id})


def start_floor(
    theme_id: int,
    floor: int,
    deck: list,
    buildings: list,
    challenge_level: int = 0,
) -> dict:
    """POST /rogueLike/startFloor"""
    return post("/rogueLike/startFloor", {
        "themeId": theme_id,
        "floor": floor,
        "deck": deck,
        "buildings": buildings,
        "challengeLevel": challenge_level,
    })


def end_floor(theme_id: int, floor: int, result: dict) -> dict:
    """POST /rogueLike/endFloor"""
    return post("/rogueLike/endFloor", {"themeId": theme_id, "floor": floor, **result})


def revive_roguelike(use_revive_coupon: bool, theme_id: int) -> dict:
    """POST /rogueLike/revive?useReviveCoupon={bool}&themeId={id}"""
    return post("/rogueLike/revive", params={
        "useReviveCoupon": str(use_revive_coupon).lower(),
        "themeId": theme_id,
    })


def can_revive_by_ad(theme_id: int) -> dict:
    """GET /rogueLike/can-revive-by-ad?themeId={id}"""
    return get("/rogueLike/can-revive-by-ad", params={"themeId": theme_id})


def get_roguelike_missions() -> dict:
    """GET /mission/roguelike"""
    return get("/mission/roguelike")


def check_roguelike_missions() -> dict:
    """POST /mission/roguelike/check"""
    return post("/mission/roguelike/check")


def check_roguelike_on_clear(theme_id: int) -> dict:
    """POST /mission/roguelike/check-on-clear?themeId={id}"""
    return post("/mission/roguelike/check-on-clear", params={"themeId": theme_id})


def get_roguelike_statistics() -> dict:
    """GET /mission/roguelike-statistics"""
    return get("/mission/roguelike-statistics")


if __name__ == "__main__":
    import json
    print("=== RogueLike Season Info (theme=1) ===")
    try:
        result = get_season_info(1)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error (cần login): {e}")
