"""The response contract: every route answers with the fields the client reads.

`route_coverage` grades whether a path has a handler. `test_all_routes_respond`
grades whether it survives being called. Neither notices a route that answers 200
with an empty model - which is what ~30 decoration and mini-game routes did after
they moved into their own modules, because `OVERRIDES` had already been snapshotted
from `DYNAMIC_OVERRIDES` before those groups merged in.

api_audit.py is the report; this is the part that must never regress.
"""
import pathlib
import sys
import tempfile

import pytest

_SERVER = pathlib.Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb

playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "players.db"

import api_audit                                  # noqa: E402
import server                                     # noqa: E402


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """This suite drives every route from one address - but keep the limiter OFF
    only for this module. The pin must not live at import time: pytest imports
    all test modules during collection, so module-level mutations leak the
    disabled limit into every later suite."""
    monkeypatch.setattr(server, "RATE_LIMIT", 0)


def check_every_registered_handler_is_reachable():
    """OVERRIDES is what respond() dispatches on. A handler group merged into
    DYNAMIC_OVERRIDES after OVERRIDES is built is dead code that still reports as
    covered - silent, and the routes answer 200 the whole time."""
    missing = sorted(set(server.DYNAMIC_OVERRIDES) - set(server.OVERRIDES))
    assert not missing, f"handlers registered too late to dispatch: {missing}"
    for group in ("DECORATION_OVERRIDES", "MINI_GAME_OVERRIDES"):
        paths = getattr(server, group, None)
        assert paths, f"{group} vanished - the module no longer registers"
        gone = sorted(p for p in paths if p not in server.OVERRIDES)
        assert not gone, f"{group} not in the dispatch table: {gone}"
    print(f"ok reachable: {len(server.OVERRIDES)} paths dispatch")


def check_no_route_returns_an_unparseable_date():
    """The client hands date-shaped strings to DateTime.Parse, which throws on null
    and on "". That is the `tomorrow` bug: one null froze the lobby into a 1 Hz
    re-login storm. build_model fills them AFTER the overlay, because the nulls came
    from static_overrides.json and from handlers too, not only from unset defaults."""
    r = api_audit.audit()
    bad = [f for f in r["findings"] if f["kind"] == "null-date"]
    assert not bad, "date fields the client cannot parse:\n" + \
        "\n".join(f"  {f['path']}: {f['detail']}" for f in bad)
    print(f"ok dates: {r['answered']} routes, no null/empty date field")


def check_every_declared_field_is_returned():
    r = api_audit.audit()
    bad = [f for f in r["findings"] if f["kind"] in ("absent-field", "unknown-model")]
    assert not bad, "declared but not returned:\n" + \
        "\n".join(f"  {f['path']}: {f['detail']}" for f in bad)
    print("ok fields: every declared field present in every response")


def check_no_route_errors():
    r = api_audit.audit()
    bad = [f for f in r["findings"] if f["kind"] in ("error-response", "no-answer")]
    assert not bad, "routes that did not answer cleanly:\n" + \
        "\n".join(f"  {f['path']}: {f['detail']}" for f in bad)
    print(f"ok answers: {r['answered']}/{r['routes']} routes answered 200/code 200")


def check_weak_mappings_are_triaged():
    """A route the extractor guessed by name similarity may be answered with the
    wrong model entirely - every field then wrong, silently. `/pvp/info` scored 0.58
    and was mapped to PlayerDataResponseModel; the real one is PvPInfoResponseModel.
    Verified routes get pinned in data/route_models_extra.json, which drops the score.
    """
    r = api_audit.audit()
    weak = sorted({f["path"] for f in r["findings"] if f["kind"] == "weak-mapping"})
    assert not weak, ("untriaged low-confidence route->model mappings: " + str(weak) +
                      "\n  check generated/restapi.json, then pin in "
                      "data/route_models_extra.json")
    print("ok mappings: no untriaged guesses")


def check_no_data_is_sent_under_a_name_the_client_does_not_read():
    """The data is there, spelled the way the payload author remembered it, while the
    field the client actually reads sits empty. `/clan/ranking` sent `clanRankings` +
    `myClanRanking` where ClanRankingResponseModel declares `ranking` +
    `playerClanRank`; `/clan/raid` sent a flat {bossId, bossHp, phase} where the model
    wanted a nested `clanRaid` {boss, remainHp, stage}. Every field present, none of
    them readable, and a 200 the whole time."""
    r = api_audit.audit()
    bad = [f for f in r["findings"] if f["kind"] == "renamed-key"]
    assert not bad, "data under an unread name:\n" + \
        "\n".join(f"  {f['path']}: {f['detail']}" for f in bad)
    print("ok names: no payload key shadows the field the client reads")


if __name__ == "__main__":
    check_every_registered_handler_is_reachable()
    check_no_data_is_sent_under_a_name_the_client_does_not_read()
    check_no_route_errors()
    check_every_declared_field_is_returned()
    check_no_route_returns_an_unparseable_date()
    check_weak_mappings_are_triaged()
    print("\nall API contract checks passed")
