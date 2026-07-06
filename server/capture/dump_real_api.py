#!/usr/bin/env python3
"""
Register a throwaway guest on the OFFICIAL server, then dump every lobby
endpoint's real (decrypted) response to documentation/captures/real_responses/.
Authoritative reference for cloning response shapes - stop guessing.

Flow mirrors the captured guest login:
  POST /auth/register {type:4,id:"",userName,castleName,...}  -> accessToken
  GET  /auth/xcdSeed
  GET  /auth?id=<loginId>&cookie=&platform=Android
  GET  <lobby endpoints> with accesstoken header
"""
import sys, os, json, random, string, pathlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "api"))
import config  # noqa: E402

config.VERSION = "170.1.00"
config.SESSION.headers.update({
    "version": config.VERSION,
    "User-Agent": f"ProductName/{config.VERSION}.0 CFNetwork/3860.300.31 Darwin/25.2.0",
})

OUT = pathlib.Path(__file__).parent.parent.parent / "documentation" / "captures" / "real_responses"
OUT.mkdir(parents=True, exist_ok=True)

def rand_name(n=8):
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))

# Endpoints to dump (GET). Lobby-load set + the panels we need to match.
GET_ENDPOINTS = [
    "/player", "/player/currencies", "/player/getInventory",
    "/card/all", "/card", "/deck", "/decoration",
    "/pass", "/pass/all-rewards",
    "/pvp/info", "/colosseum", "/colosseum/all-tier-rewards",
    "/clan", "/clan/raid",
    "/artifact/inventory", "/accessory", "/accessory/preset",
    "/treasure", "/rift-weapon", "/rift-weapon/crystal-inventory",
    "/flag/inventory", "/nameTag/inventory",
    "/mission", "/mission/roguelike",
    "/story-mode", "/story-mode/challenge/info",
    "/babel", "/invasion/reward", "/eventcache",
    "/rift-weapon", "/kg-wiki",
]

def save(name, obj):
    p = OUT / (name.strip("/").replace("/", "_") + ".json")
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    keys = list(obj.keys()) if isinstance(obj, dict) else f"<{type(obj).__name__}>"
    print(f"  saved {p.name}: {keys}")

def main():
    uname = rand_name()
    print(f"[register] guest userName={uname}")
    reg = config.post("/auth/register", {
        "type": 4, "id": "", "userName": uname, "castleName": uname,
        "kingPostfix": 1, "castlePostfix": 1, "version": 170100,
    })
    print("  register resp:", reg if isinstance(reg, dict) else str(reg)[:200])
    if not isinstance(reg, dict) or not reg.get("loginId"):
        print("!! register failed - no loginId"); return
    login_id = reg["loginId"]
    save("_register", reg)

    print("[xcdSeed]");
    try: print("  ", config.get("/auth/xcdSeed"))
    except Exception as e: print("  xcdSeed err", e)

    print(f"[auth] id={login_id}")
    try:
        a = config.get("/auth", params={"id": login_id, "version": "170.1.00",
                                        "cookie": "", "platform": "Android"})
        print("  auth resp:", a)
    except Exception as e:
        print("  auth err", e); return
    if not isinstance(a, dict) or not a.get("accessToken"):
        print("!! auth failed - no token"); return
    config.set_auth_token(a["accessToken"])

    print("[dump endpoints]")
    for ep in GET_ENDPOINTS:
        try:
            obj = config.get(ep)
            save(ep, obj)
        except Exception as e:
            print(f"  {ep} ERR {e}")

    print("[territory/fetch]")
    try:
        obj = config.post("/territory/fetch", {})
        save("/territory/fetch", obj)
    except Exception as e:
        print(f"  /territory/fetch ERR {e}")

    print("[game/start theme=1]")
    try:
        obj = config.post("/game/start", {"theme": 1, "currentDeckPreset": 0, "difficulty": 0})
        save("/game/start", obj)
    except Exception as e:
        print(f"  /game/start ERR {e}")

if __name__ == "__main__":
    main()
