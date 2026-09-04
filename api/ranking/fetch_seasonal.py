"""Fetch the current Arena and Strife Battlefield seasonal leaderboards.

The main API supplies the current season number. Ranking data comes from the
separate production service, so requests must preserve the game's ``accesstoken``
and current ``version`` headers.

    KGC_TOKEN=<accesstoken> python3 api/ranking/fetch_seasonal.py
    KGC_TOKEN=<accesstoken> python3 api/ranking/fetch_seasonal.py --pvp-season 72
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config


RANKING_URL = "https://kgc-ranking-1.awesomepiece.com"
MODES = {
    "pvp": {"info_path": "/pvp/info", "ranking_path": "/ranking/pvp-ranking"},
    "colosseum": {
        "info_path": "/colosseum",
        "ranking_path": "/ranking/colosseum-ranking",
    },
}


def _get(url, params=None, timeout=30):
    response = config.SESSION.get(
        url, params=params, headers={"time": config._time_header()}, timeout=timeout
    )
    return response.status_code, config.decode_response(response.content)


def current_season(mode: str) -> int:
    """Read the active season from the owning main-API mode endpoint."""
    spec = MODES[mode]
    status, body = _get(config.BASE_URL + spec["info_path"])
    if not isinstance(body, dict) or "season" not in body:
        raise RuntimeError(f"{spec['info_path']} failed ({status}): {body}")
    return int(body["season"])


def fetch_mode(mode: str, season: int | None = None, use_cache: bool = True) -> dict:
    """Return the mode's active or requested seasonal ranking response."""
    spec = MODES[mode]
    if season is None:
        season = current_season(mode)
    status, body = _get(
        RANKING_URL + spec["ranking_path"],
        {"season": season, "useCache": str(use_cache).lower()},
        timeout=45,
    )
    return {"season": season, "status": status, "data": body}


def fetch(pvp_season: int | None = None, colosseum_season: int | None = None,
          use_cache: bool = True) -> dict:
    return {
        "rankingService": RANKING_URL,
        "pvp": fetch_mode("pvp", pvp_season, use_cache),
        "colosseum": fetch_mode("colosseum", colosseum_season, use_cache),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pvp-season", type=int)
    parser.add_argument("--colosseum-season", type=int)
    parser.add_argument("--fresh", action="store_true", help="set useCache=false")
    args = parser.parse_args()
    if not config.SESSION.headers.get("accesstoken"):
        print("ERR: set KGC_TOKEN or create captured_token.txt with an accesstoken.", file=sys.stderr)
        return 2
    print(json.dumps(
        fetch(args.pvp_season, args.colosseum_season, not args.fresh),
        ensure_ascii=False, indent=2, default=str,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
