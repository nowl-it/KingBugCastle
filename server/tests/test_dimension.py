"""Dimension heroes: sync levels, overcome, and the card's dimensionUnit sub-model.

CardResponseModel.dimensionUnit was never filled, so it arrived null for every hero
and both /dimension-unit routes answered an empty model. The failures worth guarding
are the ones that cost the player something:

  * charging for a level that is already at the cap;
  * granting a level or an overcome step without taking the currency;
  * handing an ordinary hero a dimension model, which puts a sync panel on a hero
    that has no dimension form.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import dimension
import server

DIM = 10790      # Ophelia, a dimension hero
PLAIN = 10260    # ChungAh, an ordinary one


def _fresh(remnants=0, tickets=0):
    st = server.load_state()
    st["inventory"] = {"itemIds": [], "counts": []}
    for uid in (DIM, PLAIN):
        st.setdefault("cards", {})[str(uid)] = {
            "unitId": uid, "level": 1, "exp": 0, "potentialTier": 0, "skins": [],
            "favoriteSkinIds": [], "currentSkin": 0, "randomSkinApply": False, "soul": 0}
    if remnants:
        server._grant_reward(st, "Item", dimension.REMNANT, remnants)
    if tickets:
        server._grant_reward(st, "Item", dimension.TICKET, tickets)
    st["cash"] = 1000
    server.save_state(st)
    return st


def check_only_dimension_heroes_get_a_model():
    st = _fresh()
    assert server.r_card({"unitId": DIM}, st)["dimensionUnit"] is not None
    assert server.r_card({"unitId": PLAIN}, st)["dimensionUnit"] is None, \
        "an ordinary hero was given a sync panel"
    flagged = dimension.dimension_unit_ids(server.XML_DIR)
    for c in server.cards_list(server.load_state()):
        assert (c["dimensionUnit"] is not None) == (c["unitId"] in flagged), \
            f"unit {c['unitId']} disagrees with its IsDimensionUnit flag"
    print(f"ok model: {len(flagged)} flagged units, only those carry a dimensionUnit")


def check_upgrade_charges_exactly_the_listed_cost():
    st = _fresh(remnants=dimension.next_cost(0, server.XML_DIR) + 7)
    before = server.r_card({"unitId": DIM}, st)["dimensionUnit"]
    cost = before["dimensionNextLevelCost"]
    assert cost == dimension.next_cost(0, server.XML_DIR)

    after = server.r_dimension_upgrade({"unitId": DIM}, server.load_state())["dimensionUnit"]
    assert after["dimensionLevel"] == 1, "the sync level did not advance"
    left = server._item_count(server.load_state(), dimension.REMNANT)
    assert left == 7, f"{cost} remnants should have been spent, {left} left over"
    assert after["dimensionNextLevelCost"] == dimension.next_cost(1, server.XML_DIR), \
        "the next cost still quotes the level just paid for"
    print(f"ok upgrade: level 0 -> 1 for {cost} remnants, next quotes "
          f"{after['dimensionNextLevelCost']}")


def check_upgrade_refused_without_remnants():
    st = _fresh(remnants=dimension.next_cost(0, server.XML_DIR) - 1)
    out = server.r_dimension_upgrade({"unitId": DIM}, st)["dimensionUnit"]
    assert out["dimensionLevel"] == 0, "an unaffordable sync level was granted"
    assert server._item_count(server.load_state(), dimension.REMNANT) == \
        dimension.next_cost(0, server.XML_DIR) - 1, "remnants were taken anyway"
    print("ok refusal: one remnant short buys nothing")


def check_sync_stops_at_the_cap():
    """The whole track, paid for in full - the cap must hold and must stop charging."""
    st = _fresh(remnants=dimension.total_cost(server.XML_DIR) + 500)
    for _ in range(dimension.level_max(server.XML_DIR) + 3):
        out = server.r_dimension_upgrade({"unitId": DIM}, server.load_state())["dimensionUnit"]
    assert out["dimensionLevel"] == dimension.level_max(server.XML_DIR), \
        f"sync reached level {out['dimensionLevel']}"
    assert out["dimensionNextLevelCost"] == 0, "the capped panel still quotes a price"
    left = server._item_count(server.load_state(), dimension.REMNANT)
    assert left == 500, f"the full track cost {dimension.total_cost(server.XML_DIR)}, {left} left"
    print(f"ok cap: level {out['dimensionLevel']} for exactly "
          f"{dimension.total_cost(server.XML_DIR)} remnants, then free")


def check_overcome_spends_one_ticket_per_step():
    omax = dimension.overcome_max(server.XML_DIR)
    st = _fresh(tickets=omax + 4)
    out = server.r_dimension_overcome({"unitId": DIM, "count": 2}, st)
    assert out["unit"]["overcome"] == 2
    assert out["remainTicket"] == omax + 2, "a step cost more or less than one ticket"

    # Asking for more than the cap allows must stop at the cap, not consume the rest.
    out = server.r_dimension_overcome({"unitId": DIM, "count": 99}, server.load_state())
    assert out["unit"]["overcome"] == omax, f"overcome reached {out['unit']['overcome']}"
    assert out["remainTicket"] == 4, f"{out['remainTicket']} tickets left, expected 4"

    out = server.r_dimension_overcome({"unitId": DIM, "count": 1}, server.load_state())
    assert out["remainTicket"] == 4, "a step past the cap still took a ticket"
    print(f"ok overcome: capped at {omax}, one ticket per step, nothing burnt at the cap")


def check_overcome_refused_without_tickets():
    st = _fresh(tickets=0)
    out = server.r_dimension_overcome({"unitId": DIM, "count": 3}, st)
    assert out["unit"]["overcome"] == 0, "overcome advanced with no tickets"
    print("ok tickets: no ticket, no step")


def check_revive_costs_cash():
    st = _fresh()
    price = server.RCFG["gameComplete"]["revivePrice"]
    server.r_game_revive({}, st)
    assert server.load_state()["cash"] == 1000 - price, "the revive was free"

    st = server.load_state()
    st["cash"] = price - 1
    server.save_state(st)
    out = server.r_game_revive({}, server.load_state())
    assert out.get("msg"), "revived with not enough cash"
    assert server.load_state()["cash"] == price - 1, "cash went negative"

    server.r_game_revive({"useReviveCoupon": True}, server.load_state())
    assert server.load_state()["cash"] == price - 1, "the coupon revive charged cash"
    print(f"ok revive: {price} cash, refused when short, free with a coupon")


if __name__ == "__main__":
    check_only_dimension_heroes_get_a_model()
    check_upgrade_charges_exactly_the_listed_cost()
    check_upgrade_refused_without_remnants()
    check_sync_stops_at_the_cap()
    check_overcome_spends_one_ticket_per_step()
    check_overcome_refused_without_tickets()
    check_revive_costs_cash()
    print("\nall dimension checks passed")
