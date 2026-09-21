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
    test_dimension_rift_phase_16_complete_progression()
    print("All rift season tests passed!")
