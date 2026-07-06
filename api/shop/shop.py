"""
Shop APIs - mua items, IAP, gacha, wish list
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def get_shop() -> dict:
    """GET /shop - toàn bộ shop data"""
    return get("/shop")


def buy_shop_item(shop_item_id: int, count: int = 1, currency_type: str = "gem") -> dict:
    """POST /shop - mua item trong shop"""
    return post("/shop", {"shopItemId": shop_item_id, "count": count, "currencyType": currency_type})


def refresh_daily_shop() -> dict:
    """POST /shop/refreshDailyShop - làm mới daily shop"""
    return post("/shop/refreshDailyShop")


def can_iap(product_id: str, receipt: str, platform: str = "Android") -> dict:
    """POST /shop/caniap_new - validate IAP receipt"""
    return post("/shop/caniap_new", {"productId": product_id, "receipt": receipt, "platform": platform})


def buy_iap(product_id: str, receipt: str, platform: str = "Android") -> dict:
    """POST /shop/iap - xác nhận mua IAP, nhận items"""
    return post("/shop/iap", {"productId": product_id, "receipt": receipt, "platform": platform})


def get_restore_needed_iaps() -> dict:
    """GET /shop/get-restore-needed-iaps"""
    return get("/shop/get-restore-needed-iaps")


def remove_restore_iap(receipt_id: str) -> dict:
    """POST /shop/remove-from-restore-needed-iaps"""
    return post("/shop/remove-from-restore-needed-iaps", {"receiptId": receipt_id})


def load_custom_pickups(gacha_id: int) -> dict:
    """GET /shop/load-custom-pickups?gachaId={id}"""
    return get("/shop/load-custom-pickups", params={"gachaId": gacha_id})


def save_custom_pickups(gacha_id: int, pickups: list) -> dict:
    """POST /shop/save-custom-pickups"""
    return post("/shop/save-custom-pickups", {"gachaId": gacha_id, "pickups": pickups})


def get_treasure_wish_list() -> dict:
    """GET /shop/get-treasure-wish-list"""
    return get("/shop/get-treasure-wish-list")


def save_treasure_wish_list(wish_list: list) -> dict:
    """POST /shop/save-treasure-wish-list - wish_list: list treasure ID"""
    return post("/shop/save-treasure-wish-list", {"wishList": wish_list})


def check_treasure_wish_list_valid(wish_list: list) -> dict:
    """POST /shop/check-treasure-wish-list-valid"""
    return post("/shop/check-treasure-wish-list-valid", {"wishList": wish_list})


def choice_package_unit(shop_item_id: int, unit_id: int) -> dict:
    """POST /shop/choice-package-unit - chọn hero khi mua package"""
    return post("/shop/choice-package-unit", {"shopItemId": shop_item_id, "unitId": unit_id})


def choice_treasure_pickup_ceil(shop_item_id: int, treasure_id: int) -> dict:
    """POST /shop/choice-treasure-pickup-ceil"""
    return post("/shop/choice-treasure-pickup-ceil", {"shopItemId": shop_item_id, "treasureId": treasure_id})


def get_cumulative_purchase_event() -> dict:
    """GET /shop-event/cumulative-purchase"""
    return get("/shop-event/cumulative-purchase")


def claim_cumulative_purchase_reward() -> dict:
    """POST /shop-event/cumulative-purchase/claim"""
    return post("/shop-event/cumulative-purchase/claim")


if __name__ == "__main__":
    import json

    print("=== Get Shop ===")
    try:
        result = get_shop()
        if isinstance(result, dict):
            print(f"Keys: {list(result.keys())}")
        else:
            print(result)
    except Exception as e:
        print(f"Error (cần login): {e}")
