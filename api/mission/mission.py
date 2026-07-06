"""
Mission APIs - check, receive rewards, post box
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def get_all_missions() -> dict:
    """GET /mission - toàn bộ missions"""
    return get("/mission")


def check_missions(cond_types: list) -> dict:
    """
    POST /mission/check?
    cond_types: list condition type strings để check
    Ví dụ: ["StageWin", "UnitLevelUp"]
    """
    return post("/mission/check", params={"condTypes": ",".join(cond_types)})


def receive_all_mission_rewards(reward_types: list = None) -> dict:
    """POST /mission/reward-all"""
    return post("/mission/reward-all", {"rewardTypes": reward_types or []})


def receive_goal_reward() -> dict:
    """POST /mission/reward/goal"""
    return post("/mission/reward/goal")


def get_all_posts() -> dict:
    """GET /post - toàn bộ post box (mail)"""
    return get("/post")


def receive_post(post_ids: list) -> dict:
    """POST /post/receive - nhận items từ post box"""
    return post("/post/receive", {"postIds": post_ids})


def get_season_pass() -> dict:
    """GET /pass"""
    return get("/pass")


def get_all_pass_rewards() -> dict:
    """GET /pass/all-rewards"""
    return get("/pass/all-rewards")


def receive_pass_reward(reward_idx: int, is_premium: bool = False) -> dict:
    """POST /pass/reward"""
    return post("/pass/reward", {"rewardIdx": reward_idx, "isPremium": is_premium})


def receive_pass_bonus_reward(reward_idx: int) -> dict:
    """POST /pass/bonusReward"""
    return post("/pass/bonusReward", {"rewardIdx": reward_idx})


def receive_all_pass_rewards(is_premium: bool = False) -> dict:
    """POST /pass/all-rewards"""
    return post("/pass/all-rewards", {"isPremium": is_premium})


def buy_pass_level(count: int = 1) -> dict:
    """POST /pass/buyLevel"""
    return post("/pass/buyLevel", {"count": count})


def get_pass_event_booster() -> dict:
    """GET /pass/passEventBooster"""
    return get("/pass/passEventBooster")


def reroll_pass_mission(mission_id: int) -> dict:
    """POST /pass/reroll-mission"""
    return post("/pass/reroll-mission", {"missionId": mission_id})


if __name__ == "__main__":
    import json
    print("=== Get All Missions ===")
    try:
        result = get_all_missions()
        if isinstance(result, dict):
            print(f"Keys: {list(result.keys())}")
    except Exception as e:
        print(f"Error (cần login): {e}")

    print("\n=== Get All Posts ===")
    try:
        result = get_all_posts()
        if isinstance(result, dict):
            posts = result.get("posts", [])
            print(f"Posts count: {len(posts)}")
    except Exception as e:
        print(f"Error: {e}")
