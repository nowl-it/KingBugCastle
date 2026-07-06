"""
Colosseum APIs - PvE colosseum mode
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


def fetch_colosseum() -> dict:
    """GET /colosseum"""
    return get("/colosseum")


def colosseum_match() -> dict:
    """POST /colosseum/match - tìm trận"""
    return post("/colosseum/match")


def cancel_match() -> dict:
    """POST /colosseum/match/cancel"""
    return post("/colosseum/match/cancel")


def ping_match(game_id: str) -> dict:
    """POST /colosseum/match/ping"""
    return post("/colosseum/match/ping", {"gameId": game_id})


def get_server_address(game_id: str) -> dict:
    """GET /colosseum/server-address?gameId={id}"""
    return get("/colosseum/server-address", params={"gameId": game_id})


def fetch_players_data(game_id: str = "") -> dict:
    """GET /colosseum/fetch-players-data?gameId={id}"""
    params = {"gameId": game_id} if game_id else {}
    return get("/colosseum/fetch-players-data", params=params)


def get_round_data(game_id: str) -> dict:
    """GET /colosseum/round-data?gameId={id}"""
    return get("/colosseum/round-data", params={"gameId": game_id})


def complete_round_data(game_id: str, round_data: dict) -> dict:
    """POST /colosseum/complete-round-data"""
    return post("/colosseum/complete-round-data", {"gameId": game_id, **round_data})


def check_end(game_id: str) -> dict:
    """GET /colosseum/check-end?gameId={id}"""
    return get("/colosseum/check-end", params={"gameId": game_id})


def reenter_tried(game_id: str) -> dict:
    """POST /colosseum/reenter-tried?gameId={id}"""
    return post("/colosseum/reenter-tried", params={"gameId": game_id})


def reenter_succeed(game_id: str) -> dict:
    """POST /colosseum/reenter-succeed?gameId={id}"""
    return post("/colosseum/reenter-succeed", params={"gameId": game_id})


def get_reward(index: int, game_end_reward_index: int, game_id: str, upgrade: int = 0) -> dict:
    """GET /colosseum/get-reward?index={i}&gameEndRewardIndex={j}&gameId={id}&upgrade={u}"""
    return get("/colosseum/get-reward", params={
        "index": index,
        "gameEndRewardIndex": game_end_reward_index,
        "gameId": game_id,
        "upgrade": upgrade,
    })


def get_all_tier_rewards() -> dict:
    """GET /colosseum/all-tier-rewards"""
    return get("/colosseum/all-tier-rewards")


def open_mission_reward(reward_idx: int) -> dict:
    """POST /colosseum/open-mission-reward?rewardIdx={i}"""
    return post("/colosseum/open-mission-reward", params={"rewardIdx": reward_idx})


def record_minimum_rank(game_id: str, rank: int) -> dict:
    """POST /colosseum/record-minimum-rank?gameId={id}&rank={rank}"""
    return post("/colosseum/record-minimum-rank", params={"gameId": game_id, "rank": rank})


def fetch_statistics() -> dict:
    """GET /colosseum/fetch-statistics-data"""
    return get("/colosseum/fetch-statistics-data")


def fetch_log_history(model: dict) -> dict:
    """POST /colosseum/fetch-log-history"""
    return post("/colosseum/fetch-log-history", model)


def fetch_log_detail(model: dict) -> dict:
    """POST /colosseum/fetch-log-detail"""
    return post("/colosseum/fetch-log-detail", model)


def create_custom_match(settings: dict) -> dict:
    """POST /colosseum/create-custom-match"""
    return post("/colosseum/create-custom-match", settings)


def join_custom_match(match_id: str) -> dict:
    """POST /colosseum/join-custom-match?matchId={id}"""
    return post("/colosseum/join-custom-match", params={"matchId": match_id})


def get_colosseum_ranking(season: int, use_cache: bool = True) -> dict:
    """GET /ranking/colosseum-ranking?season={season}&useCache={bool}"""
    return get("/ranking/colosseum-ranking", params={"season": season, "useCache": str(use_cache).lower()})


if __name__ == "__main__":
    import json
    print("=== Fetch Colosseum ===")
    try:
        result = fetch_colosseum()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error (cần login): {e}")
