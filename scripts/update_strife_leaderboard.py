#!/usr/bin/env python3
"""
Update Strife (Colosseum) leaderboard data for GitHub Pages.

Fetches the Top 100 ranking data and Season metadata from official KGC API
and exports structured JSON to docs/strife-leaderboard-data.json.
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "api"))
import config

OUTPUT_JSON = REPO_ROOT / "docs" / "strife-leaderboard-data.json"


def load_hero_names() -> dict:
    """Map unit ID (str) -> English & Korean hero name."""
    names = {}
    strings_en = REPO_ROOT / "server" / "xml_live" / "Strings_EN_US.xml"
    if strings_en.exists():
        try:
            tree = ET.parse(strings_en)
            for s in tree.getroot().findall("String"):
                k = s.attrib.get("Key", "")
                if k.startswith("UnitName_"):
                    uid = k.replace("UnitName_", "")
                    names[uid] = s.text or ""
        except Exception as e:
            print(f"[!] Warning reading Strings_EN_US: {e}")
    return names


def load_master_data_tiers() -> dict:
    """Load official localized tier names directly from master data XMLs."""
    def parse_strings(xml_path: Path) -> dict:
        res = {}
        if xml_path.exists():
            tree = ET.parse(xml_path)
            for s in tree.getroot().findall("String"):
                res[s.attrib.get("Key", "")] = s.text or ""
        return res

    xml_dir = REPO_ROOT / "server" / "xml_live"
    strings_vi = parse_strings(xml_dir / "Strings_VI.xml")
    strings_en = parse_strings(xml_dir / "Strings_EN_US.xml")
    strings_kr = parse_strings(xml_dir / "Strings_KR.xml")

    tier_map = {}
    tier_xml = xml_dir / "ColosseumRankTiers.xml"
    if tier_xml.exists():
        tree = ET.parse(tier_xml)
        for t in tree.getroot().findall("ColosseumRankTier"):
            tid = int(t.attrib["ID"])
            nc = t.find("NameComment").text if t.find("NameComment") is not None else ""
            icon = t.find("TierIcon").text if t.find("TierIcon") is not None else ""

            base_group = tid // 10
            star = tid % 10

            base_vi = strings_vi.get(f"RankTier_{base_group}", "")
            base_en = strings_en.get(f"RankTier_{base_group}", "")
            base_kr = strings_kr.get(f"RankTier_{base_group}", "")

            if base_group == 8:
                group = "king-god"
                if tid == 82:
                    color = "#ffd700"
                    vi_suffix = " (Hạng 1)"
                    en_suffix = " (Rank 1)"
                elif tid == 81:
                    color = "#e0e0e0"
                    vi_suffix = " (Hạng 2~5)"
                    en_suffix = " (Rank 2~5)"
                else:
                    color = "#cd7f32"
                    vi_suffix = " (Hạng 6~10)"
                    en_suffix = " (Rank 6~10)"
                name_vi = f"{base_vi}{vi_suffix}"
                name_en = f"{base_en}{en_suffix}"
            elif base_group == 7:
                group = "god"
                if tid == 71:
                    color = "#a855f7"
                    vi_suffix = "+ (Hạng 11~30)"
                    en_suffix = "+ (Rank 11~30)"
                else:
                    color = "#6366f1"
                    vi_suffix = " (Hạng 31~100)"
                    en_suffix = " (Rank 31~100)"
                name_vi = f"{base_vi}{vi_suffix}"
                name_en = f"{base_en}{en_suffix}"
            elif base_group == 6:
                group = "king"
                color = "#ec4899"
                suffix = "+" if tid == 61 else ""
                name_vi = f"{base_vi}{suffix}"
                name_en = f"{base_en}{suffix}"
            elif base_group == 5:
                group = "diamond"
                color = "#00d2d3"
                s_txt = f" {star}★" if star > 0 else ""
                name_vi = f"{base_vi}{s_txt}"
                name_en = f"{base_en}{s_txt}"
            elif base_group == 4:
                group = "platinum"
                color = "#48dbfb"
                s_txt = f" {star}★" if star > 0 else ""
                name_vi = f"{base_vi}{s_txt}"
                name_en = f"{base_en}{s_txt}"
            elif base_group == 3:
                group = "gold"
                color = "#feca57"
                s_txt = f" {star}★" if star > 0 else ""
                name_vi = f"{base_vi}{s_txt}"
                name_en = f"{base_en}{s_txt}"
            elif base_group == 2:
                group = "silver"
                color = "#c8d6e5"
                s_txt = f" {star}★" if star > 0 else ""
                name_vi = f"{base_vi}{s_txt}"
                name_en = f"{base_en}{s_txt}"
            else:
                group = "bronze"
                color = "#a29bfe"
                s_txt = f" {star}★" if star > 0 else ""
                name_vi = f"{base_vi}{s_txt}"
                name_en = f"{base_en}{s_txt}"

            tier_map[tid] = {
                "id": tid,
                "vi": name_vi,
                "en": name_en,
                "kr": nc,
                "icon": icon,
                "group": group,
                "color": color,
            }
    return tier_map


def fetch_leaderboard_data() -> dict:
    print("[*] Fetching /colosseum season info...")
    col = config.get("/colosseum")
    season = col.get("season", 73) if isinstance(col, dict) else 73
    season_until = col.get("seasonUntilAtDates", []) if isinstance(col, dict) else []
    next_start = col.get("nextSeasonStartAtDates", []) if isinstance(col, dict) else []

    print(f"[*] Fetching /ranking/colosseum-ranking for season {season}...")
    res = config.get(f"/ranking/colosseum-ranking?season={season}&useCache=true")
    if not isinstance(res, dict) or "ranking" not in res:
        raise ValueError(f"Failed to fetch ranking: {res}")

    raw_ranking = res.get("ranking", [])
    player_rank = res.get("playerRank", {})
    hero_names = load_hero_names()
    master_tiers = load_master_data_tiers()

    formatted_ranking = []
    for entry in raw_ranking:
        p_icon = str(entry.get("profileIcon", 0))
        h_name = hero_names.get(p_icon, "")
        t_id = entry.get("tier", 0)
        tier_info = master_tiers.get(t_id, {
            "id": t_id,
            "vi": f"Bậc {t_id}",
            "en": f"Tier {t_id}",
            "kr": f"Tier {t_id}",
            "group": "other",
            "color": "var(--muted)",
        })

        formatted_ranking.append({
            "rank": entry.get("rank"),
            "score": entry.get("score"),
            "accountId": entry.get("accountId"),
            "userName": entry.get("userName") or "Unknown",
            "castleName": entry.get("castleName") or "",
            "tier": entry.get("tier"),
            "tierInfo": tier_info,
            "profileIcon": entry.get("profileIcon"),
            "heroName": h_name,
            "flagId": entry.get("flagId"),
            "nameTagId": entry.get("nameTagId"),
        })

    # Summary statistics
    top_score = formatted_ranking[0]["score"] if formatted_ranking else 0
    top_10_cutoff = formatted_ranking[9]["score"] if len(formatted_ranking) >= 10 else 0
    top_100_cutoff = formatted_ranking[-1]["score"] if formatted_ranking else 0

    end_time_iso = season_until[0] if season_until else None

    result = {
        "updatedAt": datetime.now().isoformat(),
        "season": season,
        "seasonEndTime": end_time_iso,
        "seasonStartTime": next_start[0] if next_start else None,
        "totalRanked": len(formatted_ranking),
        "summary": {
            "topScore": top_score,
            "top10Cutoff": top_10_cutoff,
            "top100Cutoff": top_100_cutoff,
            "top1Player": formatted_ranking[0] if formatted_ranking else None,
            "top2Player": formatted_ranking[1] if len(formatted_ranking) > 1 else None,
            "top3Player": formatted_ranking[2] if len(formatted_ranking) > 2 else None,
        },
        "ranking": formatted_ranking,
    }
    return result


def main():
    print("=" * 60)
    print("  KGC Strife Leaderboard Data Updater")
    print("=" * 60)

    if not config.SESSION.headers.get("accesstoken"):
        print("[!] Error: No accesstoken found! Please set KGC_TOKEN env var or provide captured_token.txt.")
        return 1

    try:
        data = fetch_leaderboard_data()
        OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"\n[+] Successfully updated {OUTPUT_JSON}!")
        print(f"    Season: {data['season']}")
        print(f"    Top 1: {data['summary']['top1Player']['userName']} ({data['summary']['topScore']} pts)")
        print(f"    Top 10 Cutoff: {data['summary']['top10Cutoff']} pts")
        print(f"    Total Players: {data['totalRanked']}")

        # Directly sync snapshot into docs/strife-leaderboard.html if present
        html_file = REPO_ROOT / "docs" / "strife-leaderboard.html"
        if html_file.exists():
            html_text = html_file.read_text(encoding="utf-8")
            pattern = r'(<script id="embedded-data" type="application/json">)(.*?)(</script>)'
            if re.search(pattern, html_text, flags=re.DOTALL):
                new_embedded = json.dumps(data, ensure_ascii=False, indent=2)
                updated_html = re.sub(
                    pattern,
                    rf'\g<1>\n{new_embedded}\n  \g<3>',
                    html_text,
                    flags=re.DOTALL
                )
                html_file.write_text(updated_html, encoding="utf-8")
                print(f"[+] Synced snapshot directly into {html_file}")

        return 0
    except Exception as e:
        print(f"\n[!] Error updating leaderboard: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
