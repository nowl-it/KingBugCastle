"""
Treasure (Bảo cụ) APIs - equip, exp, overcome, dismantle
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def equip_treasure(unit_id: int, treasure_id: int, use_ticket: bool = False) -> dict:
    """
    POST /treasure/equip?useTicket={bool}
    Trang bị treasure cho hero.
    use_ticket=True: dùng ticket thay vì gem.
    """
    return post("/treasure/equip", params={"useTicket": str(use_ticket).lower()},
                body={"unitId": unit_id, "treasureId": treasure_id})


def release_equip_treasure(unit_id: int, treasure_id: int) -> dict:
    """POST /treasure/release-equip"""
    return post("/treasure/release-equip", {"unitId": unit_id, "treasureId": treasure_id})


def add_treasure_exp(treasure_id: int, item_id: int, count: int) -> dict:
    """POST /treasure/add-exp"""
    return post("/treasure/add-exp", {"treasureId": treasure_id, "itemId": item_id, "count": count})


def overcome_treasure(treasure_id: int) -> dict:
    """POST /treasure/overcome - tăng overcome level"""
    return post("/treasure/overcome", {"treasureId": treasure_id})


def dismantle_treasure(treasure_ids: list) -> dict:
    """POST /treasure/dismantle"""
    return post("/treasure/dismantle", {"treasureIds": treasure_ids})


def set_treasure_state(treasure_id: int, state: int) -> dict:
    """
    POST /treasure/set-state
    state: 0=Normal, 1=Lock, 2=Favorite
    """
    return post("/treasure/set-state", {"treasureId": treasure_id, "state": state})


def equip_treasure_tutorial(unit_id: int, treasure_id: int) -> dict:
    """POST /treasure/equip-tutorial"""
    return post("/treasure/equip-tutorial", {"unitId": unit_id, "treasureId": treasure_id})


if __name__ == "__main__":
    print("Treasure APIs loaded. Cần login trước khi gọi.")
    print("Ví dụ: equip_treasure(unit_id=10580, treasure_id=30038)")
