"""
Event APIs - seasonal events, stock event, babel, invasion, card collecting, coupon
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


# --- Seasonal Events ---

def fetch_seasonal_event() -> dict:
    """GET /seasonal-event/fetch"""
    return get("/seasonal-event/fetch")


def get_april_fools_reward(reward_idx: int) -> dict:
    """GET /seasonal-event/april-fools/reward?rewardIdx={i}"""
    return get("/seasonal-event/april-fools/reward", params={"rewardIdx": reward_idx})


# --- Custom Event (eventcache) ---

def get_event_cache() -> dict:
    """GET /eventcache"""
    return get("/eventcache")


def custom_event(event_id: int) -> dict:
    """GET /player/customEvent?id={id}"""
    return get("/player/customEvent", params={"id": event_id})


# --- Custom Event (complete) ---

def complete_custom_event(event_id: int) -> dict:
    """POST /customevent/complete"""
    return post("/customevent/complete", {"eventId": event_id})


# --- Coupon ---

def use_coupon(code: str) -> dict:
    """POST /ingame-coupon - nhập coupon code"""
    return post("/ingame-coupon", {"code": code})


# --- Invasion ---

def get_invasion_record() -> dict:
    """GET /invasion/record"""
    return get("/invasion/record")


def get_invasion_reward() -> dict:
    """GET /invasion/reward"""
    return get("/invasion/reward")


def receive_invasion_reward(reward_id: int) -> dict:
    """POST /invasion/reward/receive"""
    return post("/invasion/reward/receive", {"rewardId": reward_id})


def receive_all_invasion_rewards() -> dict:
    """POST /invasion/reward/receive-all"""
    return post("/invasion/reward/receive-all")


# --- Babel ---

def get_babel_info() -> dict:
    """GET /babel"""
    return get("/babel")


# --- KG Marble ---

def get_kg_marble() -> dict:
    """GET /kg-marble"""
    return get("/kg-marble")


def kg_marble_roll(count: int = 1) -> dict:
    """POST /kg-marble/roll"""
    return post("/kg-marble/roll", {"count": count})


def kg_marble_execute_event(event_id: int) -> dict:
    """POST /kg-marble/execute-event"""
    return post("/kg-marble/execute-event", {"eventId": event_id})


def kg_marble_reward(reward_id: int) -> dict:
    """POST /kg-marble/reward"""
    return post("/kg-marble/reward", {"rewardId": reward_id})


def kg_marble_set_player(player_data: dict) -> dict:
    """POST /kg-marble/set-player"""
    return post("/kg-marble/set-player", player_data)


# --- Card Collecting Event ---

def fetch_card_collecting_event() -> dict:
    """GET /event-card-collecting/fetch"""
    return get("/event-card-collecting/fetch")


def card_collecting_gacha(is_free: bool = False) -> dict:
    """GET /event-card-collecting/gacha?isFreeGacha={bool}"""
    return get("/event-card-collecting/gacha", params={"isFreeGacha": str(is_free).lower()})


def collect_card(card_id: int) -> dict:
    """POST /event-card-collecting/collect"""
    return post("/event-card-collecting/collect", {"cardId": card_id})


def apply_card_collecting(cards: list) -> dict:
    """POST /event-card-collecting/apply"""
    return post("/event-card-collecting/apply", {"cards": cards})


def exchange_card_collecting(exchange_id: int) -> dict:
    """POST /event-card-collecting/exchange"""
    return post("/event-card-collecting/exchange", {"exchangeId": exchange_id})


def receive_card_collecting_reward(reward_id: int) -> dict:
    """POST /event-card-collecting/receive-reward"""
    return post("/event-card-collecting/receive-reward", {"rewardId": reward_id})


# --- Stock Event ---

def get_stock_event_info() -> dict:
    """GET /stock-event/my-info"""
    return get("/stock-event/my-info")


def get_stock_prices(stock_id: int, count: int = 10) -> dict:
    """GET /stock-event/prices?stockId={id}&count={n}"""
    return get("/stock-event/prices", params={"stockId": stock_id, "count": count})


def get_stock_orders(stock_id: int) -> dict:
    """GET /stock-event/orders?stockId={id}"""
    return get("/stock-event/orders", params={"stockId": stock_id})


def get_all_stock_orders() -> dict:
    """GET /stock-event/orders"""
    return get("/stock-event/orders")


def create_stock_order(stock_id: int, order_type: int, price: int, quantity: int) -> dict:
    """POST /stock-event/orders"""
    return post("/stock-event/orders", {
        "stockId": stock_id,
        "orderType": order_type,
        "price": price,
        "quantity": quantity,
    })


def get_stock_ranking() -> dict:
    """GET /stock-event/ranking"""
    return get("/stock-event/ranking")


def stock_daily_attendance() -> dict:
    """POST /stock-event/daily-attendance"""
    return post("/stock-event/daily-attendance")


def buy_stock_hint() -> dict:
    """POST /stock-event/buy-hint"""
    return post("/stock-event/buy-hint")


def receive_stock_mission_reward(mission_id: int) -> dict:
    """POST /stock-event/mission"""
    return post("/stock-event/mission", {"missionId": mission_id})


# --- Territory Tycoon ---

def territory_tycoon_firework(firework_id: int) -> dict:
    """POST /territory-tycoon/firework"""
    return post("/territory-tycoon/firework", {"fireworkId": firework_id})


def recover_seasonal_token() -> dict:
    """POST /territory-tycoon/recover-seasonal-token"""
    return post("/territory-tycoon/recover-seasonal-token")


if __name__ == "__main__":
    import json

    print("=== Fetch Seasonal Event ===")
    try:
        result = fetch_seasonal_event()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error (cần login): {e}")

    print("\n=== Get Babel Info ===")
    try:
        result = get_babel_info()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")
