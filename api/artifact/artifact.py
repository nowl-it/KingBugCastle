"""
Artifact APIs - crafting, merge, reroll, equip, polish
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def fetch_artifact_inventory() -> dict:
    """GET /artifact/inventory"""
    return get("/artifact/inventory")


def artifact_gacha(artifact_id: int = 0) -> dict:
    """POST /artifact/gacha"""
    return post("/artifact/gacha", {"artifactId": artifact_id})


def artifact_crafting(artifact_type: int, material_ids: list) -> dict:
    """POST /artifact/crafting"""
    return post("/artifact/crafting", {"artifactType": artifact_type, "materialIds": material_ids})


def artifact_merge(artifact_ids: list) -> dict:
    """POST /artifact/merge"""
    return post("/artifact/merge", {"artifactIds": artifact_ids})


def artifact_dismantle(artifact_ids: list) -> dict:
    """POST /artifact/dismantle"""
    return post("/artifact/dismantle", {"artifactIds": artifact_ids})


def artifact_reroll(artifact_id: int, use_gold: bool = False) -> dict:
    """POST /artifact/reroll?useGold={bool}"""
    return post("/artifact/reroll", params={"useGold": str(use_gold).lower()},
                body={"artifactId": artifact_id})


def artifact_smart_reroll(artifact_id: int) -> dict:
    """POST /artifact/smart-reroll"""
    return post("/artifact/smart-reroll", {"artifactId": artifact_id})


def artifact_fetch_reroll() -> dict:
    """POST /artifact/fetch-reroll"""
    return post("/artifact/fetch-reroll")


def artifact_set_reroll(artifact_id: int, selected_option: int) -> dict:
    """POST /artifact/set-reroll"""
    return post("/artifact/set-reroll", {"artifactId": artifact_id, "selectedOption": selected_option})


def artifact_polish(artifact_id: int, option_slot_idx: int) -> dict:
    """POST /artifact/polish"""
    return post("/artifact/polish", {"artifactId": artifact_id, "optionSlotIdx": option_slot_idx})


def artifact_polish_replace(artifact_id: int, replace_slot_idx: int) -> dict:
    """POST /artifact/polish/replace-option-slot-idx"""
    return post("/artifact/polish/replace-option-slot-idx", {"artifactId": artifact_id, "replaceSlotIdx": replace_slot_idx})


def artifact_equip(unit_id: int, artifact_id: int, slot: int) -> dict:
    """POST /artifact/equip"""
    return post("/artifact/equip", {"unitId": unit_id, "artifactId": artifact_id, "slot": slot})


def artifact_set_favorites(artifact_ids: list) -> dict:
    """POST /artifact/set-favorites"""
    return post("/artifact/set-favorites", {"artifactIds": artifact_ids})


def open_catalyst_box(box_id: int, count: int = 1) -> dict:
    """POST /artifact/open-catalyst-box"""
    return post("/artifact/open-catalyst-box", {"boxId": box_id, "count": count})


if __name__ == "__main__":
    import json
    print("=== Fetch Artifact Inventory ===")
    try:
        result = fetch_artifact_inventory()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error (cần login): {e}")
