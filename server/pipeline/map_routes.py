#!/usr/bin/env python3
"""Heuristically map REST route paths -> RestAPI method -> response model.

dump.cs method bodies are empty so path<->method isn't directly linked.
Match by tokenising both and scoring overlap. Auth-critical paths are pinned
by hand for correctness. Output generated/route_models.json: path -> {method,response}.
"""
import json, re, pathlib

G = pathlib.Path(__file__).parent.parent / "generated"
routes = [l.strip() for l in (G / "routes.txt").read_text().splitlines() if l.strip().startswith("/")]
restapi = json.load(open(G / "restapi.json"))

def toks(s):
    s = re.sub(r"[{}]", "", s)
    parts = re.split(r"[/_\-]", s)
    out = []
    for p in parts:
        # split camelCase
        for w in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+", p):
            if w:
                out.append(w.lower())
    return out

meth_toks = {m: toks(m) for m in restapi}

def best_method(path):
    pt = set(toks(path))
    best, score = None, 0
    for m, mt in meth_toks.items():
        mts = set(mt)
        if not mts:
            continue
        inter = len(pt & mts)
        if inter == 0:
            continue
        # jaccard-ish, favour full method coverage
        s = inter / len(mts) + inter / max(len(pt), 1) * 0.5
        if s > score:
            best, score = m, s
    return best, round(score, 2)

# hand-pinned auth-critical mappings (verified from RestAPI signatures)
PIN = {
    "/auth/shake-hand": "ShakeHand",
    "/auth/checkPatchVersion": "CheckPatchVersion",
    "/auth/getPatchFolder": "GetPatchFolder",
    "/auth/login": "Login",
    "/auth/register": "Auth",
    "/auth/link": "Auth",
    "/auth/xcdSeed": "GetXigncodeSeed",
    "/auth/xcd": "XigncodeReport",
    "/auth/transfer": "AccountTransfer",
}

out = {}
for r in routes:
    if r in PIN:
        meth = PIN[r]
        out[r] = {"method": meth, "response": restapi.get(meth, {}).get("response", "ResponseModel"), "pinned": True, "score": 1.0}
        continue
    meth, sc = best_method(r)
    resp = restapi.get(meth, {}).get("response", "ResponseModel") if meth else "ResponseModel"
    out[r] = {"method": meth, "response": resp, "score": sc}

(G / "route_models.json").write_text(json.dumps(out, indent=1))
pinned = sum(1 for v in out.values() if v.get("pinned"))
matched = sum(1 for v in out.values() if v["method"] and v["score"] >= 0.6)
print(f"routes: {len(out)}  pinned: {pinned}  confident(>=0.6): {matched}")
print("\n=== auth + bootstrap ===")
for r in sorted(out):
    if r.startswith(("/auth", "/player")) and not r.count("/") > 2:
        print(f"  {r:32} -> {out[r]['method']:28} {out[r]['response']:30} ({out[r]['score']})")
