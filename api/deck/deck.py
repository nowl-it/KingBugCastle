"""
Deck APIs - get, set, potential, slot management
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def get_deck() -> dict:
    """GET /deck - toàn bộ deck data"""
    return get("/deck")


def set_deck(preset_idx: int, deck: list, potential: list = None, first_comer_index: int = 0) -> dict:
    """
    POST /deck/set
    preset_idx: index preset (0-based)
    deck: list unit ID [10000, 10010, ...]
    potential: list potential config
    """
    return post("/deck/set", {
        "presetIdx": preset_idx,
        "deck": deck,
        "potential": potential or [],
        "firstComerIndex": first_comer_index,
    })


def buy_deck_slot() -> dict:
    """POST /deck/buyDeckSlot"""
    return post("/deck/buyDeckSlot")


def set_deck_slot_name(preset_idx: int, name: str) -> dict:
    """POST /deck/set-deck-slot-name"""
    return post("/deck/set-deck-slot-name", {"presetIdx": preset_idx, "name": name})


def set_all_card_potential(preset_idx: int, potential_config: list) -> dict:
    """POST /deck/setAllPotential"""
    return post("/deck/setAllPotential", {"presetIdx": preset_idx, "potentialConfig": potential_config})


def set_card_potential(preset_idx: int, unit_id: int, potential_slot: int, set_to_all: bool = False) -> dict:
    """POST /deck/setPotential"""
    return post("/deck/setPotential", {
        "presetIdx": preset_idx,
        "unitId": unit_id,
        "potentialSlot": potential_slot,
        "setToAll": set_to_all,
    })


if __name__ == "__main__":
    import json
    print("=== Get Deck ===")
    try:
        result = get_deck()
        if isinstance(result, dict):
            print(f"Keys: {list(result.keys())}")
    except Exception as e:
        print(f"Error (cần login): {e}")
