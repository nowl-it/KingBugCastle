import sys, json
sys.path.insert(0, "server")
import server, shop_routes

st = server.load_state()
body = {"accountId": "test_local"}
resp = shop_routes.r_shop(body, st)
print("availableTimeLimitGachas:", resp.get("availableTimeLimitGachas"))
print("gachaStacks:", resp.get("gachaStacks"))
