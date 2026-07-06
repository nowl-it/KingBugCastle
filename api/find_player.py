#!/usr/bin/env python3
"""
Find player information by name or Strife Battlefield match ID (gameId).
Usage:
    python3 api/find_player.py --match <gameId>
    python3 api/find_player.py --name <playerName>
    python3 api/find_player.py --id <accountId>
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import SESSION
from api.player.player import get_other_player
from api.colosseum.colosseum import fetch_players_data
from api.ranking.ranking import get_ranking, get_colosseum_ranking


def search_by_match(game_id: str):
    print(f"[*] Fetching player data for Strife match ID: {game_id}...")
    try:
        data = fetch_players_data(game_id)
        if not data or not isinstance(data, dict):
            print("[-] No data returned.")
            return
            
        players = data.get("colosseumPlayerDataList", [])
        if not players:
            print(f"[-] No players found in match data. Response: {data}")
            return
            
        print(f"\n[+] Found {len(players)} players in match {game_id}:")
        for p in players:
            user_id = p.get("userId", "N/A")
            user_name = p.get("userName", "N/A")
            castle_name = p.get("castleName", "N/A")
            is_bot = p.get("isBot", False)
            bot_tag = " [BOT]" if is_bot else ""
            print(f"  - Account ID: {user_id} | Name: {user_name} (Castle: {castle_name}){bot_tag}")
            
        # Print full JSON output for details
        print("\n=== Detailed JSON Output ===")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"[-] Error: {e}")


def search_by_id(account_id: int):
    print(f"[*] Fetching profile for account ID: {account_id}...")
    try:
        profile = get_other_player(account_id)
        if not profile or not isinstance(profile, dict):
            print("[-] No profile returned.")
            return
            
        print("\n=== Player Profile ===")
        print(f"Name: {profile.get('name', 'N/A')}")
        print(f"Castle: {profile.get('castleName', 'N/A')}")
        print(f"Level: {profile.get('level', 'N/A')}")
        print(f"Best Clear: Theme {profile.get('bestClearedTheme', 'N/A')} Stage {profile.get('bestClearedStage', 'N/A')}")
        print(f"Played Count: {profile.get('playedCount', 0)} (Wins: {profile.get('winCount', 0)})")
        
        print("\n=== Full Profile JSON ===")
        print(json.dumps(profile, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[-] Error: {e}")


def search_by_name(player_name: str):
    print(f"[*] Searching for player '{player_name}' in ranking databases...")
    
    def do_search(exact: bool):
        found = []
        # 1. Search in normal ranking
        try:
            norm_rank = get_ranking(theme=1, use_cache=True)
            if isinstance(norm_rank, dict):
                for entry in norm_rank.get("ranking", []):
                    uname = entry.get("userName", "")
                    if (exact and uname.lower() == player_name.lower()) or (not exact and (player_name.lower() in uname.lower() or uname.lower() in player_name.lower())):
                        entry["source"] = "Normal Stage Ranking"
                        found.append(entry)
        except Exception as e:
            pass

        # 2. Search in colosseum (Strife) ranking
        try:
            col_rank = get_colosseum_ranking(season=69, use_cache=True) # current season
            if isinstance(col_rank, dict):
                for entry in col_rank.get("ranking", []):
                    uname = entry.get("userName", "")
                    if (exact and uname.lower() == player_name.lower()) or (not exact and (player_name.lower() in uname.lower() or uname.lower() in player_name.lower())):
                        entry["source"] = "Strife (Colosseum) Ranking"
                        found.append(entry)
        except Exception as e:
            pass

        # 3. Search in local ranking.json
        try:
            json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ranking.json")
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    local_data = json.load(f)
                
                def scan_local_ranking(rank_data, label):
                    if isinstance(rank_data, dict):
                        data_part = rank_data.get("data")
                        entries = data_part.get("ranking", []) if isinstance(data_part, dict) else []
                        for entry in entries:
                            uname = entry.get("userName", "")
                            if uname:
                                if (exact and uname.lower() == player_name.lower()) or (not exact and (player_name.lower() in uname.lower() or uname.lower() in player_name.lower())):
                                    if not any(x.get("accountId") == entry.get("accountId") for x in found):
                                        entry["source"] = f"ranking.json ({label})"
                                        found.append(entry)
                
                scan_local_ranking(local_data.get("season_ranking"), "Season Ranking")
                scan_local_ranking(local_data.get("league_ranking"), "League Ranking")
                scan_local_ranking(local_data.get("hall_of_fame"), "Hall of Fame")
        except Exception as e:
            pass
        return found

    # Try exact match first
    found_players = do_search(exact=True)
    
    # Try partial match if no exact match found
    if not found_players:
        print("[*] No exact match found. Searching for partial matches...")
        found_players = do_search(exact=False)

    if not found_players:
        print(f"[-] Player '{player_name}' not found in top rankings. Try looking up by Account ID directly if you have it.")
        return

    print(f"\n[+] Found {len(found_players)} matches in rankings:")
    for fp in found_players:
        account_id = fp.get("accountId")
        print(f"  - Account ID: {account_id} | Name: {fp.get('userName')} (Castle: {fp.get('castleName')})")
        print(f"    Source: {fp.get('source')} | Rank: {fp.get('rank')} | Score/Tier: {fp.get('score', fp.get('tier'))}")
        
    # Automatically lookup the first match
    first_id = found_players[0].get("accountId")
    print(f"\n[*] Fetching full profile for first match (ID: {first_id})...")
    search_by_id(first_id)


def main():
    parser = argparse.ArgumentParser(description="Find KGC players and match data.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--match", help="Strife gameId (match ID)")
    group.add_argument("--name", help="Player username")
    group.add_argument("--id", type=int, help="Player account ID")
    
    args = parser.parse_args()
    
    if not SESSION.headers.get("accesstoken"):
        print("[-] Error: no token. Set KGC_TOKEN env or put one in captured_token.txt.", file=sys.stderr)
        sys.exit(2)
        
    if args.match:
        search_by_match(args.match)
    elif args.id:
        search_by_id(args.id)
    elif args.name:
        search_by_name(args.name)


if __name__ == "__main__":
    main()
