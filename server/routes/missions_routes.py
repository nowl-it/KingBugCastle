"""Mission routes: the mission listing and the claim endpoint.

The client's mission tab (/mission) is served from Missions.xml progress, and
claims funnnel through _claim_missions so every claim route shares the same
eligibility check. Server-owned helpers (counters/bump, _claimed_missions,
_grant_mission_reward, _reward_list_data) are reached through srv, which
server.py sets via register().
"""
from common import admin_log, body_int, body_list, now_iso
from config import XML_DIR
from state import save_state
import missions

srv = None      # live server module, injected via register()


def register(app, server_module):
    global srv
    srv = server_module
    srv.MISSION_OVERRIDES = handlers()


def handlers():
    return {
        "/mission": r_mission,
        "/mission/reward-all": r_mission_reward_all,
        "/mission/check": r_mission,
        "/eventcache": r_event_cache,
    }


def r_mission(body, st):
    return {"missions": missions.listing(st, srv.counters(st), srv._claimed_missions(st),
                                         now_iso(0), XML_DIR),
            "missionGoal": st.get("missionGoal", 0),
            "missionKeyStack": st.get("missionKeyStack", 0)}


def _claim_missions(st, ids):
    """Claim every cleared, unclaimed mission in `ids`. Returns the reward list."""
    claimed = srv._claimed_missions(st)
    catalog = missions.load(XML_DIR)
    out = []
    # Coerced here, not in the caller: the id list arrives straight off the request
    # and every claim route funnels through this loop.
    for mid in body_list(ids, int):
        m = catalog.get(mid)
        if m is None or mid in claimed:
            continue
        if missions.progress(m, st, srv.counters(st)) < missions.goal_value(m):
            continue
        for r in missions.rewards_of(m):
            out.append(srv._grant_mission_reward(st, r))
        claimed.add(mid)
        srv.bump(st, "missionClear")
    st["claimedMissions"] = sorted(claimed)
    save_state(st)
    return out


def r_mission_reward_all(body, st):
    """Claim missions. Despite the name this is also the single-mission claim.

    GetMissionRewardAll takes a `missionIdList` (MissionRewardRequestModel), so the
    client sends one id to claim one and several to claim a batch - there is no
    separate per-mission route. An empty list means "everything I can claim"."""
    ids = (body_list(body.get("missionIdList") or body.get("missionIds"), int)
           or ([body_int(body.get("missionId"), 0)] if body.get("missionId") else [])
           or list(missions.load(XML_DIR)))
    rewards = _claim_missions(st, ids)
    admin_log(f"[mission] claim {len(ids)} requested -> {len(rewards)} rewards")
    return {"keyStack": st.get("missionKeyStack", 0), "goal": st.get("missionGoal", 0),
            "passModel": None, "playerTerritoryTycoon": None,
            "rewardListResponseData": srv._reward_list_data(rewards)}


def r_event_cache(body, st):
    return {"events": []}
