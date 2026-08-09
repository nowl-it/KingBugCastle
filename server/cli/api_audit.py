"""Cross-check every route's real response against the model the client declares.

`route_coverage.py` answers "does this path have a handler". This answers the harder
question: **when the handler runs, are the fields the client reads actually filled in?**

`build_model()` always emits every declared field, so nothing is ever *missing* - it
is present at its default. That is precisely where the expensive bugs have lived:

  * a date-ish string left at `null` -> the client does `DateTime.Parse` on it and
    throws (`tomorrow` did this and caused a 1 Hz re-login storm; `expiredAt`,
    `serverTime` and `blockedUntilAt` throw on the login path itself);
  * an object left at `null` -> the client dereferences it;
  * a route mapped to the wrong model by name similarity -> every field is wrong,
    silently (`/player/rename` scored 0.58 and was answered with `GetPlayerInfo`, so
    every rename was discarded).

    python3 api_audit.py             # summary + findings
    python3 api_audit.py --all       # include low-severity notes
    python3 api_audit.py --json
    python3 api_audit.py --route /pvp/info
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# A string field the client is going to hand to DateTime.Parse. Naming is consistent
# across the whole API, which is what makes this checkable at all.
DATEISH = re.compile(r"(At|Date|Dates|Time|Times)$|^(until|expired|created|updated|next|last)",
                     re.I)

# Answering null here is the correct answer, not a gap: the client checks for null and
# branches. Listing them keeps the report free of noise nobody will ever action.
NULL_IS_MEANINGFUL = {
    "clan",                 # HasClan() is literally `clan != null`
    "rewardListResponseData", "artifactResult", "treasureResult", "accessoryResult",
    "supportCompletedModel", "dimensionUnit", "msg",
}


def _boot():
    """Import the server against a throwaway DB holding one real save."""
    import playerdb
    playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "audit.db"
    playerdb.init()
    import server
    server.RATE_LIMIT = 0          # this sweeps every route from one address
    st = server.copy.deepcopy(server.DEFAULT_PLAYER)
    st["uid"] = "audit-1"
    playerdb.save("audit-1", st)
    playerdb.set_active("audit-1")
    return server


_NOISE = re.compile(r"^(my|player|the)|s$|list$|data$|model$|info$", re.I)
# A qualifier makes a DIFFERENT field, not a renamed one: `maxLabor` and `labor` both
# exist and mean different things. Without this the check calls every one of them a
# rename and buries the real findings.
_QUALIFIER = re.compile(r"^(max|min|stored|last|total|current|remain|add|new|old|"
                        r"best|daily|weekly|season|equipped|received|default)")
# The only leftovers that still mean "same field, different spelling". `clanRankings`
# vs `ranking` differ by the domain word; `lastLaborAt` vs `labor` differ by a
# qualifier and a suffix, and those are two different fields.
_DOMAIN = {"clan", "unit", "card", "event", "rogue", "roguelike", "territory",
           "building", "mission", "pass", "shop", "raid", "result"}


def _norm(name):
    """Collapse the naming a payload and a model can disagree on: `clanRankings` and
    `ranking`, `myClanRanking` and `playerClanRank`, both become `clanranking`."""
    prev = None
    while prev != name:
        prev, name = name, _NOISE.sub("", name)
    return name.lower()


def _same_field(a, b):
    """Are these two names the same piece of data under different spellings?

    After _norm strips the plural/list/data/info noise, a genuine rename leaves either
    nothing or a domain word. Anything else - a qualifier, a suffix - is a different
    field that merely shares a substring.
    """
    if a == b:
        return True
    if a not in b and b not in a:
        return False
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return longer.replace(shorter, "", 1) in _DOMAIN


# One path, two behaviours, one declared model. The audit probes with an empty body,
# which takes the branch the model is NOT for - so the mismatch it sees is real and
# harmless. Listed with the reason rather than silently special-cased.
DUAL_PURPOSE = {
    # bare call = FetchInvasionRewardDatas (rewardDatas); with `theme` =
    # ReceiveInvasionReward (rewardListData), which r_invasion_reward does return.
    # Both spellings of the path reach the same handler and split the same way.
    ("/invasion/reward/receive", "rewardDatas"),
    ("/invasion/reward", "rewardDatas"),
}


def _renamed(body, declared):
    """(key we send, field the client reads) where the two are the same thing.

    Only fires when the declared field is still at its default - if the handler filled
    it too, the extra key is a harmless duplicate, not lost data.
    """
    unread = [n for n, s in declared.items()
              if n not in NULL_IS_MEANINGFUL
              and body.get(n) in (None, [], {}, "", 0)]
    out = []
    for extra in sorted(set(body) - set(declared) - {"success"}):
        ne = _norm(extra)
        if len(ne) < 4:
            continue
        if _QUALIFIER.match(_norm(extra)) and any(
                _norm(extra) != _norm(d) and _QUALIFIER.sub("", _norm(extra)) == _norm(d)
                for d in declared):
            continue          # `maxLabor` next to a declared `labor` is its own field
        for target in unread:
            nt = _norm(target)
            if len(nt) >= 4 and _same_field(ne, nt):
                if body.get(target) == body.get(extra):
                    break     # both spellings carry the same value - already fixed
                out.append((extra, target))
                break
    return out


def _fields(server, model_name):
    spec = server.MODELS.get(model_name)
    return {f["name"]: f for f in spec["fields"]} if spec else {}


def audit(only=None):
    server = _boot()
    import route_coverage
    from fastapi.testclient import TestClient

    # TestClient's default peer is the literal "testclient", which is not loopback,
    # so the admin guard would reject everything and every route would look broken.
    client = TestClient(server.app, client=("127.0.0.1", 50000))

    paths = [p for p in sorted(route_coverage.client_paths())
             if not p.startswith(("/patch", "/admin"))]
    if only:
        paths = [p for p in paths if p == only]

    findings, checked = [], 0
    for path in paths:
        info = server.ROUTE_MODELS.get(path, {})
        model = info.get("response", "ResponseModel")
        score = info.get("score")

        try:
            r = client.post(path, content=b"")
            body = server.aes_decrypt(r.content)
            if not isinstance(body, dict):
                body = json.loads(body)
        except Exception as e:                       # noqa: BLE001
            findings.append(dict(path=path, severity="high", kind="no-answer",
                                 detail=f"{type(e).__name__}: {e}"))
            continue
        checked += 1

        if r.status_code != 200 or body.get("code") != 200:
            findings.append(dict(path=path, severity="high", kind="error-response",
                                 detail=f"HTTP {r.status_code} {str(body)[:70]}"))
            continue

        declared = _fields(server, model)
        if model != "ResponseModel" and not declared:
            findings.append(dict(path=path, severity="medium", kind="unknown-model",
                                 detail=f"{model} is not in models.json"))

        dates, objs = [], []
        for name, spec in declared.items():
            if name in NULL_IS_MEANINGFUL:
                continue
            got = body.get(name, "<absent>")
            if got == "<absent>":
                findings.append(dict(path=path, severity="high", kind="absent-field",
                                     detail=f"{model}.{name} declared but not returned"))
            elif spec["jtype"] == "string" and DATEISH.search(name) and not got:
                dates.append(name)
            elif spec["jtype"] == "object" and got is None:
                objs.append(name)

        if dates:
            findings.append(dict(
                path=path, severity="high", kind="null-date",
                detail=f"{model}: {', '.join(sorted(dates))} - DateTime.Parse throws on null"))
        if objs:
            findings.append(dict(
                path=path, severity="low", kind="null-object",
                detail=f"{model}: {', '.join(sorted(objs))}"))

        # The expensive shape of undeclared key: the data IS there, under a name the
        # client does not read, while the field it does read sits at its default.
        # `/clan/ranking` sent `clanRankings` + `myClanRanking` while
        # ClanRankingResponseModel declares `ranking` + `playerClanRank`, so the board
        # read an empty list from a key nobody had filled.
        #
        # Flagging every undeclared key instead produces ~120 findings and no signal:
        # most routes carry deliberate extras, and a merely-unread key costs nothing.
        # The pairing is what makes it actionable.
        for extra, target in _renamed(body, declared):
            if (path, extra) in DUAL_PURPOSE:
                continue
            findings.append(dict(
                path=path, severity="medium", kind="renamed-key",
                detail=f"sends `{extra}` but {model} reads `{target}`, "
                       f"which is still at its default"))

        # A mapping the extractor guessed. The path is right (it comes from the client's
        # own string table); the MODEL may not be, and then every field above is wrong.
        if score is not None and score < 0.7 and path in server.OVERRIDES:
            findings.append(dict(path=path, severity="medium", kind="weak-mapping",
                                 detail=f"score {score} -> {model} (verify against dump.cs)"))

    return {"routes": len(paths), "answered": checked, "findings": findings}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true", help="include low-severity findings")
    ap.add_argument("--route", help="audit a single path")
    args = ap.parse_args()

    r = audit(only=args.route)
    if args.json:
        print(json.dumps(r, indent=1))
        return 0

    order = {"high": 0, "medium": 1, "low": 2}
    shown = [f for f in r["findings"] if args.all or f["severity"] != "low"]
    shown.sort(key=lambda f: (order[f["severity"]], f["kind"], f["path"]))

    print(f"routes audited: {r['answered']}/{r['routes']}")
    counts = {}
    for f in r["findings"]:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    print(f"findings: {counts or 'none'}\n")

    for f in shown:
        print(f"[{f['severity']:6}] {f['kind']:14} {f['path']}")
        print(f"{'':9}{f['detail']}")
    if not args.all:
        low = sum(1 for f in r["findings"] if f["severity"] == "low")
        if low:
            print(f"\n({low} low-severity finding(s) hidden - use --all)")
    return 1 if any(f["severity"] == "high" for f in r["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
