"""Which routes the real client calls, and which of them this server answers.

The old `generated/routes.txt` came from the v170 arm32 dump and is both stale and
incomplete - it misses 91 paths the v171 client actually calls (`/accessory/equip`,
`/game/revive`, every `/ranking/*`, most of `/territory/*`). The authoritative list
is the il2cpp string table of the deployed client, which is where `Web.Get/Post`
reads its uri from.

A path counts as *handled* when it has a real handler: a DYNAMIC_OVERRIDES entry, a
data/static_overrides.json entry, or its own @app.get/@app.post. Everything else
falls through to the catch-all, which answers with `build_model` - shape-valid but
semantically empty, i.e. the feature does nothing.

    python3 route_coverage.py            # summary + the unhandled list
    python3 route_coverage.py --json     # machine-readable
    python3 route_coverage.py --check N  # exit 1 if handled count drops below N
"""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT_JSON = ROOT.parent / "il2cpp" / "v171.0.00" / "script.json"

# The il2cpp string table holds every literal starting with "/", not just routes:
# mono/.NET runtime paths, format fragments, and asset paths all land in it. None of
# these is reachable as an API route, and leaving them in makes the coverage number
# permanently unreachable.
_NOT_ROUTES = re.compile(
    r"^/(usr|etc|proc|lib|bin|sbin|opt|var|Applications|System|Library|dev)(/|$)"
    r"|^/(Date\(|configuration/|resources/?$|settings\.json$)"
    r"|^/PatchResources/"
    r"|\.(png|jpg|jpeg|prefab|asset|cs|so|txt|xml|json|dll)$"
    r"|^/[^a-zA-Z]"           # "/5", "/=", "/>", "/*"
    r"|^/[a-z]+=",            # "/type=", "/enemy="
    re.I)


def client_paths(script_json=SCRIPT_JSON):
    """Every API path the deployed client can call, query strings stripped.

    FastAPI routes on the path alone, so `/territory/upgrade-building?posIndex={0}`
    and `/territory/upgrade-building` are the same endpoint here."""
    strings = json.loads(Path(script_json).read_text())["ScriptString"]
    out = set()
    for s in strings:
        v = s.get("Value")
        if not isinstance(v, str) or not v.startswith("/") or len(v) < 2:
            continue
        p = v.split("?")[0].rstrip("/") or "/"
        if p == "/" or _NOT_ROUTES.search(p) or "//" in p[1:] or " " in p:
            continue
        out.add(p)
    return sorted(out)


def handled_paths(server_py=ROOT / "server.py"):
    """Paths with a real handler, by source: dynamic, static, or a direct route."""
    src = Path(server_py).read_text()
    block = src[src.index("DYNAMIC_OVERRIDES = {"):src.index("# Pure-literal routes")]
    dyn = set(re.findall(r'^\s+"(/[^"]+)":', block, flags=re.M))
    static = set(json.loads((ROOT / "data" / "static_overrides.json").read_text()))
    direct = set(re.findall(r'@app\.(?:get|post)\("(/[^"{]+)"\)', src))
    return {"dynamic": dyn, "static": static, "direct": direct}


def modelled_paths():
    """Paths that at least resolve to their real response model.

    A route with no handler but the right model still answers correctly whenever the
    honest answer is "nothing yet" - an empty ranking board on a one-player server,
    a log history with no games in it. A route with neither gets `ResponseModel`,
    which is missing every field the client reads, and that is the real failure: the
    client sees a null list where it expected an array."""
    rm = json.loads((ROOT / "generated" / "route_models.json").read_text())
    extra = json.loads((ROOT / "data" / "route_models_extra.json").read_text())
    out = {p for p, v in rm.items() if v.get("response") not in (None, "ResponseModel")}
    out |= {p for p, v in extra.items()
            if not p.startswith("_") and v.get("response") != "ResponseModel"}
    # Routes whose real model IS ResponseModel (fire-and-forget acks) are correct as
    # they stand, so count them too - they are not a gap to close.
    out |= {p for p in rm} | {p for p in extra if not p.startswith("_")}
    return out


def report(script_json=SCRIPT_JSON):
    paths = set(client_paths(script_json))
    by_src = handled_paths()
    covered = set().union(*by_src.values())
    modelled = modelled_paths()
    # Admin routes are ours, not the client's - they never appear in the string table.
    return {
        "client_routes": sorted(paths),
        "handled": sorted(paths & covered),
        "modelled_only": sorted((paths & modelled) - covered),
        "bare": sorted(paths - covered - modelled),
        "by_source": {k: len(v & paths) for k, v in by_src.items()},
        "extra_handlers": sorted(covered - paths - {p for p in covered if p.startswith("/admin")}),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", choices=("handled", "modelled_only", "bare"), default="bare")
    ap.add_argument("--check", type=int, metavar="N",
                    help="exit 1 if more than N routes are bare")
    args = ap.parse_args()
    r = report()
    total = len(r["client_routes"])
    n_h, n_m, n_b = len(r["handled"]), len(r["modelled_only"]), len(r["bare"])
    if args.json:
        print(json.dumps(r, indent=1))
    else:
        print(f"client routes:  {total}")
        print(f"  handler:      {n_h:3d} ({100 * n_h // total}%)  {r['by_source']}")
        print(f"  model only:   {n_m:3d}  (correct empty response, no logic)")
        print(f"  bare:         {n_b:3d}  (generic ResponseModel - wrong shape)")
        print(f"\n--- {args.list} ---")
        for p in r[args.list]:
            print("  " + p)
        if r["extra_handlers"]:
            print(f"\nhandlers for paths the v171 client never calls ({len(r['extra_handlers'])}):")
            for p in r["extra_handlers"]:
                print("  " + p)
    if args.check is not None and n_b > args.check:
        print(f"\nFAIL: {n_b} bare routes > {args.check}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
