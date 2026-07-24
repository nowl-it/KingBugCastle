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
    """route_models_extra is for routes map_routes.py MISSED. An entry that also exists
    in the generated file silently overrides a scored mapping - if that is intended it
    belongs in the ROUTE_MODELS.update() block in server.py with a reason next to it."""
    gen = json.loads((ROOT / "generated" / "route_models.json").read_text())
    extra = json.loads((ROOT / "data" / "route_models_extra.json").read_text())
    dup = [p for p in extra if not p.startswith("_") and p in gen]
    assert not dup, f"route_models_extra.json shadows generated mappings: {dup}"
    print("ok: no entry shadows a generated mapping")


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
