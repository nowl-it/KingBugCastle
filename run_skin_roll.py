import sys, json
sys.path.insert(0, "server")
import server, shop_routes
st = server.load_state()
if "gachaKeys" not in st: st["gachaKeys"] = {}
st["gachaKeys"]["390"] = 100
body = {"accountId": "test_public", "gachaId": 7000}
resp = shop_routes.r_shop(body, st)
print(json.dumps(resp.get("gachaResult", []), indent=2))
