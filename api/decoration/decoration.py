"""
Decoration APIs - advisor, map skin, login skin, flag, name tag
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def fetch_decoration_info() -> dict:
    """GET /decoration"""
    return get("/decoration")


# --- Advisor ---

def contract_advisor(advisor_id: int) -> dict:
    """POST /decoration/advisor/contract"""
    return post("/decoration/advisor/contract", {"advisorId": advisor_id})


def equip_advisor(advisor_id: int) -> dict:
    """POST /decoration/advisor/equip"""
    return post("/decoration/advisor/equip", {"advisorId": advisor_id})


def extend_advisor(advisor_id: int) -> dict:
    """POST /decoration/advisor/extend"""
    return post("/decoration/advisor/extend", {"advisorId": advisor_id})


def timeout_advisor(advisor_id: int) -> dict:
    """POST /decoration/advisor/timeout"""
    return post("/decoration/advisor/timeout", {"advisorId": advisor_id})


# --- Map Skin ---

def buy_map_skin(skin_id: int) -> dict:
    """POST /decoration/map-skin/buy"""
    return post("/decoration/map-skin/buy", {"skinId": skin_id})


def equip_map_skin(skin_id: int) -> dict:
    """POST /decoration/map-skin/equip"""
    return post("/decoration/map-skin/equip", {"skinId": skin_id})


def set_map_skin_favorite(skin_id: int, is_favorite: bool) -> dict:
    """POST /decoration/map-skin/favorite"""
    return post("/decoration/map-skin/favorite", {"skinId": skin_id, "isFavorite": is_favorite})


# --- Login Skin ---

def equip_login_skin(skin_id: int) -> dict:
    """POST /decoration/login-skin/equip"""
    return post("/decoration/login-skin/equip", {"skinId": skin_id})


# --- Flag ---

def fetch_flag_inventory(target_id: int = -1) -> dict:
    """GET /flag/inventory?targetId={id}"""
    params = {"targetId": target_id} if target_id >= 0 else {}
    return get("/flag/inventory", params=params)


def fetch_equipped_flag(target_id: int = -1) -> dict:
    """GET /flag/equipedFlag?targetId={id}"""
    params = {"targetId": target_id} if target_id >= 0 else {}
    return get("/flag/equipedFlag", params=params)


def set_flag(flag_id: int) -> dict:
    """POST /flag/set"""
    return post("/flag/set", {"flagId": flag_id})


# --- Name Tag ---

def fetch_name_tag_inventory() -> dict:
    """GET /nameTag/inventory"""
    return get("/nameTag/inventory")


def set_name_tag(name_tag_id: int) -> dict:
    """POST /nameTag/set"""
    return post("/nameTag/set", {"nameTagId": name_tag_id})


if __name__ == "__main__":
    import json
    print("=== Fetch Decoration Info ===")
    try:
        result = fetch_decoration_info()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error (cần login): {e}")
