"""
PvP APIs - Arena matching, rewards, rankings
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def fetch_pvp_info() -> dict:
    """GET /pvp/info"""
    return get("/pvp/info")


def pvp_matching(deck: list, preset_idx: int = 0) -> dict:
    """
    POST /pvp/matching - tìm đối thủ PvP
    deck: list unit ID
    """
    return post("/pvp/matching", {"deck": deck, "presetIdx": preset_idx})


def test_pvp_matching() -> dict:
    """POST /pvp/test-matching (dev only)"""
    return post("/pvp/test-matching")


def receive_all_pvp_rewards(reward_indexes: list) -> dict:
    """POST /pvp/win-reward - nhận tất cả phần thưởng PvP"""
    return post("/pvp/win-reward", {"rewardIndexes": reward_indexes})


def get_pvp_all_rewards() -> dict:
    """GET /pvp/all-rewards"""
    return get("/pvp/all-rewards")


def pvp_dormant_progress() -> dict:
    """POST /pvp/dormant-progress - tiến trình khi không chơi (dormant)"""
    return post("/pvp/dormant-progress")


def fetch_pvp_statistics() -> dict:
    """GET /pvp/fetch-statistics-data"""
    return get("/pvp/fetch-statistics-data")


def fetch_pvp_log_history(model: dict) -> dict:
    """POST /pvp/fetch-log-history"""
    return post("/pvp/fetch-log-history", model)


def fetch_pvp_log_detail(model: dict) -> dict:
    """POST /pvp/fetch-log-detail"""
    return post("/pvp/fetch-log-detail", model)


def get_pvp_ranking(season: int, use_cache: bool = True) -> dict:
    """GET /ranking/pvp-ranking?season={season}&useCache={bool}"""
    return get("/ranking/pvp-ranking", params={"season": season, "useCache": str(use_cache).lower()})


def get_pvp_league_ranking(league_season: int, use_cache: bool = False) -> dict:
    """GET /ranking/pvp-league-ranking?leagueSeason={season}"""
    return get("/ranking/pvp-league-ranking", params={"leagueSeason": league_season, "useCache": str(use_cache).lower()})


def get_pvp_hall_of_fame(league_season: int, use_cache: bool = False) -> dict:
    """GET /ranking/pvp-hall-of-fame?leagueSeason={season}"""
    return get("/ranking/pvp-hall-of-fame", params={"leagueSeason": league_season, "useCache": str(use_cache).lower()})


if __name__ == "__main__":
    import json
    print("=== Fetch PvP Info ===")
    try:
        result = fetch_pvp_info()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error (cần login): {e}")
