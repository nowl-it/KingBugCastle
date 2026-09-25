"""Tests for Dimension Rift Phase 16 and seasonal challenge endpoint."""
import datetime
import sys
import tempfile
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

from tests.seed import one_account
one_account()
import server


def test_dimension_rift_season_info_returns_enabled():
    st = server.load_state()
    handler = server.OVERRIDES["/rogueLike/season-info"]
    out = handler({"themeId": 2100}, st)

    assert out.get("seasonEnabled") is True, f"seasonEnabled should be True, got {out}"
    assert out.get("errorCode") == 0, out
    assert out.get("seasonalChallengeBossId") > 0, out
    assert len(out.get("seasonalChallengeEliteIds", [])) > 0, out

    # Check ISO date formatting and validity
    start_str = out.get("seasonStartAtDate")
    until_str = out.get("seasonUntilAtDate")
    assert start_str and until_str, f"Missing date strings: {out}"

    now = datetime.datetime.now(datetime.timezone.utc)
    start_dt = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
    until_dt = datetime.datetime.fromisoformat(until_str.replace("Z", "+00:00"))
    assert start_dt <= now < until_dt, f"Season window not active: {start_dt} <= {now} < {until_dt}"

    # Check buffs
    assert isinstance(out.get("seasonalAdvantageBuffId"), int)
    assert isinstance(out.get("seasonalPenaltyBuffId"), int)


def test_dimension_rift_season_info_serves_current_season_effects():
    """The rift effects must come from the SAME season the config serves.
    Regression: r_rogue_season_info read `RCFG[pvpInfo].season` (top level,
    absent) and fell back to the hardcoded default 72, so after the bump to
    season 73 the effects still showed row 72 (South/Shadow) while the season
    title said 73."""
    import json as _json
    from pathlib import Path as _Path
    from config import CONFIG_FILE

    cfg = _json.loads(_Path(CONFIG_FILE).read_text())
    expected_season = cfg["pvpInfo"]["fixed"]["season"]

    st = server.load_state()
    handler = server.OVERRIDES["/rogueLike/season-info"]
    out = handler({"themeId": 2100}, st)

    # The served effect row must match the config season, not the fallback.
    import xml.etree.ElementTree as _ET
    from config import XML_DIR
    root = _ET.parse(XML_DIR / "DimensionRiftSeasonDatas.xml").getroot()
    row = None
    for node in root.findall("DimensionRiftSeasonData"):
        if int(node.get("ID", "0")) == expected_season:
            row = node
            break
    assert row is not None, f"season {expected_season} missing from master data"
    assert out.get("seasonalAdvantageRole") == (row.findtext("SeasonAdvantageRole", "") or "")
    assert out.get("seasonalAdvantageRegion") == (row.findtext("SeasonAdvantageRegion", "") or "")
    assert out.get("seasonalPenaltyRole") == (row.findtext("SeasonPenaltyRole", "") or "")
    assert out.get("seasonalPenaltyRegion") == (row.findtext("SeasonPenaltyRegion", "") or "")
    assert out["seasonalAdvantageBuffId"] == int(row.findtext("SeasonAdvantageBuffId", "0") or 0)
    assert out["seasonalPenaltyBuffId"] == int(row.findtext("SeasonPenaltyBuffId", "0") or 0)
    assert out["seasonalChallengeBossId"] == int(row.findtext("ChallengeBoss", "0") or 0)
    assert out["seasonalChallengeEliteIds"] == [int(x) for x in
        (row.findtext("ChallengeElites", "") or "").split(",") if x.strip().isdigit()]


def test_dimension_rift_phase_16_complete_progression():
    st = server.load_state()
    # Set player as having cleared Phase 15
    st["rogueLikePlayedCount"] = 10
    st["rogueLikeChallenge"] = 15
    server._set_key_value(st, server.DIMENSION_RIFT_PLAY_COUNT, 10)
    server._set_key_value(st, server.DIMENSION_RIFT_MAX_CLEARED_CHALLENGE, 15)
    server.save_state(st)

    complete_fn = server.OVERRIDES["/game/check-dimension-rift-complete-success"]
    res = complete_fn({
        "rogueLikeChallengeLevel": 16,
        "rogueLikeBaseScore": 120000,
        "win": True,
    }, st)

    assert res["rogueLikeScore"] == 120000, res
    st = server.load_state()
    assert st["rogueLikeChallenge"] == 16, f"rogueLikeChallenge should advance to 16, got {st.get('rogueLikeChallenge')}"
    max_cleared = int(server._key_value(st, server.DIMENSION_RIFT_MAX_CLEARED_CHALLENGE))
    assert max_cleared == 16, f"DIMENSION_RIFT_MAX_CHALLENGE should be 16, got {max_cleared}"


if __name__ == "__main__":
    test_dimension_rift_season_info_returns_enabled()
    test_dimension_rift_season_info_serves_current_season_effects()
    test_dimension_rift_phase_16_complete_progression()
    print("All rift season tests passed!")
