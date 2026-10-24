"""Guard the v174.1.00 client/server version bump.

The three features the v174.1.00 client introduced had no server mapping at all, so
each was answered with a bare `ResponseModel` - the right AES envelope, none of the
fields the client deserializes, which reads as a null list / NullReference rather
than "not implemented yet". This pins each new route to its real RestAPI response
model (read from generated/restapi.json, not guessed) and asserts `build_model`
produces that model's full field set, so a future version bump that drops a mapping
fails here instead of in game.

Unlike test_route_coverage.py (whose `check_*` functions are run as a script, not
collected by pytest), these are `test_*` so CI actually executes them.
"""
import json, sys
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
# Do NOT touch playerdb.DB_PATH at module scope - other test files set their own
# temp DB at import and rely on that assignment being the last one before their
# tests run. The one test here that needs a live save uses `tmp_path`/`monkeypatch`
# so the redirect is undone after the test.

import config
import server

# path -> (RestAPI method, response model) exactly as declared in dump.cs.
V174_ROUTES = {
    "/incarnation-unit/overcome":      ("IncarnationOvercome",             "IncarnationOvercomeResponseModel"),
    "/single-arena/info":              ("FetchSingleArenaInfo",             "SingleArenaInfoResponseModel"),
    "/single-arena/matching":          ("SingleArenaMatching",              "SingleArenaMatchResponseModel"),
    "/single-arena/matching-reroll":   ("SingleArenaMatchingReroll",        "SingleArenaMatchResponseModel"),
    "/single-arena/fetch-log-history": ("FetchSingleArenaLogHistory",       "SingleArenaLogResponseModel"),
    "/single-arena/mission-reward":    ("ReceiveSingleArenaMissionReward",  "SingleArenaRewardResponseModel"),
    "/single-arena/rank-reward":       ("ReceiveSingleArenaRankReward",     "SingleArenaRewardResponseModel"),
    "/single-arena/rank-all-rewards":  ("ReceiveSingleArenaRankAllRewards", "SingleArenaRewardResponseModel"),
    "/single-arena/reward-info":       ("FetchSingleArenaRewardInfo",       "SingleArenaRewardInfoResponseModel"),
    "/ranking/single-arena-ranking":   ("GetSingleArenaRanking",            "SingleArenaRankingResponseModel"),
}


def test_v174_routes_are_mapped_to_real_models():
    models = json.loads((config.GENERATED / "models.json").read_text())
    routes = config.load_route_models()
    for path, (_method, resp) in V174_ROUTES.items():
        assert path in routes, f"{path} is not routed"
        assert routes[path]["response"] == resp, \
            f"{path} -> {routes[path]['response']}, expected {resp}"
        assert resp in models, f"{resp} missing from models.json (stale generated?)"


def test_v174_build_model_is_not_bare():
    """A mapped route must answer its real shape, not {code, msg, success}."""
    for path, (_method, resp) in V174_ROUTES.items():
        payload = server.build_model(resp)
        assert payload["code"] == 200
        spec_fields = {f["name"] for f in
                       json.loads((config.GENERATED / "models.json").read_text())[resp]["fields"]}
        missing = spec_fields - set(payload)
        assert not missing, f"{path} ({resp}) answered without fields: {sorted(missing)}"


def test_incarnation_overcome_shape_has_expected_fields():
    payload = server.build_model("IncarnationOvercomeResponseModel")
    assert "unit" in payload and "remainTicket" in payload


def test_auth_next_day_is_handled_and_mints_a_token(tmp_path, monkeypatch):
    """/auth/next-day must return a real accessToken for the live session, not an
    empty AuthResponseModel (a null accessToken overwrites the stored token)."""
    assert "/auth/next-day" in server.OVERRIDES, "no handler for /auth/next-day"
    monkeypatch.setattr(playerdb, "DB_PATH", tmp_path / "v174.db")
    playerdb.init()
    playerdb.save("v174-nextday", {"uid": "v174-nextday"})
    st = playerdb.load("v174-nextday")
    out = server.OVERRIDES["/auth/next-day"]({}, st)
    assert out.get("accessToken"), out
    assert out.get("serverTime") and out.get("expiredAt")
