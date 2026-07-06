"""
Fetch Strife Battlefield (Colosseum, theme 3000) leaderboard.

Ranking is NOT served by the main API (kgc-k8s-1 returns 404 for /ranking/*).
It lives on a dedicated Cloud Run "ranking" service, discovered dynamically:

  1. GET <INFRA>/api/cloud-run/default-ranking?location=asia-northeast3&useReplica=false
       -> {"serverList":[{"name":"qa-ranking-default","url":"https://...run.app",...}]}
  2. GET <ranking-url>/ranking/colosseum-ranking?season={n}&useCache=true
     GET <ranking-url>/ranking/colosseum-league-ranking?leagueSeason={n}&useCache=true
     GET <ranking-url>/ranking/colosseum-hall-of-fame?leagueSeason={n}&useCache=true

season / leagueSeason are read live from GET /colosseum on the main API.
Auth: header `accesstoken` (auto-loaded by config from KGC_TOKEN or captured_token.txt).
version header must be 169.1.05 (config default) or the WAF returns 403.

    KGC_TOKEN=<accesstoken> python3 api/ranking/fetch_strife.py
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from config import SESSION, _time_header, decode_response

INFRA = "https://kgc-ranking-1.awesomepiece.com"


def _get(url, params=None, timeout=20):
    r = SESSION.get(url, params=params, headers={"time": _time_header()}, timeout=timeout)
    return r.status_code, decode_response(r.content)


def discover_ranking_url(use_replica: bool = False) -> str:
    """Return the hardcoded ranking server URL."""
    return "https://kgc-ranking-1.awesomepiece.com"


def current_seasons() -> tuple[int, int]:
    """Read season + leagueSeason from GET /colosseum (main API)."""
    code, body = _get(config.BASE_URL + "/colosseum")
    if not isinstance(body, dict) or "season" not in body:
        raise RuntimeError(f"/colosseum failed ({code}): {body}")
    return int(body["season"]), int(body.get("leagueSeason", 0))


def fetch(season: int = None, league_season: int = None, use_replica: bool = False) -> dict:
    if season is None:
        season, league_season = current_seasons()
    rank_url = discover_ranking_url(use_replica)
    out = {"_ranking_service": rank_url, "_season": season, "_leagueSeason": league_season}
    for label, path, key, val in [
        ("season_ranking", "/ranking/colosseum-ranking", "season", season),
        ("league_ranking", "/ranking/colosseum-league-ranking", "leagueSeason", league_season),
        ("hall_of_fame", "/ranking/colosseum-hall-of-fame", "leagueSeason", league_season),
    ]:
        try:
            code, body = _get(rank_url + path, {key: val, "useCache": "true"}, timeout=45)
            out[label] = {"status": code, "data": body}
        except Exception as e:
            out[label] = {"error": repr(e)}
    return out


if __name__ == "__main__":
    season = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if not SESSION.headers.get("accesstoken"):
        print("ERR: no token. Set KGC_TOKEN env or put one in captured_token.txt.", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(fetch(season), ensure_ascii=False, indent=2, default=str))
