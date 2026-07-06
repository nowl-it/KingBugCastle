"""
Player APIs - thông tin player, inventory, buildings, early access
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def get_player_info() -> dict:
    """GET /player - toàn bộ player data"""
    return get("/player")


def get_other_player(target_id: int) -> dict:
    """GET /player/other?targetId={id}"""
    return get(f"/player/other", params={"targetId": target_id})


def get_currencies() -> dict:
    """GET /player/currencies"""
    return get("/player/currencies")


def get_daily_consumed_currencies() -> dict:
    """GET /player/daily-consumed-currencies"""
    return get("/player/daily-consumed-currencies")


def get_inventory() -> dict:
    """GET /player/getInventory"""
    return get("/player/getInventory")


def use_inventory(item_id: int, count: int = 1) -> dict:
    """POST /player/useInventory"""
    return post("/player/useInventory", {"itemId": item_id, "count": count})


def use_reward_box(item_id: int, count: int = 1) -> dict:
    """POST /player/use-reward-box-inventory-item"""
    return post("/player/use-reward-box-inventory-item", {"itemId": item_id, "count": count})


def use_skin_box(item_id: int, count: int = 1) -> dict:
    """POST /player/use-skin-box-inventory-item"""
    return post("/player/use-skin-box-inventory-item", {"itemId": item_id, "count": count})


def add_inventory_count(inventory_type: str, count: int) -> dict:
    """POST /player/add-inventory-count"""
    return post("/player/add-inventory-count", {"inventoryType": inventory_type, "count": count})


def rename(new_name: str) -> dict:
    """POST /player/rename"""
    return post("/player/rename", {"name": new_name})


def change_profile_icon(icon_id: int) -> dict:
    """POST /player/changeProfileIcon"""
    return post("/player/changeProfileIcon", {"iconId": icon_id})


def get_building_info() -> dict:
    """GET /player/building"""
    return get("/player/building")


def buy_building_point() -> dict:
    """POST /player/building/point"""
    return post("/player/building/point")


def reset_building_point(levels: list, preset: int = 0) -> dict:
    """POST /player/building/resetPoint"""
    return post("/player/building/resetPoint", {"levels": levels, "preset": preset})


def save_building(levels: list, preset: int = 0) -> dict:
    """POST /player/building/save"""
    return post("/player/building/save", {"levels": levels, "preset": preset})


def recover_heart() -> dict:
    """POST /player/heart/recover"""
    return post("/player/heart/recover")


def can_early_access() -> dict:
    """GET /player/early-access-mode - kiểm tra quyền truy cập early access"""
    return get("/player/early-access-mode")


def check_early_access_code(code: str) -> dict:
    """
    GET /player/early-access-mode-code?code={code}
    Xác thực code beta. Validation server-side.
    Response: { "success": bool, "message": str }
    """
    return get("/player/early-access-mode-code", params={"code": code})


def complete_tutorial(status_key: str) -> dict:
    """POST /player/tutorial/complete"""
    return post("/player/tutorial/complete", {"statusKey": status_key})


def progress_tutorial_mission(number: int) -> dict:
    """POST /player/tutorial/progress-mission"""
    return post("/player/tutorial/progress-mission", {"number": number})


def get_tutorial_status() -> dict:
    """GET /player/tutorial-status"""
    return get("/player/tutorial-status")


def get_daily_attendance_events() -> dict:
    """GET /player/dailyAttendanceEvents"""
    return get("/player/dailyAttendanceEvents")


def get_surprise_attendance_event() -> dict:
    """GET /player/surprise-attendance-event"""
    return get("/player/surprise-attendance-event")


def get_surprise_attendance_daily_reward() -> dict:
    """POST /player/surprise-attendance-event-daily-attendance-reward"""
    return post("/player/surprise-attendance-event-daily-attendance-reward")


def get_year_event() -> dict:
    """GET /player/year-event"""
    return get("/player/year-event")


def get_year_event_attendance_reward() -> dict:
    """GET /player/year-event-attendance-reward"""
    return get("/player/year-event-attendance-reward")


def get_year_event_pass_reward() -> dict:
    """GET /player/year-event-pass-reward"""
    return get("/player/year-event-pass-reward")


def buy_year_event_pass_point(buy_count: int) -> dict:
    """POST /player/year-event-buy-pass-point?buyCount={n}"""
    return post(f"/player/year-event-buy-pass-point", params={"buyCount": buy_count})


def get_journey_reward(reward_index: int = 0) -> dict:
    """GET /player/journey-reward"""
    return get("/player/journey-reward", params={"rewardIndex": reward_index})


def initialize_journey() -> dict:
    """POST /player/initialize-journey"""
    return post("/player/initialize-journey")


def get_login_scene_illust(version: int = 0) -> dict:
    """GET /player/get-login-scene-illust-data?version={version}"""
    return get("/player/get-login-scene-illust-data", params={"version": version})


def get_game_skip_info() -> dict:
    """GET /player/game-skip-information"""
    return get("/player/game-skip-information")


if __name__ == "__main__":
    import json

    print("=== Player Info ===")
    try:
        result = get_player_info()
        # Chỉ in một phần để không quá dài
        keys = list(result.keys()) if isinstance(result, dict) else []
        print(f"Keys: {keys}")
    except Exception as e:
        print(f"Error (cần login trước): {e}")

    print("\n=== Check Early Access Code ===")
    try:
        result = check_early_access_code("TEST_CODE_123")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")
