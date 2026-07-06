#!/usr/bin/env python3
"""
Search for players within clans.
Usage:
    python3 api/search_by_clan.py --clan <clanName>
    python3 api/search_by_clan.py --clan <clanName> --player <playerName>
    python3 api/search_by_clan.py --clan <clanName> --json
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.config import SESSION, post
from api.clan.clan import fetch_other_clan

def search_by_clan(clan_keyword: str, player_keyword: str = None, output_json: bool = False):
    if not output_json:
        print(f"[*] Searching for clans matching keyword: '{clan_keyword}'...")
        
    try:
        # Call the POST /clan/search endpoint
        response = post("/clan/search", {
            "keyword": clan_keyword,
            "tags": [],
            "searchStartOffset": 0
        })
        
        if not response or not isinstance(response, dict):
            if output_json:
                print(json.dumps({"error": "No response from server"}, indent=2))
            else:
                print("[-] No response from server.")
            return
            
        clans = response.get("resultClans", [])
        if not clans:
            if output_json:
                print(json.dumps([], indent=2))
            else:
                print(f"[-] No clans found matching '{clan_keyword}'.")
            return
            
        json_results = []
        
        if not output_json:
            print(f"[+] Found {len(clans)} clans:")
            
        for clan in clans:
            clan_name = clan.get("name", "N/A")
            clan_id = clan.get("id", "N/A")
            member_count = clan.get("memberCount", 0)
            max_members = clan.get("maxMemberCount", 20)
            master_name = clan.get("masterName", "N/A")
            
            if not output_json:
                print(f"\n--- Clan: {clan_name} (ID: {clan_id}) | Members: {member_count}/{max_members} | Master: {master_name} ---")
            
            # Fetch full detailed clan info to ensure we get all members
            try:
                clan_details = fetch_other_clan(clan_id)
                members = clan_details.get("members", [])
            except Exception as e:
                # Fallback to members in search result
                members = clan.get("members", [])
                
            if not members:
                if not output_json:
                    print("    [-] No members list available.")
                continue
                
            matching_members = []
            for member in members:
                user_name = member.get("userName", "")
                castle_name = member.get("castleName", "")
                
                # Check if matches player keyword if provided
                if player_keyword:
                    pk_lower = player_keyword.lower()
                    if pk_lower not in user_name.lower() and pk_lower not in castle_name.lower():
                        continue
                matching_members.append(member)
                
            if output_json:
                clan_data = {
                    "id": clan_id,
                    "name": clan_name,
                    "memberCount": member_count,
                    "maxMemberCount": max_members,
                    "masterName": master_name,
                    "members": matching_members
                }
                json_results.append(clan_data)
            else:
                if not matching_members:
                    if player_keyword:
                        print(f"    [-] No members matching player keyword '{player_keyword}' found in this clan.")
                    else:
                        print("    [-] No members found.")
                    continue
                    
                for m in matching_members:
                    role_val = m.get("role", 1)
                    role_str = "Master" if role_val == 10 else "Sub-Master" if role_val == 9 else "Member"
                    print(f"  - Account ID: {m.get('accountId')} | Name: {m.get('userName')} (Castle: {m.get('castleName')}) | Role: {role_str} | Level: {m.get('playerLevel')} | Last Login: {m.get('lastLogined')}")
                    
        if output_json:
            print(json.dumps(json_results, indent=2, ensure_ascii=False))
            
    except Exception as e:
        if output_json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print(f"[-] Error searching clans: {e}")

def main():
    parser = argparse.ArgumentParser(description="Search for players in clans.")
    parser.add_argument("--clan", required=True, help="Clan name keyword to search for")
    parser.add_argument("--player", help="Optional player name/castle name keyword to filter by")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    
    args = parser.parse_args()
    
    if not SESSION.headers.get("accesstoken"):
        print("[-] Error: no token. Set KGC_TOKEN env or put one in captured_token.txt.", file=sys.stderr)
        sys.exit(2)
        
    search_by_clan(args.clan, args.player, args.json)

if __name__ == "__main__":
    main()
