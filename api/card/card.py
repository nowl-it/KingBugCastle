"""
Card (Hero) APIs - upgrade, skin, potential
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def get_all_cards() -> dict:
    """GET /card/all - toàn bộ card collection"""
    return get("/card/all")


def get_card(card_id: int) -> dict:
    """GET /card?cardId={id}"""
    return get("/card", params={"cardId": card_id})


def upgrade_card(card_id: int, use_candy: bool = False) -> dict:
    """POST /card/upgrade hoặc /card/useCandy"""
    path = "/card/useCandy" if use_candy else "/card/upgrade"
    return post(path, {"cardId": card_id, "count": 1})


def fast_upgrade_card(card_id: int, target_level: int) -> dict:
    """POST /card/fast-upgrade"""
    return post("/card/fast-upgrade", {"cardId": card_id, "targetLevel": target_level})


def upgrade_potential_tier(card_id: int) -> dict:
    """POST /card/upgradePotentialTier"""
    return post("/card/upgradePotentialTier", {"cardId": card_id})


def use_unit_exp_item(card_id: int, item_id: int, count: int) -> dict:
    """POST /card/useUnitExpItem"""
    return post("/card/useUnitExpItem", {"cardId": card_id, "itemId": item_id, "count": count})


def use_unit_soul_item(card_id: int, item_id: int, count: int) -> dict:
    """POST /card/useUnitSoulItem"""
    return post("/card/useUnitSoulItem", {"cardId": card_id, "itemId": item_id, "count": count})


def use_unit_soul_to_exp(card_id: int, soul_unit_id: int, count: int) -> dict:
    """POST /card/useUnitSoulToExp"""
    return post("/card/useUnitSoulToExp", {"cardId": card_id, "soulUnitId": soul_unit_id, "count": count})


def buy_skin(card_id: int, skin_id: int) -> dict:
    """POST /card/buySkin"""
    return post("/card/buySkin", {"cardId": card_id, "skinId": skin_id})


def equip_skin(card_id: int, skin_id: int) -> dict:
    """POST /card/equipSkin"""
    return post("/card/equipSkin", {"cardId": card_id, "skinId": skin_id})


def set_skin_favorite(card_id: int, skin_id: int, is_favorite: bool) -> dict:
    """POST /card/set-skin-favorite"""
    return post("/card/set-skin-favorite", {"cardId": card_id, "skinId": skin_id, "isFavorite": is_favorite})


def set_random_skin_apply(card_id: int, enabled: bool) -> dict:
    """POST /card/set-random-skin-apply"""
    return post("/card/set-random-skin-apply", {"cardId": card_id, "enabled": enabled})


if __name__ == "__main__":
    import json
    print("=== Get All Cards ===")
    try:
        result = get_all_cards()
        if isinstance(result, dict):
            print(f"Keys: {list(result.keys())}")
    except Exception as e:
        print(f"Error (cần login): {e}")
