"""
Story Mode APIs - save, chest reward, challenge
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def fetch_story_mode() -> dict:
    """GET /story-mode"""
    return get("/story-mode")


def save_story_mode(map_id: int, field_id: int, tile_pos: str, state: dict) -> dict:
    """
    POST /story-mode/save
    Lưu tiến trình story mode.
    map_id: StoryMap ID (ví dụ 1010100)
    field_id: StoryField ID hiện tại
    tile_pos: vị trí tile "x,y"
    """
    return post("/story-mode/save", {
        "mapId": map_id,
        "fieldId": field_id,
        "tilePos": tile_pos,
        "state": state,
    })


def delete_story_mode() -> dict:
    """POST /story-mode/delete - xóa save data story mode"""
    return post("/story-mode/delete")


def get_chest_reward(chest_id: int) -> dict:
    """POST /story-mode/chest-reward"""
    return post("/story-mode/chest-reward", {"chestId": chest_id})


def get_challenge_info() -> dict:
    """GET /story-mode/challenge/info"""
    return get("/story-mode/challenge/info")


def receive_challenge_reward(stage_id: int, star_count: int) -> dict:
    """POST /story-mode/challenge/reward"""
    return post("/story-mode/challenge/reward", {"stageId": stage_id, "starCount": star_count})


if __name__ == "__main__":
    import json
    print("=== Fetch Story Mode ===")
    try:
        result = fetch_story_mode()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error (cần login): {e}")
