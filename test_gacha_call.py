import sys, json
sys.path.insert(0, "server")
import server, shop_routes, gacha
st = server.load_state()
if "gachaKeys" not in st: st["gachaKeys"] = {}
st["gachaKeys"]["390"] = 100
body = {"accountId": "test_public", "gachaId": 7000}
resp = shop_routes.r_shop(body, st)
print("r_shop gachaResult keys:", resp.keys())
print("r_shop raw:", resp)
