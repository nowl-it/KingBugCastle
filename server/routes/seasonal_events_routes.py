"""Seasonal routes: the season pass, cumulative-spend events, cloud-run
service discovery. All four render from config, not state, so they are thin.
"""
from common import body_int, now_iso
from config import RCFG
from state import save_state

srv = None      # live server module, injected via register()


def register(app, server_module):
    global srv
    srv = server_module
    srv.SEASONAL_EVENTS_OVERRIDES = handlers()


def handlers():
    return {
        "/pass": r_pass,
        "/pass/reward": r_pass,
        "/pass/all-rewards": r_pass,
        "/pass/bonusReward": r_pass,
        "/pass/buyLevel": r_pass,
        "/pass/reroll-mission": r_pass_reroll_mission,
        "/shop-event/cumulative-purchase": r_cumulative_purchase,
        "/shop-event/cumulative-purchase/claim": r_cumulative_purchase_claim,
        "/api/cloud-run/services": r_cloud_run_services,
        "/api/cloud-run/default-ranking": r_cloud_run_services,
    }


def r_pass(body, st):
    c = RCFG["pass"]
    out = {"seasonStartAtDate": now_iso(c["seasonStartDayOffset"]),
           "seasonUntilAtDate": now_iso(c["seasonUntilDayOffset"]),
           "nextSeasonStartAtDate": now_iso(c["nextSeasonStartDayOffset"])}
    out.update(c["fixed"])
    return out


def r_pass_reroll_mission(body, st):
    """Reroll one pass mission for gold. The client redraws the row from
    newMissionData, so handing back the same mission is a visible no-op - which is
    the honest answer when there is no second mission to swap in."""
    price = RCFG.get("pass", {}).get("rerollPrice", 0)
    count = int(st.get("passRerollCount", 0))
    if price and st.get("gold", 0) < price:
        return {"newMissionData": None, "rerollCount": count,
                "playerGold": st.get("gold", 0)}
    st["gold"] = st.get("gold", 0) - price
    st["passRerollCount"] = count + 1
    save_state(st)
    return {"newMissionData": None, "rerollCount": st["passRerollCount"],
            "playerGold": st.get("gold", 0)}


def r_cumulative_purchase(body, st):
    """Cumulative-spend events. Every window in ShopEventInfos.xml has closed, so
    there is no event to have spent into - `states` is empty, not absent."""
    return {"states": st.get("shopEventStates", {})}


def r_cumulative_purchase_claim(body, st):
    return {"eventId": body_int(body.get("eventId"), 0), "state": 0,
            "rewardList": srv._reward_list_data([])}


def r_cloud_run_services(body, st):
    """Infrastructure discovery. The real backend answers with the regional service
    endpoints it wants the client to use; return local endpoints so client configures correctly."""
    endpoint_data = {
        "name": "default-ranking",
        "url": "http://127.0.0.1",
        "cachedInfo": {"useSideCar": False, "useReplicaDB": False}
    }
    return {"services": [endpoint_data], "ranking": [], "serverList": [endpoint_data]}