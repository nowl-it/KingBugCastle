"""Inbox claims on the overcome track (dimension + incarnation) and the live-refresh
payload, the two bugs reported 2026-10-26:

  * A claimed item only appeared in the inventory after a game restart - the client
    does NOT re-fetch after /post/receive, so the response must carry
    treasureResult.inventories (HandleTreasureResult rebuilds the cache from it).
  * A duplicate Yhoundeh (10820, the only IsIncarnationUnit hero) fell to the soul
    path and never raised overcome - _grant_reward only knew IsDimensionUnit, the
    claim wire emitted no IncarnationOvercome entry, and card_to_dict never
    serialized incarnationUnit, so even a restart could not recover the stars.

Client semantics that pin the wire format (v174.1.00 disasm, HandleRewardResponseData
0x319F1E4): the Incarnation/DimensionOvercome case assigns card.overcome = count
OUTRIGHT (not additive) and only dispatches on the type string matching the unit's
own flag; the Card case AddCards with overcome 0, hence a first grant needs the
companion overcome entry.
"""
import sys, tempfile
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import dimension
from tests.seed import one_account
one_account()          # multiplayer mode does not mint a save; give load_state() one
import server
import inbox                       # the SAME module instance server.py registered
                                   # (routes/ is on sys.path; "routes.inbox" would be a
                                   # second copy whose srv stays None)

INC = 10820       # Yhoundeh, the only IsIncarnationUnit hero
DIM = 10790       # Ophelia, a dimension hero
PLAIN = 10260     # ChungAh, an ordinary one


def _mail(rt, rid, amt):
    """A fresh state with exactly one unclaimed mail carrying (rt, rid, amt)."""
    st = server.load_state()
    st["cards"] = {}
    st["inventory"] = {"itemIds": [], "counts": []}
    st["posts"] = [{"id": 1, "type": "Normal", "title": "t", "text": "x",
                    "rewardType": rt, "rewardId": rid, "rewardAmount": amt,
                    "untilAt": "2999-01-01T00:00:00Z"}]
    server.save_state(st)
    return st


def _wire(rewards):
    """What the client actually matches on: _wire_rewards already passes an
    Incarnation/DimensionOvercome type through unchanged."""
    return server._wire_rewards(rewards)


def check_incarnation_first_grant_starts_at_one_star():
    st = _mail("Unit", INC, 1)
    got, rewards = inbox.claim(st, 1)
    c = st["cards"][str(INC)]
    assert c["overcome"] == 1, f"first incarnation grant left overcome {c['overcome']}"
    assert c.get("soul", 0) == 0, "an incarnation hero was paid out as souls"
    wire = _wire(rewards)
    assert [r["type"] for r in wire] == ["Card", "IncarnationOvercome"], wire
    assert wire[1]["count"] == 1 and wire[1]["id"] == INC, wire
    print("ok incarnation: first grant = Card + IncarnationOvercome(1), card starts 1-star")


def check_incarnation_duplicate_raises_to_five():
    """The user's repro: mail 1 Yhoundeh, claim; mail 4 more, claim -> overcome 5."""
    st = _mail("Unit", INC, 1)
    inbox.claim(st, 1)
    st = server.load_state()
    st["posts"] = [{"id": 2, "type": "Normal", "title": "t", "text": "x",
                    "rewardType": "Unit", "rewardId": INC, "rewardAmount": 4,
                    "untilAt": "2999-01-01T00:00:00Z"}]
    server.save_state(st)
    got, rewards = inbox.claim(st, 2)
    assert st["cards"][str(INC)]["overcome"] == 5, \
        f"1 + 4 Yhoundeh must be overcome 5, got {st['cards'][str(INC)]['overcome']}"
    wire = _wire(rewards)
    assert len(wire) == 1, f"a duplicate must send one absolute entry, got {wire}"
    assert wire[0]["type"] == "IncarnationOvercome" and wire[0]["count"] == 5, wire
    print("ok incarnation: duplicate claim -> overcome 5, one IncarnationOvercome(5)")


def check_dimension_duplicate_uses_dimensionovercome_wire():
    st = _mail("Unit", DIM, 1)
    inbox.claim(st, 1)
    st = server.load_state()
    st["posts"] = [{"id": 2, "type": "Normal", "title": "t", "text": "x",
                    "rewardType": "Unit", "rewardId": DIM, "rewardAmount": 2,
                    "untilAt": "2999-01-01T00:00:00Z"}]
    server.save_state(st)
    got, rewards = inbox.claim(st, 2)
    assert st["cards"][str(DIM)]["overcome"] == 3
    wire = _wire(rewards)
    assert wire == [{"type": "DimensionOvercome", "id": DIM, "count": 3}], wire
    print("ok dimension: duplicate claim -> DimensionOvercome(3), track unchanged")


def check_ordinary_duplicate_still_pays_souls():
    st = _mail("Unit", PLAIN, 2)
    got, rewards = inbox.claim(st, 1)
    assert st["cards"][str(PLAIN)]["soul"] == 0, "a first grant is the card, not souls"
    st = server.load_state()
    st["posts"] = [{"id": 2, "type": "Normal", "title": "t", "text": "x",
                    "rewardType": "Unit", "rewardId": PLAIN, "rewardAmount": 1,
                    "untilAt": "2999-01-01T00:00:00Z"}]
    server.save_state(st)
    got, rewards = inbox.claim(st, 2)
    c = st["cards"][str(PLAIN)]
    assert c.get("overcome", 0) == 0, "an ordinary hero must not enter the overcome track"
    assert c["soul"] == 150, f"soul math broke: {c['soul']}"
    wire = _wire(rewards)
    assert wire == [{"type": "Card", "id": PLAIN, "count": 1}], wire
    print("ok ordinary: duplicate stays on the soul path, wire keeps the Card entry")


def check_card_payload_serializes_incarnation_overcome():
    st = _mail("Unit", INC, 4)
    inbox.claim(st, 1)                       # new card: starts at 1 star by design
    assert st["cards"][str(INC)]["overcome"] == 1, "a fresh overcome card must start at 1"
    st = server.load_state()
    st["posts"] = [{"id": 2, "type": "Normal", "title": "t", "text": "x",
                    "rewardType": "Unit", "rewardId": INC, "rewardAmount": 3,
                    "untilAt": "2999-01-01T00:00:00Z"}]
    server.save_state(st)
    inbox.claim(st, 2)                       # dup +3 -> overcome 4
    st = server.load_state()
    server._grant_reward(st, "Unit", PLAIN, 1)   # an ordinary hero for the None contrast
    server.save_state(st)
    cards = {c["unitId"]: c for c in server.cards_list(server.load_state())}
    inc = cards[INC]
    assert inc["incarnationUnit"] is not None, \
        "ApplySpecialUnitData reads incarnation overcome only from this submodel"
    assert inc["incarnationUnit"]["overcome"] == 4, inc["incarnationUnit"]
    assert inc["dimensionUnit"] is None, "flags are exclusive; an incarnation hero has no dim model"
    plain = cards[PLAIN]
    assert plain["incarnationUnit"] is None and plain["dimensionUnit"] is None, \
        "an ordinary hero must carry neither special model"
    print("ok card_to_dict: incarnationUnit carries the persisted overcome")


def check_claim_payload_refreshes_inventory_live():
    """Bug A: the reward list alone leaves the client cache stale until restart."""
    st = _mail("Item", dimension.REMNANT, 3)
    got, rewards = inbox.claim(st, 1)
    payload_rewards = server._wire_rewards(rewards)
    assert payload_rewards == [{"type": "InventoryItem", "id": dimension.REMNANT, "count": 3}], payload_rewards
    treasure_result = {
        "treasures": server.get_st_treasures(st),
        "deletedTreasures": [],
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "inventories": server._inventory_models(st),
        "addedExpItems": 0,
    }
    row = next(i for i in treasure_result["inventories"] if i["id"] == dimension.REMNANT)
    assert row["count"] == 3, f"claimed item not reflected in inventories: {row}"
    print("ok inventory: claim grants the item and the response can rebuild the cache")


if __name__ == "__main__":
    check_incarnation_first_grant_starts_at_one_star()
    check_incarnation_duplicate_raises_to_five()
    check_dimension_duplicate_uses_dimensionovercome_wire()
    check_ordinary_duplicate_still_pays_souls()
    check_card_payload_serializes_incarnation_overcome()
    check_claim_payload_refreshes_inventory_live()
    print("\nall inbox-overcome checks passed")
