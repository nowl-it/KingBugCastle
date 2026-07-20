"""Dashboard API checks. Runs against a throwaway DB.

`playerdb.DB_PATH` is redirected BEFORE dashboard is imported - the module resolves the
store at import time, so importing first would run every one of these mutations against
the live save.

Covered: the admin guard on every route (including the websocket, which HTTP middleware
never sees), the CRUD paths, and the two invariants that are easy to break by accident -
the parallel inventory arrays staying the same length, and refusing to delete the last
remaining save.
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import playerdb

_TMP = tempfile.TemporaryDirectory()
playerdb.DB_PATH = pathlib.Path(_TMP.name) / "players.db"
playerdb.init()          # schema follows DB_PATH, so re-run it against the temp file

import dashboard                                    # noqa: E402  (after DB_PATH swap)
from fastapi.testclient import TestClient           # noqa: E402

# TestClient's default peer is the literal string "testclient", which is NOT loopback -
# without this the loopback guard would reject everything and the suite would "pass" by
# never reaching any real code.
client = TestClient(dashboard.app, client=("127.0.0.1", 55001))

SEED = {
    "uid": "t-1", "name": "Tester", "castleName": "Keep", "level": 5, "exp": 0,
    "gold": 100, "cash": 10, "heart": 3,
    "cards": {"10000": {"unitId": 10000, "level": 30, "soul": 999, "potentialTier": 1}},
    "inventory": {"itemIds": [2550, 4100], "counts": [5, 7]},
    "accessories": [{
        "id": 1, "type": 3, "rarity": 3, "level": 20, "synergy": 1, "unitId": 0,
        "data": {"mainStat": "BaseDefPen"},
        "subStats": ["BaseDefPen", "HpPer"], "subStatScores": [26.0, 4.0],
    }],
    "posts": [],
}


def seed(uid="t-1", **over):
    st = json.loads(json.dumps(SEED))
    st["uid"] = uid
    st.update(over)
    playerdb.save(uid, st)
    return st


def test_guard():
    """Non-loopback peers must be refused while no token is configured."""
    assert dashboard.ADMIN_TOKEN is None, "test assumes no token in env"
    outsider = TestClient(dashboard.app, client=("10.0.0.9", 55002))
    for path in ("/api/status", "/api/players", "/api/player/t-1"):
        r = outsider.get(path)
        assert r.status_code == 403, f"{path} reachable from a remote peer: {r.status_code}"
    # The websocket guard is separate code - a middleware-only check leaves it open.
    try:
        with outsider.websocket_connect("/ws"):
            raise AssertionError("/ws accepted a non-loopback peer")
    except AssertionError:
        raise
    except Exception:
        pass
    print("ok guard: http + ws both refuse non-loopback")


def test_crud():
    seed()
    assert client.get("/api/status").json()["players"] >= 1
    summaries = client.get("/api/players").json()
    assert any(p["id"] == "t-1" for p in summaries), summaries

    r = client.patch("/api/player/t-1", json={"gold": 999, "name": "Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["gold"] == 999

    r = client.patch("/api/player/t-1", json={"uid": "hijack"})
    assert r.status_code == 400, "uid must not be editable through the field patcher"
    r = client.patch("/api/player/t-1", json={"gold": "many"})
    assert r.status_code == 400, "non-integer currency must be rejected, not coerced"

    # Raw editor: the uid is forced back to the row key, otherwise the save and its
    # key disagree and the player edits a ghost.
    raw = client.get("/api/player/t-1/raw").json()
    raw["uid"] = "somethingelse"
    raw["castleName"] = "Rewritten"
    assert client.put("/api/player/t-1/raw", json=raw).status_code == 200
    assert playerdb.load("t-1")["uid"] == "t-1"
    assert playerdb.load("t-1")["castleName"] == "Rewritten"
    assert client.put("/api/player/t-1/raw", json={}).status_code == 400
    print("ok crud: patch validation + raw-editor uid pinning")


def test_delete_guard():
    for pid in list(p["id"] for p in client.get("/api/players").json()):
        if pid != "t-1":
            playerdb.delete(pid)
    assert playerdb.count() == 1
    r = client.delete("/api/players/t-1")
    assert r.status_code == 400, "deleted the only save - that is unrecoverable"
    seed("t-2")
    assert client.delete("/api/players/t-2").status_code == 200
    assert playerdb.load("t-2") is None
    print("ok delete: refuses the last save, deletes otherwise")


def test_heroes_and_inventory():
    seed()
    heroes = client.get("/api/player/t-1/heroes").json()
    assert len(heroes["owned"]) == 1 and heroes["owned"][0]["unitId"] == 10000
    assert heroes["owned"][0]["name"] and not heroes["owned"][0]["name"].startswith("Unit "), \
        "hero name did not resolve through master data"
    assert heroes["missing"], "every other hero should show as missing"

    grant_id = heroes["missing"][0]["unitId"]
    assert client.post(f"/api/player/t-1/heroes/{grant_id}").status_code == 200
    assert client.post(f"/api/player/t-1/heroes/{grant_id}").status_code == 409
    assert client.post("/api/player/t-1/heroes/999999").status_code == 404
    assert client.patch(f"/api/player/t-1/heroes/{grant_id}", json={"level": 25}).status_code == 200
    assert playerdb.load("t-1")["cards"][str(grant_id)]["level"] == 25
    assert client.delete(f"/api/player/t-1/heroes/{grant_id}").status_code == 200

    added = client.post("/api/player/t-1/heroes-grant-all", json={}).json()
    assert added["total"] == len(dashboard.gamedata.HEROES)

    # The save stores itemIds and counts as two parallel arrays; a write that updates
    # one and not the other desyncs them permanently.
    assert client.post("/api/player/t-1/inventory", json={"id": 2550, "count": 42}).status_code == 200
    inv = client.get("/api/player/t-1/inventory").json()
    assert next(i for i in inv if i["id"] == 2550)["count"] == 42
    client.post("/api/player/t-1/inventory", json={"id": 4100, "count": 0})
    st = playerdb.load("t-1")["inventory"]
    assert len(st["itemIds"]) == len(st["counts"]), "inventory arrays desynced"
    assert 4100 not in st["itemIds"], "count=0 should remove the row"
    assert client.post("/api/player/t-1/inventory", json={"id": 1, "count": -5}).status_code == 400
    print("ok heroes+inventory: grant/edit/remove, parallel arrays stay in sync")


def test_accessories():
    seed()
    body = client.get("/api/player/t-1/accessories").json()
    acc = body["accessories"][0]
    # The whole point of the accessory view: keys resolved through Strings, and the
    # grade computed the way the client computes it.
    assert acc["mainStatLabel"] == "Menace", acc["mainStatLabel"]
    assert acc["synergyName"] == "Fear", acc["synergyName"]
    assert [s["grade"] for s in acc["subStats"]] == ["SS", "D"], acc["subStats"]
    assert acc["subStats"][0]["label"] == "Menace"
    assert acc["scoreTotal"] == 30.0
    print("ok accessories: stat labels + grades resolved")


def test_mail():
    seed()
    r = client.post("/api/player/t-1/mail", json={"title": "@raw: Hi", "text": "  body ", "days": 7})
    assert r.status_code == 200
    post = r.json()["posts"][-1]
    assert post["title"] == "Hi", "a user-typed @raw: must be stripped, server.py re-adds it"
    assert post["text"] == "body"
    assert client.post("/api/player/t-1/mail", json={"title": "", "text": ""}).status_code == 400

    seed("t-3")
    sent = client.post("/api/mail/broadcast", json={"title": "All", "text": "hi"}).json()
    assert set(sent["sent"]) >= {"t-1", "t-3"}, sent
    assert playerdb.load("t-3")["posts"][-1]["title"] == "All"

    pid = post["id"]
    left = client.delete(f"/api/player/t-1/mail/{pid}").json()["posts"]
    assert all(p["id"] != pid for p in left)
    print("ok mail: @raw stripping, broadcast, delete")


def test_server_proxy_when_down():
    """The game server being down is a normal state for this UI, not a 500."""
    dashboard.SERVER_URL = "http://127.0.0.1:9"      # reserved discard port
    r = client.get("/api/server/system")
    assert r.status_code == 200 and r.json()["ok"] is False, r.text
    assert client.get("/api/server/nope").status_code == 404
    print("ok proxy: degrades to ok:false instead of erroring")


if __name__ == "__main__":
    test_guard()
    test_crud()
    test_delete_guard()
    test_heroes_and_inventory()
    test_accessories()
    test_mail()
    test_server_proxy_when_down()
    print("\nall dashboard API checks passed")
