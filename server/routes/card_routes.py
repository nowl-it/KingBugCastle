"""Card and deck routes: the hero roster, level ups, skins, potentials, dimension
heroes, and deck presets.

Most responses share one card shape (_card_view); the level-up handlers mutate
the card then re-render it. Server-owned helpers (cards_list, card_to_dict,
_pad_deck, DEFAULT_DECKS) stay in server.py and are reached through srv.
"""
from common import admin_log, body_int, body_list, now_iso
from config import XML_DIR
from state import save_state
import dimension

srv = None      # live server module, injected via register()


def register(app, server_module):
    global srv
    srv = server_module
    srv.CARD_OVERRIDES = handlers()


def handlers():
    return {
        "/card/all": r_card_all,
        "/card/upgrade": r_card_upgrade,
        "/card/fast-upgrade": r_card_fast_upgrade,
        "/card/upgradePotentialTier": r_card_upgrade_potential,
        "/card/useCandy": r_card_use_candy,
        "/card/useUnitExpItem": r_card_use_exp_item,
        "/card/useUnitSoulItem": r_card_use_soul_item,
        "/card/useUnitSoulItemToExp": r_card_use_candy,
        "/card/useUnitSoulToExp": r_card_use_candy,
        "/card/buySkin": r_card_buy_skin,
        "/card/equipSkin": r_card_equip_skin,
        "/card/set-random-skin-apply": r_card_set_random_skin,
        "/card/set-skin-favorite": r_card_set_skin_favorite,
        "/card": r_card,
        "/dimension-unit/upgrade": r_dimension_upgrade,
        "/dimension-unit/overcome": r_dimension_overcome,
        "/deck": r_deck,
        "/deck/set": r_deck_set,
        "/deck/setPotential": r_deck_set_potential,
        "/deck/setAllPotential": r_deck_set_all_potential,
        "/deck/buyDeckSlot": r_deck,
        "/deck/set-deck-slot-name": r_deck,
    }


def r_card_all(body, st):
    return {"cards": srv.cards_list(st)}


def r_card_upgrade(body, st):
    unit_id = body.get("unitId", 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["level"] += 1
        if cards[key]["level"] >= 16 and cards[key].get("potentialTier", 0) == 0:
            cards[key]["potentialTier"] = 1
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": 1, "exp": 0, "potentialTier": 0,
                        "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
                        "randomSkinApply": False, "soul": 0})
    player_gold = st.get("gold", 0)
    player_cash = st.get("cash", 0)
    tier = c.get("potentialTier", 0)
    if c["level"] >= 16 and tier == 0:
        tier = 1
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": tier,
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": player_gold, "playerCash": player_cash,
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": tier,
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }


def r_card_fast_upgrade(body, st):
    unit_id = body.get("unitId", 0)
    target_level = body.get("targetLevel", 1)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["level"] = target_level
        if target_level >= 16 and cards[key].get("potentialTier", 0) == 0:
            cards[key]["potentialTier"] = 1
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": target_level, "exp": 0, "potentialTier": 0,
                        "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
                        "randomSkinApply": False, "soul": 0})
    tier = c.get("potentialTier", 0)
    if c["level"] >= 16 and tier == 0:
        tier = 1
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": tier,
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": tier,
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }


def r_card_use_exp_item(body, st):
    unit_id = body.get("unitId", 0)
    count = body_int(body.get("count"), 1, lo=1)

    # Deduct item 151 (Exp Box) or 156 (King Exp Box). We assume 151 for now.
    srv._take_item(st, 151, count)

    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["level"] += 1
        if cards[key]["level"] >= 16 and cards[key].get("potentialTier", 0) == 0:
            cards[key]["potentialTier"] = 1
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": 1})
    tier = c.get("potentialTier", 0)
    if c["level"] >= 16 and tier == 0:
        tier = 1
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": tier,
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": tier,
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }


def r_card_use_soul_item(body, st):
    unit_id = body.get("unitId", 0)
    count = body_int(body.get("count"), 1, lo=1)
    cards = st.setdefault("cards", {})
    key = str(unit_id)

    if key in cards:
        # Deduct soul
        current_soul = cards[key].get("soul", 0)
        cards[key]["soul"] = max(0, current_soul - count)

        cards[key]["level"] += 1
        if cards[key]["level"] >= 16 and cards[key].get("potentialTier", 0) == 0:
            cards[key]["potentialTier"] = 1
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": 1})
    tier = c.get("potentialTier", 0)
    if c["level"] >= 16 and tier == 0:
        tier = 1
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": tier,
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": tier,
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }


def r_card_use_candy(body, st):
    with open("scroll_debug.txt", "a") as f:
        f.write("r_card_use_candy request\n")
    unit_id = body.get("unitId", 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["level"] += 1
        if cards[key]["level"] >= 16 and cards[key].get("potentialTier", 0) == 0:
            cards[key]["potentialTier"] = 1
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": 1})
    tier = c.get("potentialTier", 0)
    if c["level"] >= 16 and tier == 0:
        tier = 1
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": tier,
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": tier,
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }


def r_card_upgrade_potential(body, st):
    unit_id = body_int(body.get("unitId"), 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["potentialTier"] = min(20, cards[key].get("potentialTier", 0) + 1)
        save_state(st)
    # The fallback needs potentialTier: without it, upgrading a hero the save does
    # not have raised KeyError and the route answered 500 instead of a card.
    c = cards.get(key, {"unitId": unit_id, "level": 1, "potentialTier": 0})
    return {**srv.card_to_dict(c),
            "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0)}


def r_card_buy_skin(body, st):
    unit_id = body.get("unitId", 0)
    skin_id = body.get("skinId", 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        skins = cards[key].setdefault("skins", [])
        if skin_id not in skins:
            skins.append(skin_id)
        cards[key]["currentSkin"] = skin_id
        save_state(st)
    return {"unitId": unit_id, "level": 0, "exp": 0, "potentialTier": 0,
            "skins": [skin_id], "favoriteSkinIds": [], "currentSkin": skin_id,
            "randomSkinApply": False, "playerGold": 0, "playerCash": 0, "soul": 0}


def _card_view(c, st):
    """Standard card response shape (no level mutation)."""
    tier = c.get("potentialTier", 0)
    level = c.get("level", 1)
    if level >= 16 and tier == 0:
        tier = 1
    return {
        "unitId": c["unitId"], "level": level, "exp": c.get("exp", 0),
        "potentialTier": tier,
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": level, "originPotentialTier": tier,
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }


def r_card_equip_skin(body, st):
    # EquipSkinRequestModel = {unit, skin}  (NOT unitId/skinId)
    unit_id = body.get("unit", body.get("unitId", 0))
    skin_id = body.get("skin", body.get("skinId", 0))
    cards = st.setdefault("cards", {})
    c = cards.get(str(unit_id))
    if c is not None and (skin_id == 0 or skin_id in c.get("skins", [])):
        c["currentSkin"] = skin_id
        save_state(st)
    return _card_view(c or {"unitId": unit_id, "currentSkin": skin_id}, st)


def r_card_set_skin_favorite(body, st):
    # CardSkinEtcRequestModel = {unitId, skinId, flag}
    unit_id = body.get("unitId", body.get("unit", 0))
    skin_id = body.get("skinId", body.get("skin", 0))
    flag = body.get("flag", True)
    cards = st.setdefault("cards", {})
    c = cards.get(str(unit_id))
    if c is not None:
        fav = c.setdefault("favoriteSkinIds", [])
        if flag and skin_id not in fav:
            fav.append(skin_id)
        elif not flag and skin_id in fav:
            fav.remove(skin_id)
        save_state(st)
    return _card_view(c or {"unitId": unit_id}, st)


def r_card_set_random_skin(body, st):
    # CardSkinEtcRequestModel = {unitId, skinId, flag}
    unit_id = body.get("unitId", body.get("unit", 0))
    flag = body.get("flag", True)
    cards = st.setdefault("cards", {})
    c = cards.get(str(unit_id))
    if c is not None:
        c["randomSkinApply"] = bool(flag)
        save_state(st)
    return _card_view(c or {"unitId": unit_id}, st)


def r_deck(body, st):
    decks = st.get("decks", srv.DEFAULT_DECKS)
    deck_infos = [{"deck": d["deck"], "potential": d.get("potential", []),
                   "firstComerIndex": d.get("firstComerIndex", 0)} for d in decks]
    return {"deckInfos": deck_infos, "defaultPotentialInfo": st.get("defaultPotential", {"unit": [], "potential": []})}


def r_deck_set(body, st):
    # `or []` rather than a get() default: the client sends the key with a null
    # value when a preset is empty, and a default only fires on a missing key.
    preset_idx = body_int(body.get("presetIdx"), 0, lo=0, hi=srv.DECK_PRESETS - 1)
    decks = st.setdefault("decks", list(srv.DEFAULT_DECKS))
    admin_log(f"[DECK/SET] preset={preset_idx} body_keys={list(body.keys())}")
    deck, potential = srv._pad_deck(body_list(body.get("deck")),
                                    body_list(body.get("potential")))
    first_comer = body_int(body.get("firstComerIndex"), 0, lo=0)
    while len(decks) <= preset_idx:
        decks.append({"deck": [0] * srv.DECK_SLOTS, "potential": [0] * srv.DECK_SLOTS, "firstComerIndex": 0})
    decks[preset_idx] = {"deck": deck, "potential": potential, "firstComerIndex": first_comer}
    st["decks"] = decks
    save_state(st)
    return {"deckInfos": [{"deck": d["deck"], "potential": d.get("potential", []),
                           "firstComerIndex": d.get("firstComerIndex", 0)} for d in decks],
            "defaultPotentialInfo": st.get("defaultPotential", {"unit": [], "potential": []})}


def r_deck_set_potential(body, st):
    preset_idx = body_int(body.get("presetIdx"), 0, lo=0, hi=srv.DECK_PRESETS - 1)
    idx = body_int(body.get("idx"), 0, lo=0, hi=srv.DECK_SLOTS - 1)
    unit_id = body_int(body.get("unitId"), 0)
    potential = body_int(body.get("potential"), 0)
    decks = st.setdefault("decks", list(srv.DEFAULT_DECKS))
    admin_log(f"[DECK/SET-POTENTIAL] preset={preset_idx} idx={idx} unitId={unit_id} potential={potential}")
    while len(decks) <= preset_idx:
        decks.append({"deck": [0] * srv.DECK_SLOTS, "potential": [0] * srv.DECK_SLOTS, "firstComerIndex": 0})
    while len(decks[preset_idx]["deck"]) <= idx:
        decks[preset_idx]["deck"].append(0)
    decks[preset_idx]["deck"][idx] = unit_id
    while len(decks[preset_idx]["potential"]) <= idx:
        decks[preset_idx]["potential"].append(0)
    decks[preset_idx]["potential"][idx] = potential
    st["decks"] = decks
    save_state(st)
    return r_deck({}, st)


def r_deck_set_all_potential(body, st):
    potentials = [p for p in body_list(body.get("potentials")) if isinstance(p, dict)]
    st["defaultPotential"] = {"unit": [body_int(p.get("unitId"), 0) for p in potentials],
                              "potential": [body_int(p.get("potential"), 0) for p in potentials]}
    save_state(st)
    return r_deck({}, st)


def _card(st, unit_id):
    return st.setdefault("cards", {}).get(str(unit_id))


def r_card(body, st):
    """One card. The client asks for a single hero after upgrading it; answering with
    the whole roster is wrong shape, and answering with nothing blanks the panel."""
    unit_id = body_int(body.get("unitId") or body.get("id"), 0)
    c = _card(st, unit_id)
    if c is None:
        return {"unitId": unit_id, "level": 1, "exp": 0, "potentialTier": 0,
                "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
                "randomSkinApply": False, "playerGold": st.get("gold", 0),
                "playerCash": st.get("cash", 0), "soul": 0, "originLevel": 1,
                "originPotentialTier": 0, "isLevelSynced": False,
                "isTemporaryRecruited": False, "createdAt": now_iso(-30),
                "dimensionUnit": dimension.model(unit_id, xml_dir=XML_DIR)}
    out = srv.card_to_dict(c)
    out["playerGold"] = st.get("gold", 0)
    out["playerCash"] = st.get("cash", 0)
    return out


def r_dimension_upgrade(body, st):
    """Spend dimension remnants to raise one sync level.

    One level per call, not one per affordable step: the panel animates a single
    level-up and re-reads the card, so jumping several would desync the display from
    the state it just paid for."""
    unit_id = body_int(body.get("unitId"), 0)
    c = _card(st, unit_id)
    if c is None or dimension.model(unit_id, xml_dir=XML_DIR) is None:
        return r_card(body, st)
    level = c.get("dimensionLevel", 0)
    cost = dimension.next_cost(level, XML_DIR)
    if cost and srv._item_count(st, dimension.REMNANT) >= cost:
        srv._take_item(st, dimension.REMNANT, cost)
        c["dimensionLevel"] = level + 1
        c["dimensionGauge"] = 0
        save_state(st)
    return r_card(body, st)


def r_dimension_overcome(body, st):
    """Spend dimension hero breakthrough tickets, one per step, up to OvercomeMax."""
    unit_id = body_int(body.get("unitId"), 0)
    count = body_int(body.get("count"), 1, lo=1)
    c = _card(st, unit_id)
    if c is None or dimension.model(unit_id, xml_dir=XML_DIR) is None:
        return {"unit": dimension.model(unit_id, xml_dir=XML_DIR),
                "remainTicket": srv._item_count(st, dimension.TICKET)}
    room = dimension.overcome_max(XML_DIR) - c.get("overcome", 0)
    step = min(count, room, srv._item_count(st, dimension.TICKET))
    if step > 0:
        srv._take_item(st, dimension.TICKET, step)
        c["overcome"] = c.get("overcome", 0) + step
        save_state(st)
    return {"unit": dimension.model(unit_id, c.get("dimensionLevel", 0),
                                    c.get("dimensionGauge", 0), c.get("overcome", 0),
                                    XML_DIR),
            "remainTicket": srv._item_count(st, dimension.TICKET)}
