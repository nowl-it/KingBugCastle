"""
Rift Weapon APIs - upgrade, equip, reroll, crystal
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def get_rift_weapon() -> dict:
    """GET /rift-weapon"""
    return get("/rift-weapon")


def get_crystal_inventory() -> dict:
    """GET /rift-weapon/crystal-inventory"""
    return get("/rift-weapon/crystal-inventory")


def upgrade_rift_weapon(weapon_id: int, material_ids: list = None) -> dict:
    """POST /rift-weapon/upgrade"""
    return post("/rift-weapon/upgrade", {"weaponId": weapon_id, "materialIds": material_ids or []})


def equip_rift_weapon(unit_id: int, weapon_id: int) -> dict:
    """POST /rift-weapon/equip"""
    return post("/rift-weapon/equip", {"unitId": unit_id, "weaponId": weapon_id})


def release_equip_rift_weapon(unit_id: int) -> dict:
    """POST /rift-weapon/release-equip"""
    return post("/rift-weapon/release-equip", {"unitId": unit_id})


def dismantle_rift_weapon(weapon_ids: list) -> dict:
    """POST /rift-weapon/dismantle"""
    return post("/rift-weapon/dismantle", {"weaponIds": weapon_ids})


def reroll_rift_weapon(weapon_id: int) -> dict:
    """POST /rift-weapon/re-roll"""
    return post("/rift-weapon/re-roll", {"weaponId": weapon_id})


def reset_rift_weapon(weapon_id: int) -> dict:
    """POST /rift-weapon/reset-weapon"""
    return post("/rift-weapon/reset-weapon", {"weaponId": weapon_id})


def set_rift_weapon_state(weapon_id: int, state: int) -> dict:
    """POST /rift-weapon/set-state"""
    return post("/rift-weapon/set-state", {"weaponId": weapon_id, "state": state})


def charge_crystal(crystal_id: int, count: int = 1) -> dict:
    """POST /rift-weapon/crystal-charge"""
    return post("/rift-weapon/crystal-charge", {"crystalId": crystal_id, "count": count})


def destroy_crystal(crystal_id: int) -> dict:
    """POST /rift-weapon/crystal-destroy"""
    return post("/rift-weapon/crystal-destroy", {"crystalId": crystal_id})


def set_crystal_state(crystal_id: int, state: int) -> dict:
    """POST /rift-weapon/set-crystal-state"""
    return post("/rift-weapon/set-crystal-state", {"crystalId": crystal_id, "state": state})


def buy_rift_gauge(weapon_id: int) -> dict:
    """POST /rift-weapon/buy-rift-gauge"""
    return post("/rift-weapon/buy-rift-gauge", {"weaponId": weapon_id})


def archive_rift_weapon(weapon_id: int) -> dict:
    """POST /kg-wiki/rift-weapon/archive"""
    return post("/kg-wiki/rift-weapon/archive", {"weaponId": weapon_id})


def archive_delete_rift_weapon(weapon_id: int) -> dict:
    """POST /kg-wiki/rift-weapon/archive-delete"""
    return post("/kg-wiki/rift-weapon/archive-delete", {"weaponId": weapon_id})


if __name__ == "__main__":
    import json
    print("=== Get Rift Weapon ===")
    try:
        result = get_rift_weapon()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error (cần login): {e}")
