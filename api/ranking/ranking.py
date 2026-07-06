"""
Ranking APIs - normal, PvP, Colosseum, Roguelike, Dimension Rift
Ranking server: https://kgc-ranking-1.awesomepiece.com
Main server: https://kgc-k8s-1.awesomepiece.com
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get

CLOUD_RUN_BASE = "https://kgc-ranking-1.awesomepiece.com"


def get_ranking(theme: int, use_cache: bool = True) -> dict:
    """
    GET /ranking/ranking?theme={theme}&useCache={bool}
    Normal stage ranking theo theme.
    theme: 1=Normal, 2=Challenge, v.v.
    """
    return get("/ranking/ranking", params={"theme": theme, "useCache": str(use_cache).lower()})


def get_challenge_mode_ranking(season: int, use_cache: bool = True) -> dict:
    """GET /ranking/challenge-mode-ranking?season={season}&useCache={bool}"""
    return get("/ranking/challenge-mode-ranking", params={"season": season, "useCache": str(use_cache).lower()})


def get_pvp_ranking(season: int, use_cache: bool = True) -> dict:
    """GET /ranking/pvp-ranking?season={season}&useCache={bool}"""
    return get("/ranking/pvp-ranking", params={"season": season, "useCache": str(use_cache).lower()})


def get_pvp_league_ranking(league_season: int, use_cache: bool = False) -> dict:
    """GET /ranking/pvp-league-ranking?leagueSeason={season}&useCache={bool}"""
    return get("/ranking/pvp-league-ranking", params={"leagueSeason": league_season, "useCache": str(use_cache).lower()})


def get_pvp_hall_of_fame(league_season: int, use_cache: bool = False) -> dict:
    """GET /ranking/pvp-hall-of-fame?leagueSeason={season}&useCache={bool}"""
    return get("/ranking/pvp-hall-of-fame", params={"leagueSeason": league_season, "useCache": str(use_cache).lower()})


def get_colosseum_ranking(season: int, use_cache: bool = True) -> dict:
    """GET /ranking/colosseum-ranking?season={season}&useCache={bool}"""
    return get("/ranking/colosseum-ranking", params={"season": season, "useCache": str(use_cache).lower()})


def get_colosseum_league_ranking(league_season: int, use_cache: bool = True) -> dict:
    """GET /ranking/colosseum-league-ranking?leagueSeason={season}&useCache={bool}"""
    return get("/ranking/colosseum-league-ranking", params={"leagueSeason": league_season, "useCache": str(use_cache).lower()})


def get_colosseum_hall_of_fame(league_season: int, use_cache: bool = True) -> dict:
    """GET /ranking/colosseum-hall-of-fame?leagueSeason={season}&useCache={bool}"""
    return get("/ranking/colosseum-hall-of-fame", params={"leagueSeason": league_season, "useCache": str(use_cache).lower()})


def get_roguelike_ranking(challenge: int, use_cache: bool = True) -> dict:
    """GET /ranking/roguelike-ranking?challenge={challenge}&useCache={bool}"""
    return get("/ranking/roguelike-ranking", params={"challenge": challenge, "useCache": str(use_cache).lower()})


def get_roguelike_building_ranking(building: int, use_cache: bool = True) -> dict:
    """GET /ranking/roguelike-building-ranking?building={building}&useCache={bool}"""
    return get("/ranking/roguelike-building-ranking", params={"building": building, "useCache": str(use_cache).lower()})


def get_dimension_rift_ranking(use_cache: bool = True) -> dict:
    """GET /ranking/dimension-rift-ranking?useCache={bool}"""
    return get("/ranking/dimension-rift-ranking", params={"useCache": str(use_cache).lower()})


def get_unit_statistics(unit_id: int, force_refresh: bool = False) -> dict:
    """
    GET /statistics/unit?id={unit_id}&forceRefresh={bool}
    Thống kê usage của một hero cụ thể.
    """
    return get("/statistics/unit", params={"id": unit_id, "forceRefresh": str(force_refresh).lower()})


if __name__ == "__main__":
    import json

    print("=== Normal Ranking (theme=1) ===")
    try:
        result = get_ranking(theme=1, use_cache=True)
        if isinstance(result, dict):
            print(f"Keys: {list(result.keys())}")
            # In top 3 nếu có
            entries = result.get("entries", result.get("ranking", []))
            for e in entries[:3]:
                print(json.dumps(e, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")

    print("\n=== Unit Statistics (Garam #10580) ===")
    try:
        result = get_unit_statistics(10580)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")
