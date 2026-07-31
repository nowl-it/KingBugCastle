"""Every route the v171 client can call resolves to its real response model.

A route with no model is answered with `ResponseModel` - the right envelope and none
of the fields the client reads, so a list arrives as null and the feature looks
unimplemented when it is really mistyped. That failure is silent on both ends, which
is why it is asserted here rather than left to be noticed in game.
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import route_coverage

ROOT = Path(__file__).resolve().parent.parent

# Same bar api_audit flags a mapping as a guess at. Below this, map_routes.py paired
# the route with a method by name alone and is as often wrong as right.
WEAK_SCORE = 0.7


def check_no_bare_routes():
    r = route_coverage.report()
    assert not r["bare"], (
        f"{len(r['bare'])} client routes have no response model - add them to "
        f"data/route_models_extra.json:\n  " + "\n  ".join(r["bare"]))
    print(f"ok: all {len(r['client_routes'])} client routes modelled "
          f"({len(r['handled'])} with a handler)")


def check_extra_models_exist():
    """A typo in route_models_extra.json degrades silently: build_model falls back to
    {code, msg} for an unknown model name, which is the very bug this file prevents."""
    models = json.loads((ROOT / "generated" / "models.json").read_text())
    extra = json.loads((ROOT / "data" / "route_models_extra.json").read_text())
    bad = [(p, v["response"]) for p, v in extra.items()
           if not p.startswith("_") and v["response"] not in models]
    assert not bad, f"route_models_extra.json names models that do not exist: {bad}"
    print(f"ok: {len(extra) - 1} hand-mapped routes all name a real model")


def check_extra_does_not_shadow():
    """route_models_extra is for routes map_routes.py missed, and for the ones it
    GUESSED badly.

    A confidently-scored mapping must not be silently overridden here - if that is
    intended it belongs in the ROUTE_MODELS.update() block in server.py with a reason.
    But map_routes.py pairs a route with a method by name similarity and records how
    sure it was, and below ~0.7 it is usually wrong: /pvp/info scored 0.58 into
    PlayerDataResponseModel when FetchPvPInfo returns PvPInfoResponseModel, so every
    field the panel read was the wrong one. Pinning those is the documented fix
    (api_audit's weak-mapping finding demands it), and the pin has to live here
    because this file is what server.py merges last.

    So: overriding a low-scored guess is the point; overriding a confident one is the
    bug. The `_method` key is the receipt that the route was checked against
    generated/restapi.json by hand.
    """
    gen = json.loads((ROOT / "generated" / "route_models.json").read_text())
    extra = json.loads((ROOT / "data" / "route_models_extra.json").read_text())
    bad = []
    for p, v in extra.items():
        if p.startswith("_") or p not in gen:
            continue
        if (gen[p].get("score") or 0) >= WEAK_SCORE:
            bad.append(f"{p} (generated score {gen[p]['score']})")
        elif not v.get("_method"):
            bad.append(f"{p} (overrides a guess with no _method receipt)")
    assert not bad, ("route_models_extra.json shadows confident generated mappings: "
                     + str(bad))
    print("ok: no entry shadows a confident generated mapping")


def check_handlers_are_reachable():
    """A handler keyed on a path the client never calls is dead code - usually a typo
    (this caught /incgame-coupon for /ingame-coupon, and /ranking for /ranking/ranking).
    Two are legitimately unreachable from the string table and are allowed by name."""
    allowed = {
        "/territory",     # alias; the client calls /territory/fetch
        "/x2/xls.cgi",    # CDN patch query, not built from a literal in the table
    }
    r = route_coverage.report()
    stray = [p for p in r["extra_handlers"] if p not in allowed]
    assert not stray, f"handlers for paths the client never calls: {stray}"
    print(f"ok: no stray handlers ({len(allowed)} known aliases allowed)")


if __name__ == "__main__":
    check_no_bare_routes()
    check_extra_models_exist()
    check_extra_does_not_shadow()
    check_handlers_are_reachable()
    print("\nall route coverage checks passed")
