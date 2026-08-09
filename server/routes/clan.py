"""Clan: one player, one clan of one, and all 28 routes that hang off it.

Every clan route used to answer an empty model, so a clan could be created but never
read back, renamed, chatted in, or left. The founder was also handed role 1, which
hides every management control from the person who just made the clan.

Constants.ClanRole: Requested -1, None 0, Member1..3 1..3, SubMaster 9, Master 10.

Handlers keep the (body, st) shape server.py's DYNAMIC_OVERRIDES expects; call
`handlers()` to get the path -> handler mapping.

    python3 clan.py     # self-check
"""
from common import body_int, body_list, body_str, next_reset_iso, now_iso
from config import PLAYER_DEFAULTS as _PC, RCFG, STATIC_OVERRIDES
from decoration import block as _deco
from state import save_state


# A private server has one player, so it has a clan of one. All 28 remaining clan
# routes answered an empty model: the clan could be created but never read back,
# renamed, chatted in, or left.
#
# Constants.ClanRole: Requested -1, None 0, Member1..3 1..3, SubMaster 9, Master 10.
# The old /clan/create lambda handed the founder role 1, so the client hid every
# management control from the person who had just made the clan.
CLAN_MASTER = 10
CLAN_REQUESTED = -1
# Every "pad this list up to the index the client asked for" loop needs a ceiling.
# The index is client-supplied and unauthenticated, so without one a single request
# naming preset 999999999 makes the server allocate until it dies.
CLAN_RAID_DECKS = 10

def _clan(st):
    return st.get("clan")

def _clan_new(st, body):
    c = dict(RCFG["clanCreate"])
    c.update({
        "id": 1,
        "name": body_str(body.get("name")) or "Clan",
        "markId": body_int(body.get("markId") or body.get("mark"), 0),
        "language": body_int(body.get("language"), 0),
        "keywords": body_list(body.get("keywords")),
        "joinType": body_int(body.get("joinType"), 0),
        "intro": body_str(body.get("intro")),
        "notice": body_str(body.get("notice")),
        "tag": body_str(body.get("tag")),
        "point": 0, "tier": 0, "battleTier": 0,
        "contribution": 0, "weeklyContribution": 0,
        "roleNames": [], "chats": [], "seq": 0,
    })
    st["clan"] = c
    st["clanId"] = c["id"]
    st["clanName"] = c["name"]
    return c

def _clan_member(st):
    d = _PC["defaults"]
    deco = _deco(st)
    c = _clan(st) or {}
    return {"accountId": st.get("accountId", d["accountId"]), "role": CLAN_MASTER,
            "castleName": st.get("castleName", d["castleName"]),
            "userName": st.get("name", d["name"]),
            "contribution": c.get("contribution", 0),
            "weeklyContribution": c.get("weeklyContribution", 0),
            "profileIconId": d["profileIconId"], "profileIconBackgroundId": 0,
            "flagId": deco["flag"]["flagId"], "nameTagId": deco["nameTag"],
            "lastLogined": now_iso(0), "playerLevel": st.get("level", 1)}

def _clan_model(st):
    c = _clan(st)
    if not c:
        return None
    d = _PC["defaults"]
    return {"id": c["id"], "name": c["name"], "markId": c.get("markId", 0),
            "language": c.get("language", 0), "keywords": c.get("keywords", []),
            "joinType": c.get("joinType", 0), "intro": c.get("intro", ""),
            "battleTier": c.get("battleTier", 0), "tier": c.get("tier", 0),
            "point": c.get("point", 0), "contribution": c.get("contribution", 0),
            "weeklyContribution": c.get("weeklyContribution", 0),
            "memberCount": 1, "maxMemberCount": c.get("maxMemberCount", 30),
            "masterName": st.get("name", d["name"]),
            "masterAccountId": st.get("accountId", d["accountId"]),
            "nameBanned": False, "roleNames": c.get("roleNames", []),
            "notice": c.get("notice", ""), "members": [_clan_member(st)],
            "chats": c.get("chats", []), "joinRequests": [],
            "goldBonusTier": 0,
            # The only member is the master, so there is nobody to hand it to.
            "canMandateMaster": False,
            "clanRaidRank": 1 if c else 0, "clanPointRank": 1 if c else 0,
            "weeklyClanPointRank": 1 if c else 0}

def r_clan(body, st):
    """The clan the player is in, or null.

    clan:null keeps GameManager.HasClan() false, which is right for an account that
    never joined one - a fake clan object here would show every account a clan it
    does not have."""
    c = _clan(st)
    return {"clan": _clan_model(st), "role": CLAN_MASTER if c else 0,
            "requestSupportCooltime": now_iso(-1),
            "supportCompletedModel": None,
            "seasonUntilAtDate": next_reset_iso(7),
            "nextSeasonStartAtDate": next_reset_iso(8),
            "clanRaidEnabled": bool(c),
            "clanRaidUntilAtDate": next_reset_iso(7),
            "nextClanRaidStartAtDate": next_reset_iso(8),
            "canReceiveClanPointAt": now_iso(-1),
            "canPlayClanRaidAt": now_iso(-1),
            "clanRaidLockedByLeaveUntilAt": now_iso(-1)}

def r_clan_create(body, st):
    if not _clan(st):
        _clan_new(st, body)
        save_state(st)
    return r_clan(body, st)

def _clan_modify(field, cast=str):
    """Most of the clan management routes set one field and re-read the clan."""
    def handler(body, st, _f=field, _c=cast):
        c = _clan(st)
        if c is not None:
            for key in (_f, "name", "value"):
                if key in body:
                    c[_f] = _c(body[key])
                    break
            if _f == "name":
                st["clanName"] = c["name"]
            save_state(st)
        return r_clan(body, st)
    return handler

def r_clan_leave(body, st):
    """Leaving disbands it: there is nobody left to inherit a clan of one."""
    st.pop("clan", None)
    st["clanId"] = 0
    st["clanName"] = ""
    save_state(st)
    return r_clan(body, st)

def r_clan_name_check(body, st):
    """Nothing to collide with on a one-player server, so every name is free. The
    response is still the full clan read - the panel re-renders from it."""
    return r_clan(body, st)

def r_clan_chat(body, st):
    """Post a line. Chat lives in the clan record so it survives a restart, and is
    trimmed - the client re-reads the whole list on every refresh."""
    c = _clan(st)
    if c is None:
        return {"chats": []}
    msg = body.get("message", body.get("text", ""))
    if msg:
        c["seq"] = c.get("seq", 0) + 1
        c.setdefault("chats", []).append({
            "seqId": c["seq"], "type": body_int(body.get("type"), 0),
            "accountId": st.get("accountId", _PC["defaults"]["accountId"]),
            "sender": st.get("name", _PC["defaults"]["name"]),
            "message": msg, "targetUnit": body_int(body.get("targetUnit"), 0),
            "count": 0, "maxCount": 0, "createdAt": now_iso(0), "canSupport": False})
        c["chats"] = c["chats"][-100:]
        save_state(st)
    return {"chats": c.get("chats", [])}

def r_clan_fetch_chat(body, st):
    c = _clan(st) or {}
    return {"chats": c.get("chats", [])}

def r_clan_delete_chat(body, st):
    c = _clan(st)
    if c is not None:
        seq = body_int(body.get("seqId") or body.get("id"), 0)
        c["chats"] = [m for m in c.get("chats", []) if m["seqId"] != seq]
        save_state(st)
    return r_clan_fetch_chat(body, st)

def r_clan_seq(body, st):
    return {"seqId": (_clan(st) or {}).get("seq", 0)}

def r_clan_role_name(body, st):
    """roleNames is a sparse list of {role, name} overrides, so a renamed rank
    replaces its entry rather than appending a second one for the same role."""
    c = _clan(st)
    if c is not None:
        role = body_int(body.get("role"), 0)
        name = body.get("name", "")
        names = [r for r in c.get("roleNames", []) if r.get("role") != role]
        if name:
            names.append({"role": role, "name": name})
        c["roleNames"] = names
        save_state(st)
    return r_clan(body, st)

def r_clan_noop_member(body, st):
    """Ban/promote/demote/mandate/kick, and the join-request flow.

    There is exactly one member and they are the master, so every one of these is a
    no-op by construction rather than by omission - answering the clan read keeps the
    panel consistent instead of leaving it on stale data."""
    return r_clan(body, st)

def r_clan_raid_deck(body, st):
    c = _clan(st) or {}
    decks = c.setdefault("raidDecks", []) if _clan(st) else []
    if _clan(st) is not None and (body.get("deck") or body.get("units")):
        idx = body_int(body.get("index"), 0, lo=0, hi=CLAN_RAID_DECKS - 1)
        while len(decks) <= idx:
            decks.append({"index": len(decks), "name": "", "deck": [], "potential": []})
        decks[idx] = {"index": idx,
                      "name": body.get("name", decks[idx].get("name", "")),
                      "deck": body.get("deck") or body.get("units") or [],
                      "potential": body.get("potential") or []}
        save_state(st)
    return {"decks": decks, "bestDeck": decks[0] if decks else None}

def r_clan_raid_delete_deck(body, st):
    c = _clan(st)
    if c is not None:
        idx = body_int(body.get("index"), -1)
        decks = c.get("raidDecks", [])
        if 0 <= idx < len(decks):
            decks.pop(idx)
            for i, d in enumerate(decks):
                d["index"] = i
            save_state(st)
    return r_clan_raid_deck({}, st)

def r_clan_raid_state(body, st):
    """Damage is per member and there is one member, so the sum is the player's."""
    d = _PC["defaults"]
    dmg = (_clan(st) or {}).get("raidDamage", 0)
    return {"memberDamages": [{"accountId": st.get("accountId", d["accountId"]),
                               "userName": st.get("name", d["name"]),
                               "damage": dmg}] if _clan(st) else [],
            "totalDamage": dmg}

def r_clan_raid_end(body, st):
    c = _clan(st)
    if c is not None:
        c["raidDamage"] = max(c.get("raidDamage", 0), body_int(body.get("damage"), 0))
        save_state(st)
    return dict(STATIC_OVERRIDES["/clan/raid"])

def r_clan_support(body, st):
    """Support is one member handing another a hero. With one member there is nobody
    to ask and nobody to answer, so the lists stay empty and the cooldown stays clear
    rather than pretending a request is pending."""
    return {"supports": [], "requestSupportCooltime": now_iso(-1),
            "supportCompletedModel": None}


def handlers():
    """path -> handler, merged into server.py's DYNAMIC_OVERRIDES."""
    mod = {p: _clan_modify(f, cast) for p, f, cast in [
        ("/clan/modify-name", "name", str), ("/clan/modifyIntro", "intro", str),
        ("/clan/modifyNotice", "notice", str), ("/clan/modifyTag", "tag", str),
        ("/clan/modifyMark", "markId", int), ("/clan/modifyJoinType", "joinType", int),
    ]}
    return {
        "/clan": r_clan, "/clan/info": r_clan,
        "/clan/create": r_clan_create,
        "/clan/leave": r_clan_leave, "/clan/delete": r_clan_leave,
        "/clan/nameCheck": r_clan_name_check,
        "/clan/changeRoleName": r_clan_role_name,
        "/clan/chat": r_clan_chat,
        "/clan/fetchChat": r_clan_fetch_chat, "/clan/refreshChat": r_clan_fetch_chat,
        "/clan/deleteChat": r_clan_delete_chat,
        "/clan/currentSeq": r_clan_seq,
        "/clan/banMember": r_clan_noop_member,
        "/clan/changeMaster": r_clan_noop_member,
        "/clan/mandateMaster": r_clan_noop_member,
        "/clan/changeMemberRole": r_clan_noop_member,
        "/clan/requestJoin": r_clan_noop_member,
        "/clan/processRequestJoin": r_clan_noop_member,
        "/clan/raid/deck": r_clan_raid_deck,
        "/clan/raid/best-deck": r_clan_raid_deck,
        "/clan/raid/deck-name": r_clan_raid_deck,
        "/clan/raid/delete-deck": r_clan_raid_delete_deck,
        "/clan/raid/currentState": r_clan_raid_state,
        "/clan/raid/end": r_clan_raid_end,
        "/clan/raid/support": r_clan_support,
        "/clan/support": r_clan_support,
        "/clan/requestSupport": r_clan_support,
        **mod,
    }


if __name__ == "__main__":
    import playerdb, pathlib as _pl, tempfile, state
    playerdb.DB_PATH = _pl.Path(tempfile.mkdtemp()) / "t.db"
    playerdb.init()
    state.use_default_player({"uid": "t", "name": "K", "castleName": "C", "level": 3})

    st = state.new_save("t")
    assert r_clan({}, st)["clan"] is None, "a fresh account must not appear to have a clan"
    assert r_clan({}, st)["role"] == 0

    out = r_clan_create({"name": "Ours", "tag": "OU"}, st)
    assert out["clan"]["name"] == "Ours"
    assert out["role"] == CLAN_MASTER, "the founder must get master, or the UI hides everything"
    before = out["clan"]["id"]
    assert r_clan_create({"name": "Second"}, st)["clan"]["name"] == "Ours", "create replaced the clan"
    assert r_clan_create({}, st)["clan"]["id"] == before

    _clan_modify("name")({"name": "Renamed"}, st)
    assert _clan(st)["name"] == "Renamed" and st["clanName"] == "Renamed"

    r_clan_chat({"message": "hi"}, st)
    assert [c["message"] for c in r_clan_fetch_chat({}, st)["chats"]] == ["hi"]

    assert r_clan_leave({}, st)["clan"] is None and _clan(st) is None

    paths = handlers()
    # 33 paths, fewer handlers: /clan and /clan/info are the same read, delete is
    # leave, refreshChat is fetchChat, and six member ops are all the same no-op.
    assert len(paths) == 33, f"{len(paths)} routes registered"
    assert all(callable(h) for h in paths.values())
    print(f"clan self-check ok ({len(paths)} routes)")
