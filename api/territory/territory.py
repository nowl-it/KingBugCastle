"""
Territory APIs - xây dựng, săn bắn (điều tra/TerritoryHunting), alchemy
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


# --- Fetch ---

def fetch_territory() -> dict:
    """GET /territory/fetch - toàn bộ territory state"""
    return get("/territory/fetch")


def fetch_stat_buffs() -> dict:
    """GET /territory/fetch-stat-buffs"""
    return get("/territory/fetch-stat-buffs")


# --- Buildings ---

def build_building(pos_index: int, building_id: int) -> dict:
    """POST /territory/build"""
    return post("/territory/build", {"posIndex": pos_index, "buildingId": building_id})


def upgrade_building(pos_index: int) -> dict:
    """POST /territory/upgrade-building?posIndex={i}"""
    return post("/territory/upgrade-building", params={"posIndex": pos_index})


def upgrade_building_immediately(pos_index: int, territory_type: int = 0) -> dict:
    """POST /territory/upgrade-building-immediately?posIndex={i}&territoryType={t}"""
    return post("/territory/upgrade-building-immediately", params={"posIndex": pos_index, "territoryType": territory_type})


def refresh_building(pos_index: int) -> dict:
    """POST /territory/refresh-building"""
    return post("/territory/refresh-building", {"posIndex": pos_index})


def replace_building(pos_index: int, building_id: int) -> dict:
    """POST /territory/replace-building"""
    return post("/territory/replace-building", {"posIndex": pos_index, "buildingId": building_id})


def remove_building(pos_index: int) -> dict:
    """DELETE /territory/remove-building?posIndex={i}"""
    from config import SESSION, BASE_URL
    r = SESSION.delete(BASE_URL + f"/territory/remove-building", params={"posIndex": pos_index})
    r.raise_for_status()
    return r.json()


def store_building(pos_index: int) -> dict:
    """POST /territory/store-building?posIndex={i}"""
    return post("/territory/store-building", params={"posIndex": pos_index})


def unstore_building(building_id: int, pos_index: int) -> dict:
    """POST /territory/unstore-building?buildingId={id}&posIndex={i}"""
    return post("/territory/unstore-building", params={"buildingId": building_id, "posIndex": pos_index})


# --- Units ---

def assign_units(building_id: int, unit_ids: list) -> dict:
    """POST /territory/assign-units"""
    return post("/territory/assign-units", {"buildingId": building_id, "unitIds": unit_ids})


def swap_assigned_units(building_id_a: int, building_id_b: int) -> dict:
    """POST /territory/swap-assigned-units"""
    return post("/territory/swap-assigned-units", {"buildingIdA": building_id_a, "buildingIdB": building_id_b})


# --- Labor ---

def collect_labor(amount: int) -> dict:
    """POST /territory/collect-labor?amount={n}"""
    return post("/territory/collect-labor", params={"amount": amount})


def recover_labor() -> dict:
    """POST /territory/recover-labor"""
    return post("/territory/recover-labor")


# --- Attendance ---

def territory_attendance_check() -> dict:
    """POST /territory/attendance-check"""
    return post("/territory/attendance-check")


# --- Alchemy ---

def alchemy_new(data: dict) -> dict:
    """POST /territory/alchemy-new"""
    return post("/territory/alchemy-new", data)


# --- Level Sync ---

def assign_level_sync(unit_id: int, building_id: int) -> dict:
    """POST /territory/level-sync/assign"""
    return post("/territory/level-sync/assign", {"unitId": unit_id, "buildingId": building_id})


def reset_level_sync_timer(building_id: int) -> dict:
    """POST /territory/level-sync/reset-timer"""
    return post("/territory/level-sync/reset-timer", {"buildingId": building_id})


# --- Skin ---

def equip_territory_skin(skin_id: int) -> dict:
    """POST /territory/equip-skin"""
    return post("/territory/equip-skin", {"skinId": skin_id})


# --- Restaurant ---

def claim_restaurant_reward() -> dict:
    """POST /territory/restaurant/claim"""
    return post("/territory/restaurant/claim")


# --- Trade Shop ---

def buy_trade_shop(item_id: int, count: int = 1) -> dict:
    """POST /territory/trade-shop/buy"""
    return post("/territory/trade-shop/buy", {"itemId": item_id, "count": count})


# --- Hunting (Điều tra / TerritoryHunting) ---

def fetch_hunting() -> dict:
    """
    GET /territory/hunting/fetch
    Lấy state hiện tại của chế độ điều tra (TerritoryHunting).
    Đây là hệ thống idle dispatch - heroes được gửi đi trong một khoảng thời gian.
    """
    return get("/territory/hunting/fetch")


def start_hunting(hunting_id: int, unit_ids: list) -> dict:
    """
    POST /territory/hunting/start
    Bắt đầu nhiệm vụ điều tra.

    hunting_id: ID từ TerritoryHuntings.xml (ví dụ 10203 = Area 2 Bandits Difficulty 3)
    unit_ids: list hero ID gửi đi (theo ReqHeroCount trong XML)
    """
    return post("/territory/hunting/start", {"huntingId": hunting_id, "unitIds": unit_ids})


def end_hunting(hunting_id: int) -> dict:
    """POST /territory/hunting/end - nhận kết quả sau khi hết thời gian"""
    return post("/territory/hunting/end", {"huntingId": hunting_id})


def stop_hunting(hunting_id: int) -> dict:
    """POST /territory/hunting/stop - dừng sớm (mất phần thưởng)"""
    return post("/territory/hunting/stop", {"huntingId": hunting_id})


def complete_hunting_immediately(hunting_id: int) -> dict:
    """POST /territory/hunting/complete-hunting-immediately - hoàn thành ngay (tốn gem)"""
    return post("/territory/hunting/complete-hunting-immediately", {"huntingId": hunting_id})


# --- Tycoon ---

def fetch_tycoon_token() -> dict:
    """GET /territory-tycoon/fetch-token"""
    return get("/territory-tycoon/fetch-token")


def tycoon_attendance_check() -> dict:
    """POST /territory-tycoon/attendance-check"""
    return post("/territory-tycoon/attendance-check")


def collect_gold_token(amount: int) -> dict:
    """POST /territory-tycoon/collect-gold-token?amount={n}"""
    return post("/territory-tycoon/collect-gold-token", params={"amount": amount})


if __name__ == "__main__":
    import json

    print("=== Fetch Territory ===")
    try:
        result = fetch_territory()
        if isinstance(result, dict):
            print(f"Keys: {list(result.keys())}")
    except Exception as e:
        print(f"Error (cần login): {e}")

    print("\n=== Fetch Hunting (Điều tra) ===")
    try:
        result = fetch_hunting()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")
