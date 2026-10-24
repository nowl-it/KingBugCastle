"""Clan: one player, one clan of one, and all 28 routes that hang off it.

Every clan route used to answer an empty model, so a clan could be created but never
read back, renamed, chatted in, or left. The founder was also handed role 1, which
hides every management control from the person who just made the clan.

Constants.ClanRole: Requested -1, None 0, Member1..3 1..3, SubMaster 9, Master 10.

Handlers keep the (body, st) shape server.py's DYNAMIC_OVERRIDES expects; call
`handlers()` to get the path -> handler mapping.

    python3 clan.py     # self-check
"""
import xml.etree.ElementTree as ET

from common import body_int, body_list, body_str, next_reset_iso, now_iso
from config import PLAYER_DEFAULTS as _PC, RCFG, XML_DIR
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
            # Same bracket as the PvP seasons (AGENTS.md): the client calls the raid
            # "Raid Ended" and shows a countdown to nextClanRaidStartAtDate whenever
            # now < that date, so the start must be in the PAST and the end in the
            # future or the panel can never open. Was next_reset_iso(8) = "starts in
            # 7 days" forever.
            "clanRaidUntilAtDate": next_reset_iso(7),
            "nextClanRaidStartAtDate": now_iso(-1),
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

# ── Clan Raid ────────────────────────────────────────────────────────────────
# The v174 raid routes answered the wrong shape: /clan/raid returned a flat
# {bossId, bossHp, phase} where the client reads ClanRaidResponseModel.clanRaid
# (a nested ClanRaidModel), and every sibling handler spelled its keys as
# decks/memberDamages/supports/bestDeck while the models declare
# clanRaidDeckInfos/members/supporters/bestDecks. The panel opened on nulls.
#
# The client runs the battle itself; the server only owns the persistent raid
# state (which boss, how much HP is left, kill count, decks) and applies the
# damage reported at /clan/raid/end. That state lives inside the clan record as
# c["raid"] so it survives a restart and a re-log.
CLAN_RAID_ATTEMPTS = 5          # battles per reset window
CLAN_RAID_ROUNDS_PER_STAGE = 5  # rounds before the stage (and boss HP) steps up
# Boss max HP IS master data: Units.xml carries <Hp> per boss unit (42200 Bronze
# 375000, 42201 Silver 1050000 ... 42204/5 Diamond+King 5000000), and the client
# clamps the HP bar to the boss unit it draws (GameManager.GetClanRaidBossHp).
# The old CLAN_RAID_BASE_HP = 5_000_000 constant ignored that, so a fresh Bronze
# raid opened at 5,000,000/375,000 - an over-full bar that cannot drop below
# 4.6M no matter what the first battle reports.
_RAID_VERSION = 2               # v1 seeded remainHp from the invented constant

_XML_CACHE: dict = {}

def _xml_rows(fname, tag):
    """Parse a master-data file once; a missing or broken file degrades to []."""
    if fname not in _XML_CACHE:
        try:
            _XML_CACHE[fname] = [el for el in ET.parse(XML_DIR / fname).getroot()
                                 if el.tag == tag]
        except Exception:
            _XML_CACHE[fname] = []
    return _XML_CACHE[fname]

def _raid_boss_ids():
    ids = [int(r.get("ID")) for r in _xml_rows("ClanRaidBossPowers.xml",
                                               "ClanRaidBossPower")
           if (r.get("ID") or "").isdigit()]
    return ids or [42200, 42500]

def _unit_hp_cache():
    """unitId -> <Hp> from Units.xml, honouring Inherit (the Bronze boss defines
    its own Hp; Silver..King override it). Parsed once, like the other tables."""
    if "__hp__" not in _XML_CACHE:
        hp, parents = {}, {}
        for el in _xml_rows("Units.xml", "Unit"):
            uid = el.get("ID")
            if not (uid or "").isdigit():
                continue
            uid = int(uid)
            h = el.findtext("Hp")
            if h and h.isdigit():
                hp[uid] = int(h)
            p = el.get("Inherit")
            if p and p.isdigit():
                parents[uid] = int(p)
        def resolve(u, depth=0):
            if u in hp or depth > 8:
                return hp.get(u, 0)
            p = parents.get(u)
            if p is None:
                return 0
            hp[u] = resolve(p, depth + 1)
            return hp[u]
        for u in list(parents):
            resolve(u)
        _XML_CACHE["__hp__"] = hp
    return _XML_CACHE["__hp__"]

def _raid_max_hp(boss):
    """The boss unit's master-data HP - the exact number the client caps its HP
    bar at. A boss id missing from Units.xml falls back to the Bronze base."""
    return _unit_hp_cache().get(int(boss)) or _unit_hp_cache().get(42200, 375_000)

def _raid_rank_for(kill_count):
    """Highest rank tier whose ReqBossKill the clan has reached -> (tierId, goldBonus)."""
    rows = []
    for r in _xml_rows("ClanRaidRankTiers.xml", "ClanRaidRankTier"):
        req = r.find("ReqBossKill")
        gb = r.find("GoldBonus")
        rows.append((int(req.text) if req is not None and req.text else 0,
                     int(r.get("ID") or 0),
                     int(gb.text) if gb is not None and gb.text else 0))
    tier = bonus = 0
    for req, tid, gb in sorted(rows):
        if kill_count >= req:
            tier, bonus = tid, gb
    return tier, bonus

def _raid(st):
    """The clan's persistent raid state, seeded on first use. None with no clan."""
    c = _clan(st)
    if c is None:
        return None
    r = c.get("raid")
    if not r:
        bosses = _raid_boss_ids()
        r = {"version": _RAID_VERSION, "bossIndex": 0, "boss": bosses[0], "stage": 1,
             "round": 1, "killCount": 0, "score": 0, "remainHp": _raid_max_hp(bosses[0]),
             "remainBattleCount": CLAN_RAID_ATTEMPTS, "remainResetCount": 1,
             "battleStartedAt": now_iso(0), "lastBattleAt": now_iso(-1),
             "supportUnitCardInfo": None, "decks": []}
        c["raid"] = r
    elif r.get("version", 1) < _RAID_VERSION:
        # v1 state carries the invented 5M pool the client can never show;
        # re-seat HP onto the current boss's master-data value once.
        r["version"] = _RAID_VERSION
        r["remainHp"] = _raid_max_hp(r.get("boss", _raid_boss_ids()[0]))
        save_state(st)
    return r

def _raid_card_info(st, unit_id):
    """One owned hero as a ClanRaidCardInfo, or a bare stub for an unowned id."""
    card = next((c for c in st.get("cards", {}).values()
                 if c.get("unitId") == unit_id), None) or {}
    return {"unitId": unit_id, "level": card.get("level", 1),
            "skin": card.get("currentSkin", 0), "potential": card.get("potential", 0),
            "potentialTier": card.get("potentialTier", 0), "overcome": card.get("overcome", 0),
            "dimensionLevel": card.get("dimensionLevel", 0),
            "incarnationSkillLevel": card.get("incarnationSkillLevel", 0),
            "incarnationUltimateSkillLevel": card.get("incarnationUltimateSkillLevel", 0),
            "isLevelSyncApplied": False, "supported": False,
            "accountId": 0, "accountName": None, "treasure": None, "accessories": []}

def _raid_deck_data(st, d):
    """A stored raid deck (flat id lists) back into the ClanRaidDeckData the client renders."""
    return {"cards": [_raid_card_info(st, uid) for uid in d.get("deck", [])],
            "buildings": d.get("buildingLevels", []),
            "roundData": None,
            "artifacts": [], "potentials": d.get("potential", []),
            "territoryStatBuffPers": [], "divinePower": 0.0, "riftWeapons": []}

def _raid_deck_infos(st):
    """The clan's raid decks as List<ClanRaidDeckInfo>. The model names this field
    clanRaidDeckInfos - answering `decks` is exactly the bug this module fixes."""
    r = _raid(st)
    if r is None:
        return []
    infos = []
    for i, d in enumerate(r.get("decks", [])):
        infos.append({"id": d.get("id", i + 1), "idx": d.get("idx", i),
                      "remainCount": r.get("remainBattleCount", 0),
                      "deckName": d.get("name", "") or "",
                      "deck": _raid_deck_data(st, d)})
    return infos

def _ensure_raid_deck(r, idx):
    decks = r.setdefault("decks", [])
    while len(decks) <= idx:
        j = len(decks)
        decks.append({"id": j + 1, "idx": j, "name": "", "deck": [], "potential": [],
                      "buildingLevels": [], "artifactIds": [], "riftWeaponIds": [],
                      "remainCount": 0})
    return decks

def _clan_raid_model(st):
    r = _raid(st)
    if r is None:
        return None
    c = _clan(st) or {}
    d = _PC["defaults"]
    bosses = _raid_boss_ids()
    boss = bosses[min(r.get("bossIndex", 0), len(bosses) - 1)]
    tier, bonus = _raid_rank_for(r.get("killCount", 0))
    return {"clanId": c.get("id", 1), "score": r.get("score", 0),
            "killCount": r.get("killCount", 0), "stage": r.get("stage", 1),
            "round": r.get("round", 1), "boss": boss,
            "remainHp": r.get("remainHp", _raid_max_hp(boss)),
            "currentPlayer": 1, "currentPlayerName": st.get("name", d["name"]),
            "battleStartedAt": r.get("battleStartedAt") or now_iso(0),
            "remainBattleCount": r.get("remainBattleCount", CLAN_RAID_ATTEMPTS),
            "remainResetCount": r.get("remainResetCount", 1),
            "decks": _raid_deck_infos(st),
            "supportUnitCardInfo": r.get("supportUnitCardInfo"),
            "retryInfo": None, "bossList": bosses,
            "seasonEndRank": tier, "goldBonusTier": bonus, "usedSupporter": []}

def r_clan_raid(body, st):
    """FetchClanRaid -> ClanRaidResponseModel. clanRaid holds the full nested
    ClanRaidModel; killBoss is only ever true in the /end response."""
    return {"clanRaid": _clan_raid_model(st), "killBoss": False}

def r_clan_raid_deck(body, st):
    """SetClanRaidDeckPreset: store one raid deck from the client's flat id lists,
    then echo the deck list under clanRaidDeckInfos (not the old `decks`)."""
    c = _clan(st)
    if c is not None:
        r = _raid(st)
        idx = body_int(body.get("deckIdx", body.get("index")), 0, lo=0, hi=CLAN_RAID_DECKS - 1)
        decks = _ensure_raid_deck(r, idx)
        decks[idx].update({
            "deck": body_list(body.get("deck")),
            "potential": body_list(body.get("potential")),
            "buildingLevels": body_list(body.get("buildingLevels")),
            "artifactIds": body_list(body.get("artifactIds")),
            "riftWeaponIds": body_list(body.get("riftWeaponIds")),
        })
        save_state(st)
    return {"clanRaidDeckInfos": _raid_deck_infos(st), "retryInfo": None}

def r_clan_raid_deck_name(body, st):
    """SetClanRaidDeckName: rename one slot, echo the deck list."""
    c = _clan(st)
    if c is not None:
        r = _raid(st)
        idx = body_int(body.get("deckIdx", body.get("index")), 0, lo=0, hi=CLAN_RAID_DECKS - 1)
        decks = _ensure_raid_deck(r, idx)
        name = body_str(body.get("deckName", body.get("name")))
        if name:
            decks[idx]["name"] = name
        save_state(st)
    return {"clanRaidDeckInfos": _raid_deck_infos(st), "retryInfo": None}

def r_clan_raid_delete_deck(body, st):
    """DeleteClanRaidDeck: drop one slot, re-index, echo the deck list."""
    c = _clan(st)
    if c is not None:
        r = _raid(st)
        idx = body_int(body.get("deckIdx", body.get("index")), -1)
        decks = r.get("decks", [])
        if 0 <= idx < len(decks):
            decks.pop(idx)
            for i, d in enumerate(decks):
                d["idx"] = i
                d["id"] = i + 1
            save_state(st)
    return {"clanRaidDeckInfos": _raid_deck_infos(st), "retryInfo": None}

def r_clan_raid_best_deck(body, st):
    """FetchClanRaidBestDecks -> ClanRaidBestDeckResponseModel (`bestDecks`).
    One clan of one, so there are no rival decks to rank against."""
    return {"bestDecks": []}

def r_clan_raid_state(body, st):
    """FetchClanRaidCurrentState -> ClanRaidMemberDamageSumResponseModel. The model
    reads `members`, each with `damageSum` - not the old memberDamages/damage."""
    if _clan(st) is None:
        return {"members": []}
    r = _raid(st)
    mem = _clan_member(st)
    return {"members": [{
        "accountId": mem["accountId"], "castleName": mem["castleName"],
        "userName": mem["userName"], "profileIconId": mem["profileIconId"],
        "profileIconBackgroundId": mem["profileIconBackgroundId"],
        "nameTagId": mem["nameTagId"], "damageSum": r.get("score", 0),
        "lastUpdatedAt": r.get("lastBattleAt") or now_iso(0)}]}

def r_clan_raid_end(body, st):
    """EndClanRaid -> ClanRaidResponseModel. Apply the reported damage to the boss,
    persist it, and advance the raid when the boss dies. Practice battles do not
    count and a retry does not spend another attempt."""
    c = _clan(st)
    if c is None:
        return {"clanRaid": None, "killBoss": False}
    r = _raid(st)
    damage = body_int(body.get("damage"), 0, lo=0)
    practice = str(body.get("isPracticeBattle", "")).lower() in ("true", "1")
    retrying = str(body.get("isRetrying", "")).lower() in ("true", "1")
    r["lastBattleAt"] = now_iso(0)
    kill = False
    if not practice:
        r["score"] = r.get("score", 0) + damage
        r["remainHp"] = max(0, r.get("remainHp", 0) - damage)
        if not retrying:
            r["remainBattleCount"] = max(0, r.get("remainBattleCount", 0) - 1)
        if r["remainHp"] <= 0:
            kill = True
            r["killCount"] = r.get("killCount", 0) + 1
            r["round"] = r.get("round", 1) + 1
            if r["round"] > CLAN_RAID_ROUNDS_PER_STAGE:
                r["round"] = 1
                r["stage"] = r.get("stage", 1) + 1
            bosses = _raid_boss_ids()
            r["bossIndex"] = (r.get("bossIndex", 0) + 1) % len(bosses)
            r["boss"] = bosses[r["bossIndex"]]
            r["remainHp"] = _raid_max_hp(r["boss"])
            r["remainBattleCount"] = CLAN_RAID_ATTEMPTS
        save_state(st)
    return {"clanRaid": _clan_raid_model(st), "killBoss": kill}

def r_clan_raid_support(body, st):
    """FetchClanRaidSupporters -> ClanRaidSupportResponseModel (`supporters`). With a
    single member there is nobody to lend a hero, so the list is empty."""
    return {"supporters": []}

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
        "/clan/raid": r_clan_raid,
        "/clan/raid/deck": r_clan_raid_deck,
        "/clan/raid/deck-name": r_clan_raid_deck_name,
        "/clan/raid/best-deck": r_clan_raid_best_deck,
        "/clan/raid/delete-deck": r_clan_raid_delete_deck,
        "/clan/raid/currentState": r_clan_raid_state,
        "/clan/raid/end": r_clan_raid_end,
        "/clan/raid/support": r_clan_raid_support,
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
