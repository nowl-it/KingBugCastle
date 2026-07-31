"""Every route, against bodies the handler did not expect.

`test_all_routes_respond` posts an empty body. That only catches handlers that
read a key which is absent. It misses the larger family: a key that is present
with the wrong shape - null, a string, a negative index, a list, an object. The
client's serialiser sends null for an unset field, and `body.get("x", 0)` returns
None for that, not 0.

Three real defects came out of this, all of them 500s in production shape:

  * `int(body.get("count") or 1)` raised TypeError on "2".
  * `while len(presets) <= preset: presets.append(...)` grew a list to whatever
    index arrived, so one request naming preset 1000000000 allocated until the
    server died. Unauthenticated, one request. Every such loop is now clamped.
  * A negative index passed `preset < len(presets)` and quietly wrote to the wrong
    end of the list, which is worse than crashing.

Body fields are read through `body_int` / `body_list` / `body_str` rather than
guarded per handler, so this test is what keeps the next raw `int(body.get(...))`
from getting in.
"""
import os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# This fires several thousand requests from one address, which is exactly what the
# per-IP limit exists to stop - every route past the first 600 came back 429 and the
# check read it as a crash. Off for the sweep; test_public_hardening covers the limit
# itself. Set before importing server: RATE_LIMIT is read once at import.
os.environ["KGC_RATE_LIMIT"] = "0"

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import route_coverage
from tests.seed import one_account
_SEEDED = one_account()   # multiplayer needs a session; load_state() has no fallback
import server
from fastapi.testclient import TestClient

# The requests below must arrive as the SAME player the checks read back with
# load_state(). Without the header the middleware resolves no identity and
# multiplayer mode hands the request a throwaway save, so every write lands
# somewhere the assertions never look.
_TOKEN = "test-session-token"
playerdb.bind_session(_TOKEN, _SEEDED["uid"])
client = TestClient(server.app, client=("127.0.0.1", 50000),
                    headers={"accesstoken": _TOKEN})

# Every field name any handler reads. One body sets them all at once, which is
# blunt but means a new handler is covered the moment its field name is added.
KEYS = [
    "unitId", "id", "itemId", "itemID", "artifactId", "treasureId", "accessoryId",
    "skinId", "shopItemId", "missionId", "missionIdList", "missionIds", "themeId",
    "stage", "theme", "index", "preset", "presetIdx", "idx", "count", "level",
    "potential", "potentials", "deck", "decks", "levels", "firstComerIndex",
    "riftWeaponId", "eventId", "seqId", "role", "day", "floor", "round", "win",
    "message", "name", "code", "selectIdx", "targetId", "player", "wishList",
    "customPickups", "uid", "gameId", "keywords", "intro", "notice", "tag",
    "markId", "language", "joinType", "buildingId", "posIndex", "targetPosIndex",
    "huntingId", "currencyIndex", "advisorId", "season", "flagId", "nameTagId",
    "buyAmount", "difficulty", "damage", "type", "targetUnit", "saveVersion",
    "profileIconId", "unitIds", "units", "rewardIdx", "deckPreset", "pass",
    "rogueLikeThemeId", "ownCardSnapshot", "state",
]

SHAPES = {
    "empty": {},
    "unknown-id": {k: 999999 for k in KEYS},
    "huge": {k: 10 ** 9 for k in KEYS},          # the allocation bomb
    "string-ids": {k: "1" for k in KEYS},
    "garbage-str": {k: "xyz" for k in KEYS},
    "negative": {k: -1 for k in KEYS},           # the silent wrong-end write
    "null": {k: None for k in KEYS},             # what get(k, default) misses
    "wrong-type": {k: [] for k in KEYS},
    "dict-type": {k: {"a": 1} for k in KEYS},
    "bool-type": {k: True for k in KEYS},
    "float-type": {k: 1.9 for k in KEYS},
    "nested-list": {k: [{"a": 1}, None, "x"] for k in KEYS},
}


def _paths():
    return [p for p in sorted(route_coverage.client_paths())
            if not p.startswith("/patch") and not p.startswith("/admin")]


def check_no_route_crashes_on_a_malformed_body():
    paths = _paths()
    bad = []
    for shape, body in SHAPES.items():
        for p in paths:
            try:
                r = client.post(p, content=server.aes_encrypt(body))
                if r.status_code != 200:
                    bad.append(f"{shape} {p}: HTTP {r.status_code}")
            except Exception as e:                # noqa: BLE001 - collect, don't stop
                bad.append(f"{shape} {p}: {e!r}"[:140])
    assert not bad, f"{len(bad)} crashes:\n" + "\n".join("  " + b for b in bad[:25])
    print(f"ok: {len(paths)} routes x {len(SHAPES)} body shapes = "
          f"{len(paths) * len(SHAPES)} calls, no crash")


def check_a_client_index_cannot_allocate():
    """The index is client-supplied and unauthenticated. Before the clamp, one
    request grew a list to a billion entries."""
    for path, key in (("/player/building/save", "preset"),
                      ("/deck/set", "presetIdx"),
                      ("/deck/setPotential", "idx"),
                      ("/clan/raid/deck", "index")):
        r = client.post(path, content=server.aes_encrypt({key: 10 ** 9, "deck": [1]}))
        assert r.status_code == 200, f"{path} died on {key}=1e9"
    st = server.load_state()
    assert len(st.get("decks", [])) <= server.DECK_PRESETS, \
        f"deck presets grew to {len(st.get('decks', []))}"
    assert len(server._get_building_data(st)) <= server.BUILDING_PRESETS, \
        "building presets grew past the cap"
    print(f"ok: index clamped to {server.DECK_PRESETS} decks / "
          f"{server.BUILDING_PRESETS} building presets")


def check_a_negative_index_does_not_write_to_the_end():
    """`preset < len(presets)` passes for -1 and Python indexes from the end, so a
    negative preset used to overwrite the last one instead of the first."""
    st = server.load_state()
    st["decks"] = [{"deck": [i] * server.DECK_SLOTS,
                    "potential": [0] * server.DECK_SLOTS, "firstComerIndex": 0}
                   for i in range(server.DECK_PRESETS)]
    server.save_state(st)
    last = server.load_state()["decks"][-1]["deck"][:]
    client.post("/deck/set", content=server.aes_encrypt(
        {"presetIdx": -1, "deck": [9999] * server.DECK_SLOTS}))
    decks = server.load_state()["decks"]
    assert decks[-1]["deck"] == last, "a negative preset overwrote the last one"
    assert decks[0]["deck"][0] == 9999, "the write did not land on preset 0"
    print("ok: preset -1 clamps to 0, the last preset is untouched")


def check_body_helpers_do_what_they_claim():
    bi, bl, bs = server.body_int, server.body_list, server.body_str
    assert bi(None, 5) == 5 and bi("xyz", 5) == 5 and bi({}, 5) == 5
    assert bi("7") == 7 and bi(1.9) == 1 and bi(True) == 1
    assert bi(-3, lo=0) == 0 and bi(10 ** 9, hi=9) == 9
    assert bl(None) == [] and bl(3) == [] and bl({"a": 1}) == []
    assert bl(["1", "x", 2], int) == [1, 2], "the bad element was not dropped"
    assert bs(None) == "" and bs(5) == "" and bs("  hi ") == "hi"
    print("ok: body_int / body_list / body_str coerce and bound")


if __name__ == "__main__":
    check_body_helpers_do_what_they_claim()
    check_a_client_index_cannot_allocate()
    check_a_negative_index_does_not_write_to_the_end()
    check_no_route_crashes_on_a_malformed_body()
    print("\nall malformed-body checks passed")
