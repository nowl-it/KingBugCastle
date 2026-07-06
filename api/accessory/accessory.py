"""
Accessory APIs - equip, change stats, dismantle, preset
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def equip_accessory(unit_id: int, accessory_id: int, slot: int, use_ticket: bool = False) -> dict:
    """POST /accessory/equip?useTicket={bool}"""
    return post("/accessory/equip", params={"useTicket": str(use_ticket).lower()},
                body={"unitId": unit_id, "accessoryId": accessory_id, "slot": slot})


def release_equip_accessory(unit_id: int, slot: int) -> dict:
    """POST /accessory/release-equip"""
    return post("/accessory/release-equip", {"unitId": unit_id, "slot": slot})


def add_accessory_exp(accessory_id: int, item_ids: list) -> dict:
    """POST /accessory/add-exp"""
    return post("/accessory/add-exp", {"accessoryId": accessory_id, "itemIds": item_ids})


def change_sub_stat(accessory_id: int, slot_index: int) -> dict:
    """POST /accessory/change-sub-stat"""
    return post("/accessory/change-sub-stat", {"accessoryId": accessory_id, "slotIndex": slot_index})


def dismantle_accessories(accessory_ids: list) -> dict:
    """POST /accessory/dismantle"""
    return post("/accessory/dismantle", {"accessoryIds": accessory_ids})


def set_accessory_state_all(state: int) -> dict:
    """POST /accessory/set-state-all - set state cho toàn bộ accessory"""
    return post("/accessory/set-state-all", {"state": state})


def get_accessory_preset() -> dict:
    """GET /accessory/preset"""
    return get("/accessory/preset")


def set_accessory_preset(preset_data: dict) -> dict:
    """POST /accessory/set-preset"""
    return post("/accessory/set-preset", preset_data)


def set_accessory_preset_name(preset_idx: int, name: str) -> dict:
    """POST /accessory/set-preset-name"""
    return post("/accessory/set-preset-name", {"presetIdx": preset_idx, "name": name})


def equip_accessory_tutorial(unit_id: int, accessory_id: int) -> dict:
    """POST /accessory/equip-tutorial"""
    return post("/accessory/equip-tutorial", {"unitId": unit_id, "accessoryId": accessory_id})


if __name__ == "__main__":
    print("Accessory APIs loaded. Cần login trước khi gọi.")
