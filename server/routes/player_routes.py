"""Player routes: auth/login, building presets, rename, the player profile, and
the tail of one-way /player telemetry routes (ack / ad / other / transfer / wiki).

The login path owns the account/session mapping via playerdb; server-owned gates
(_registration_allowed, the per-IP window, CONTENT_GATE, ALL_ARTIFACT_IDS, the
default save) are reached through srv.
"""
import copy
import hashlib
import random
import secrets

from common import admin_log, body_int, body_str, now_iso, next_reset_iso
from config import PLAYER_DEFAULTS as _PC
from state import (CURRENT_IP, CURRENT_UID, MULTIPLAYER,
                   ADOPT_LONE_SAVE, MAX_PLAYERS, save_state)
import playerdb

srv = None      # live server module, injected via register()

DIMENSION_RIFT_PLAY_COUNT = "DimensionRiftPlayCount"
DIMENSION_RIFT_MAX_CLEARED_CHALLENGE = "DimensionRiftMaxClearedChallenge"


def register(app, server_module):
    global srv
    srv = server_module
    srv.PLAYER_OVERRIDES = handlers()


def handlers():
    return {
        "/auth/login": r_login,
        "/auth/register": r_login,
        "/player": r_player,
        "/player/rename": r_player_rename,
        "/player/building": r_building_get,
        "/player/building/point": r_building_buy_point,
        "/player/building/save": r_building_save,
        "/player/building/resetPoint": r_building_reset_point,
        "/auth/transfer/code": r_transfer_issue,
        "/auth/transfer": r_transfer_redeem,
        "/player/ad": r_player_ad,
        "/player/changeProfileIcon": r_change_profile_icon,
        "/player/other": r_player_other,
        "/player/exception": r_ack,
        "/player/xcdReport": r_ack,
        "/player/customEvent": r_ack,
        "/player/logClickNotice": r_ack,
        "/player/completeKingGakReturnEvent": r_ack,
        "/test/roguelike/clear-count": r_ack,
        "/test/roguelike/play-count": r_ack,
        "/test/roguelike/mission-clear-count": r_ack,
        "/test/roguelike/reset-mission": r_ack,
        "/mission/roguelike/check-on-clear": r_ack,
        "/game/eventMode": r_event_mode,
        "/kg-wiki/insert-wiki": r_wiki,
        "/kg-wiki/rift-weapon/archive": r_wiki_archive,
        "/kg-wiki/rift-weapon/archive-delete": r_wiki_archive_delete,
    }


def _uid_for_login(login_id, prev_token, acct_type=None):
    """Which player a login belongs to.

    Order: known account id -> the session the presented token already belongs to
    (/auth/login carries a token, not an id) -> first-login adoption of a lone
    existing save -> a fresh per-account save (multiplayer) -> the active player.
    """
    # Account ids become durable indexed keys. Malformed input is absent, but a
    # valid prior session can still refresh normally below.
    login_id = login_id if playerdb.valid_login_id(login_id) else ""
    uid = playerdb.uid_for_login(login_id) or playerdb.uid_for_token(prev_token)
    if uid and playerdb.load(uid) is not None:
        return uid
    if MULTIPLAYER and login_id:
        # One-shot migration for a server that was single-player until now: hand its
        # lone unbound save to the first login instead of orphaning it. Off by
        # default - it is indistinguishable from a hijack once the migration is
        # done, and it silently gave a fresh Guest the old test save.
        if ADOPT_LONE_SAVE and playerdb.account_count() == 0 and playerdb.count() == 1:
            sole = playerdb.active()
            if sole and playerdb.load(sole) is not None:
                playerdb.bind_login(login_id, sole)
                admin_log(f"[auth] adopted lone save {sole} for the first account")
                return sole
        uid = "p-" + hashlib.sha1(login_id.encode()).hexdigest()[:12]
        if playerdb.load(uid) is None:
            # The account id is client-supplied and unauthenticated, so anyone who
            # can reach /auth/register can mint saves. Cap it - without this a loop
            # fills the disk.
            # Refuse, never fall back to playerdb.active(): that handed whoever hit
            # the cap a stranger's save, with a session bound to it.
            if playerdb.count() >= MAX_PLAYERS:
                admin_log(f"[auth] refused new player: at KGC_MAX_PLAYERS={MAX_PLAYERS}")
                return None
            ip = CURRENT_IP.get()
            if not srv._registration_allowed(ip):
                admin_log(f"[auth] rate-limited new player from {ip} "
                          f"({srv.NEW_PLAYER_PER_IP}/{srv.NEW_PLAYER_WINDOW}s)")
                return None
            st = copy.deepcopy(srv.DEFAULT_PLAYER)
            st["uid"] = uid
            st["accountId"] = playerdb.next_account_id()
            st["name"] = f"Player{random.randint(1000, 9999)}"
            st["castleName"] = f"Castle{random.randint(1000, 9999)}"
            st["accountCreatedAt"] = now_iso(0)
            if acct_type is not None:
                st["accountType"] = acct_type

            # --- Tier 1 Defaults ---
            # Max Resources (290909)
            st["gold"] = 290909
            st["cash"] = 290909
            st["heart"] = 290909
            st["level"] = 100
            st["exp"] = 9999999
            # Basic Heroes (Lvl 20)
            import gamedata
            for unit_id, info in gamedata.HEROES.items():
                if info.get("min_version", 0) <= srv.CONTENT_GATE:
                    if str(unit_id) in st["cards"]:
                        st["cards"][str(unit_id)]["level"] = 20
            # Maxed Legacies (10*, full AtkSpeedPer)
            arts = st.setdefault("artifacts", [])
            arts.clear()
            for i, aid in enumerate(srv.ALL_ARTIFACT_IDS):
                arts.append(srv.make_max_artifact(i + 1, aid))
            # -----------------------

            playerdb.save(uid, st)
            admin_log(f"[auth] new player {uid} (accountType={acct_type})")
        playerdb.bind_login(login_id, uid)
        return uid
    # Empty id + no token: refuse in multiplayer instead of handing the caller
    # dev-0001's save. That fallback is single-player-only; a client that lost its
    # guest id kept getting the stranger's save with a session bound to it.
    return playerdb.active() if not MULTIPLAYER else None


def r_login(body, st):
    # All date-ish fields must be non-null parseable strings: HandleAuthResponse
    # does DateTime.Parse on expiredAt / serverTime / blockedUntilAt -> null throws
    # ArgumentNullException.
    login_id = srv.CURRENT_LOGIN_ID.get() or body.get("id") or ""
    # Constants.AccountType: 0 Test, 1 Google, 2 GameCenter, 3 AppleID, 4 Guest.
    # Only /auth/register carries it; None on the token-refresh paths.
    acct_type = body_int(body["type"], None) if isinstance(body, dict) and "type" in body else None
    # No bind_login() here: in single-player mode _uid_for_login falls back to the
    # ACTIVE player, and recording that as "account X owns save Y" would pin every
    # account that ever logged in to it - permanently, so a later switch to
    # multiplayer would still hand them all the same save. Only the multiplayer
    # branch, which actually owns the account, writes that mapping.
    uid = _uid_for_login(login_id, body.get("token"), acct_type)
    login_id = login_id if playerdb.valid_login_id(login_id) else ""
    if uid is None:
        # No save and none may be created (cap or rate limit). Nothing to bind a
        # session to; the alternative was logging the caller into someone else.
        return {"success": False, "msg": "cannot create an account right now"}
    # Remember which social login this account used, so PlayerDataResponseModel
    # reports the right accountType (Google vs Guest) and the client shows it.
    acct = playerdb.load(uid)
    if acct is not None:
        rep_changed = _repair_player_state(acct)
        if acct_type is not None and acct.get("accountType") != acct_type:
            acct["accountType"] = acct_type
            rep_changed = True
        if rep_changed:
            playerdb.save(uid, acct)
    token = "DEV." + secrets.token_hex(16)
    playerdb.bind_session(token, uid)   # every later request identifies via this
    CURRENT_UID.set(uid)                # rest of THIS request is already this player
    if acct_type == 4:
        # AutoRegister follows POST /auth/register with GET /auth. Authorize that
        # single native exchange without making arbitrary guest ids impersonable.
        import google_login
        google_login._grant_native_auth(CURRENT_IP.get(), login_id)
    # login_id is a bearer credential (whoever presents it gets that save), and
    # admin_log feeds the dashboard log view - record a fingerprint, not the id.
    fp = hashlib.sha1(login_id.encode()).hexdigest()[:8] if login_id else "-"
    admin_log(f"[auth] login id#{fp} -> uid={uid}")
    return {
        "accessToken": token,
        "expiredAt": now_iso(7),
        "seed": secrets.token_hex(8),
        "serverTime": now_iso(0),
        "blockedUntilAt": now_iso(0),
        "blockedComment": "",
        "loginId": login_id,
    }


def mint_session_token(login_id, acct_type=1):
    """Resolve (or create) the save for `login_id` and bind a fresh session token to
    it, without a full /auth round-trip. The Google web-login flow calls this so the
    deep link can carry a ready-to-use token: the client sets it as RestAPI.accessToken
    and the next /player request lands on this account's save. acct_type default 1 =
    Google (Constants.AccountType)."""
    uid = _uid_for_login(login_id, None, acct_type)
    if uid is None:
        return None
    token = "DEV." + secrets.token_hex(16)
    playerdb.bind_session(token, uid)
    admin_log(f"[glogin] minted token for uid={uid}")
    return token


def _building_point_floor(st):
    """The altar pool must cover what is already allocated: the client renders the
    panel's remaining points as pool minus the current preset's Σlevels, so a pool
    clamped to 0 while levels are high (admin-granted or the old negative-save bug)
    displays NEGATIVE. Raise the pool to the max Σlevels across presets instead."""
    return max((sum(d.get("buildingLevels") or []) for d in (st.get("buildingData") or [])
                if isinstance(d, dict)), default=0)


def _get_building_data(st):
    presets = st.get("buildingData", st.get("buildingPresets", [{"buildingLevels": [0]*6} for _ in range(5)]))
    # WorldPanel.<GameStart>d__349.MoveNext (Ghidra RVA 0x220BC48) indexes
    # response.buildingData once per entry in a static building-type registry
    # (Buildings.xml defines 6 types, IDs 0-5) - fewer buildingData entries
    # than that throws ArgumentOutOfRangeException on literally the first
    # battle-start attempt. Pad (never truncate) so the index always resolves.
    if len(presets) < 10:
        presets = list(presets) + [{"buildingLevels": [0]*6} for _ in range(10 - len(presets))]
    return presets


def r_building_get(body, st):
    return {"buildingData": _get_building_data(st), "buildingPoint": st.get("buildingPoint", 0)}


def r_building_buy_point(body, st):
    st["buildingPoint"] = st.get("buildingPoint", 0) + body_int(body.get("count"), 1, lo=1)
    save_state(st)
    return {"buildingData": _get_building_data(st), "buildingPoint": st["buildingPoint"]}


def r_building_save(body, st):
    # The client sends BuildingRequestModel {levels: int[], preset: int} - the
    # altar allocation for one preset at a time. Reading a `buildingData` key
    # (an earlier draft's shape) silently dropped every allocation, so battles
    # ran with zero altar levels.
    levels = [body_int(x, 0) for x in (body.get("levels") or [])]
    if levels:
        preset = body_int(body.get("preset"), 0)
        presets = st.get("buildingData") or []
        if not isinstance(presets, list):
            presets = []
        while len(presets) <= preset:
            presets.append({"buildingLevels": [0] * 6})
        presets[preset] = {"buildingLevels": levels}
        st["buildingData"] = presets
    else:
        data = body.get("buildingData") or []
        if data:
            st["buildingData"] = [{"buildingLevels": [body_int(x, 0) for x in d.get("buildingLevels", [])]}
                                  for d in data]
    if body.get("buildingPoint") is not None:
        st["buildingPoint"] = body_int(body.get("buildingPoint"), st.get("buildingPoint", 0), lo=0)
    st["buildingPoint"] = max(st.get("buildingPoint", 0), _building_point_floor(st))
    save_state(st)
    return {"buildingData": _get_building_data(st), "buildingPoint": st["buildingPoint"]}


def r_building_reset_point(body, st):
    """"Retrieve Ember": clear the preset's altar allocation. The pool is the
    player's LIFETIME ember total - the panel renders remaining = pool minus the
    preset's Σlevels - so retrieving must NOT refund into it (a refund stacked on
    the existing pool double-counted: 25 + 25 = 50). Zero only the levels; the
    remaining display rises back to the pool on its own."""
    levels = [body_int(x, 0) for x in (body.get("levels") or [])]
    preset = body_int(body.get("preset"), 0)
    presets = st.get("buildingData") or []
    if not isinstance(presets, list):
        presets = []
    while len(presets) <= preset:
        presets.append({"buildingLevels": [0] * 6})
    stored = presets[preset].get("buildingLevels") or [0] * 6
    if levels and any(levels):
        presets[preset]["buildingLevels"] = [
            max(int(stored[i] or 0) - int(levels[i] or 0), 0) for i in range(6)]
    else:
        presets[preset]["buildingLevels"] = [0] * 6
    st["buildingData"] = presets
    st["buildingPoint"] = max(st.get("buildingPoint", 0), _building_point_floor(st))
    save_state(st)
    return {"buildingData": _get_building_data(st), "buildingPoint": st["buildingPoint"]}


def r_player_rename(body, st):
    new_name = str(body.get("name") or "").strip()
    if not new_name:
        return {"success": False, "msg": "empty name"}
    st["name"] = new_name
    if body.get("castleName") is not None:
        st["castleName"] = str(body["castleName"]).strip() or st["castleName"]
    save_state(st)
    return {"success": True, "name": st["name"], "castleName": st["castleName"]}


# ProfilePanel.ReloadChallenge indexes invasion/difficulty records per
# unlockedDifficulty tier (up to 15) -> a shorter list throws
# IndexOutOfRangeException, aborting Reload() before name/avatar/clan/date ever
# get set (root cause of the whole profile-popup bug batch).
# v171.1.00+ builds the invasion carousel from Themes.xml ThemeSeason (1-20, 51-70),
# so every season theme must be in the records - not just 16-20/66-70 (that gap kept
# chapter I-1 = theme 1's difficulty bar locked past Easy). Keep the v172-era battle
# themes first: records-driven clients read chapter I-1 as the FIRST record entry.
# Theme 16 (Invasion I-1) requires ReqPrevThemeDifficulty=3 on the PREVIOUS theme (15,
# the last Story chapter) - ThemeSelectPanel.IsThemeLocked looks this up by ID-1 in the
# same invasionDifficultyRecords dictionary (no separate "story difficulty" field exists
# on PlayerDataResponseModel). Without a record for 15, the lookup returns 0 < 3 -> locked,
# and OnSelectTheme silently falls back to theme=1 instead of refusing selection.
# Theme 10 = prerequisite for Invasion II (OpenInvasionTheme passes theme=10 to
# GetInvasionClearedDifficulty; without a record, it returns 0 < ReqPrevThemeDifficulty(3)
# and the section stays locked). 60-65 = invasion-I hard prerequisite themes.
_PREREQ_THEMES = [10, 15, 60, 61, 62, 63, 64, 65]


def invasion_theme_list():
    """The full ThemeSeason theme list (1-20, 51-70), v172-era battle themes first.

    Shared by the data-layer migration (which seeds per-player records), the /player
    and /invasion/record response builders, and the real-progress recorder."""
    themes = ([t for a, b in _PC["invasionThemeRanges"] for t in range(a, b)]
              + _PREREQ_THEMES)
    return sorted(dict.fromkeys(themes),
                  key=lambda t: (t not in (16, 17, 18, 19, 20, 66, 67, 68, 69, 70), t))


def _repair_player_state(st):
    """Repair old saves in place before they are served or written again. Returns
    True when anything changed so callers know whether to persist."""
    changed = False
    key_values = st.get("keyValues")
    if not isinstance(key_values, list):
        key_values = [{"key": "profileIconId",
                       "value": str(_PC["defaults"]["profileIconId"])}]
        st["keyValues"] = key_values
        changed = True
    present_keys = {kv.get("key") for kv in key_values if isinstance(kv, dict)}
    dimension_defaults = (
        (DIMENSION_RIFT_PLAY_COUNT,
         body_int(st.get("rogueLikePlayedCount"), 0, lo=0)),
        (DIMENSION_RIFT_MAX_CLEARED_CHALLENGE,
         body_int(st.get("rogueLikeChallenge"), -1, lo=-1, hi=16)),
    )
    for key, value in dimension_defaults:
        if key not in present_keys:
            key_values.append({"key": key, "value": str(value)})
            changed = True
    if "decks" not in st or not isinstance(st.get("decks"), list):
        st["decks"] = copy.deepcopy(srv.DEFAULT_DECKS)
        changed = True
    else:
        for d in st["decks"]:
            if not isinstance(d, dict):
                continue
            deck = d.get("deck")
            if not isinstance(deck, list) or len(deck) != srv.DECK_SLOTS:
                d["deck"] = srv._pad_deck(deck, d.get("potential", []))
                changed = True
            if not isinstance(d.get("potential"), list) or len(d["potential"]) != srv.DECK_SLOTS:
                d["potential"] = [0] * srv.DECK_SLOTS
                changed = True
    if not isinstance(st.get("cards"), dict):
        st["cards"] = {}
        changed = True
    bp = st.get("buildingPoint")
    if not isinstance(bp, int) or bp < 0 or "buildingPoints" in st:
        merged = bp if isinstance(bp, int) else 0
        bps = st.get("buildingPoints")
        if isinstance(bps, int):
            merged = max(merged, bps)
        st["buildingPoint"] = max(merged, 0)
        st.pop("buildingPoints", None)
        changed = True
    if st["buildingPoint"] < _building_point_floor(st):
        st["buildingPoint"] = _building_point_floor(st)
        changed = True
    # --- Data-layer seed: the DB row is the source of truth for player data; this
    # migration materializes the defaults once, response builders only read back. ---
    if not isinstance(st.get("invasionRecords"), dict):
        u = _PC["invasionUnlockedDifficulty"]
        st["invasionRecords"] = {str(t): {"cleared": u, "unlocked": u}
                                 for t in invasion_theme_list()}
        changed = True
    ld = _PC["listDefaults"]
    for k in ("eventModeRecord", "rogueLikeBuildingChallengeLevelRecord",
              "currentRanking", "currentHardRanking"):
        if not isinstance(st.get(k), list):
            st[k] = [ld[k + "Value"]] * ld[k + "Count"]
            changed = True
    if "rogueLikeBoughtDlcs" not in st:
        st["rogueLikeBoughtDlcs"] = list(srv.ALL_ROGUE_LIKE_DLCS)
        changed = True
    from routes.artifact_routes import (
        _ensure_defaults, DEFAULT_TREASURES, DEFAULT_ARTIFACTS, ensure_artifact_state,
    )
    from routes.accessory import load_default_corruption_accessories
    from routes import rift as _rift
    _ensure_defaults()
    if not isinstance(st.get("treasures"), list):
        st["treasures"] = copy.deepcopy(DEFAULT_TREASURES)
        changed = True
    if not isinstance(st.get("accessories"), list) or len(st["accessories"]) == 0:
        st["accessories"] = copy.deepcopy(load_default_corruption_accessories())
        changed = True
    if not isinstance(st.get("artifacts"), list):
        st["artifacts"] = copy.deepcopy(DEFAULT_ARTIFACTS)
        changed = True
    if ensure_artifact_state(st):
        changed = True
    if not isinstance(st.get("riftWeapons"), list):
        st["riftWeapons"] = copy.deepcopy(_rift.DEFAULT_RIFT_WEAPONS)
        changed = True
    if not isinstance(st.get("equippedRiftWeapons"), dict):
        st["equippedRiftWeapons"] = {}
        changed = True
    if not isinstance(st.get("riftCrystals"), list) or not st["riftCrystals"]:
        st["riftCrystals"] = copy.deepcopy(_rift.DEFAULT_RIFT_CRYSTALS)
        changed = True
    if "riftGauge" not in st:
        st["riftGauge"] = _rift._parse_xml()["gauge_max"]
        changed = True
    if "riftWeaponArchives" not in st:
        st["riftWeaponArchives"] = []
        changed = True
    return changed


def r_player(body, st):
    # Field set matches PlayerDataResponseModel exactly (dump.cs @0x18-0xC4) - any
    # extra key here is dead weight the client silently ignores (Newtonsoft default),
    # and any missing real field risks an NRE downstream. Ghidra-verified 2026-07-03:
    # buildingPoint/altarPoints/altarLevels/difficultyRecords/season/semiSeason/
    # pvpEnabled/seasonUntilAtDates/nextSeasonStartAtDates/score/tier/rank/bestScore/
    # bestTier/loseCount/theme/deckRecordDifficulty do NOT exist on this model - they
    # were dead fields from an earlier draft. Altar/building data belongs on
    # BuildingResponseModel (/player/building*), not here.
    if _repair_player_state(st):
        save_state(st)
    d = _PC["defaults"]
    return {
        "accountId": st.get("accountId", d["accountId"]),
        "name": st.get("name", d["name"]), "castleName": st.get("castleName", d["castleName"]),
        "kingPostfix": st.get("kingPostfix", 0), "castlePostfix": st.get("castlePostfix", 0),
        "uid": st.get("uid") or "dev-0001", "accountType": st.get("accountType", d["accountType"]),
        "cash": st.get("cash", d["cash"]), "paidCash": st.get("paidCash", d["paidCash"]),
        "gold": st.get("gold", d["gold"]), "level": st.get("level", d["level"]),
        "exp": st.get("exp", d["exp"]), "heart": st.get("heart", d["heart"]),
        "treasureCapacity": 9999, "capacity": 9999, "maxCapacity": 9999,
        "lastHeartTime": st.get("lastHeartTime", now_iso(0)),
        "bestClearedStage": st.get("bestClearedStage", d["bestClearedStage"]),
        "bestClearedTheme": st.get("bestClearedTheme", d["bestClearedTheme"]),
        "bestClearedHardStage": st.get("bestClearedHardStage", d["bestClearedHardStage"]),
        "bestClearedHardTheme": st.get("bestClearedHardTheme", d["bestClearedHardTheme"]),
        "currentDeckPreset": st.get("currentDeckPreset", d["currentDeckPreset"]),
        "playedCount": st.get("playedCount", d["playedCount"]),
        "winCount": st.get("winCount", d["winCount"]),
        "rogueLikePlayedCount": st.get("rogueLikePlayedCount", d["rogueLikePlayedCount"]),
        "rogueLikeCleared": st.get("rogueLikeCleared", d["rogueLikeCleared"]),
        "invasionDifficultyRecords": [
            # difficulty = highest CLEARED tier (GetInvasionClearedDifficulty reads
            # .First(theme).difficulty). Rows come from the save's real records
            # (seeded by the data-layer migration); the d-loop only pads list length
            # for ProfilePanel.ReloadChallenge's per-tier indexing.
            {"theme": t, "difficulty": r["cleared"], "unlockedDifficulty": r["unlocked"]}
            for t in invasion_theme_list()
            for r in (st["invasionRecords"].get(str(t), {"cleared": 0, "unlocked": 0}),)
            for d in range(1, max(1, r["unlocked"]) + 1)
        ],
        "eventModeRecord": st.get("eventModeRecord", []),
        "rogueLikeBuildingChallengeLevelRecord": st.get("rogueLikeBuildingChallengeLevelRecord", []),
        "rogueLikeGameIndex": st.get("rogueLikeGameIndex", d["rogueLikeGameIndex"]),
        "dimensionRiftGameIndex": st.get("dimensionRiftGameIndex", d["dimensionRiftGameIndex"]),
        "currentRanking": st.get("currentRanking", []),
        "currentHardRanking": st.get("currentHardRanking", []),
        "tomorrow": next_reset_iso(1),
        "nextWeek": next_reset_iso(7),
        "hasFreeRename": st.get("hasFreeRename", d["hasFreeRename"]),
        "eventFlag": st.get("eventFlag", d["eventFlag"]),
        "eventPlayedCount": st.get("eventPlayedCount", 0),
        "clanAttendance": st.get("clanAttendance", d["clanAttendance"]),
        "tokens": st.get("tokens", []),
        # profileIconId must be a real Unit ID (ResourceBase<Unit>.Get lookup) - a
        # non-resolving id gives a blank/white avatar.
        "keyValues": st.get("keyValues", [{"key": "profileIconId", "value": d["profileIconId"]}]) + [
            # AccessorySubStatGrade.Set() opens with GetKeyValueInt("AccessoryRenewal")
            # and SetActive(false)s the whole grade badge unless it is 1 - which is
            # why substats rendered with no tier. It is the ONLY reader of the flag
            # (verified by scanning every reference to the literal), so turning it
            # on enables the badge and nothing else. Tier itself is
            # Utility.LowerBound(AccessorySubStatScoreRange, score), thresholds from
            # AccessoryConstants.xml: 1, 4.5, 8.5, 13.5, 18.5, 22.5, 26.5.
            {"key": "AccessoryRenewal", "value": "1"},
            {"key": "InventoryCount_Treasure", "value": "999"},
            {"key": "InventoryCount_Accessory", "value": "999"},
            {"key": "InventoryCount_RiftWeapon", "value": "999"},
            {"key": "InventoryCount_RiftCrystal", "value": "999"},
            {"key": "InventoryCount_AccessoryPreset", "value": "999"},
            {"key": "RiftGauge", "value": str(st.get("riftGauge", 1000))},
            {"key": "RiftGaugeBuyCount", "value": str(st.get("riftGaugeBuyCount", 0))},
        ],
        "attendedCustomEvents": st.get("attendedCustomEvents", []),
        "customEventDatas": st.get("customEventDatas", []),
        "eventMissionData": st.get("eventMissionData", []),
        "eventData": st.get("eventData", []),
        "rogueLikeBoughtDlcs": st.get("rogueLikeBoughtDlcs") or [],
        "accountCreatedAt": st.get("accountCreatedAt", now_iso(0)),
    }


def r_ack(body, st):
    """Bare acknowledgement. Several colosseum routes report progress the server has
    nothing to keep (a cancelled match, a re-entry attempt) but still must answer."""
    return {}


# --- The rest of /player ------------------------------------------------------
# Seventeen /player routes answered an empty model. Most are one-way telemetry the
# client never reads back, but /player/other's panel does read name/castleName, and
# /player/heart/recover hands the lobby its heart widget state. The keyValues
# helpers feed changeProfileIcon and the /player heart recover path.

def _key_values(st):
    return list(st.get("keyValues", []))


def _set_key_value(st, key, value):
    kvs = st.setdefault("keyValues", [])
    for kv in kvs:
        if kv.get("key") == key:
            kv["value"] = str(value)
            break
    else:
        kvs.append({"key": key, "value": str(value)})
    save_state(st)


def _key_value(st, key, default=None):
    for kv in st.get("keyValues", []):
        if kv.get("key") == key:
            return kv.get("value", default)
    return default


def r_change_profile_icon(body, st):
    # ChangeProfileIconRequestModel = {profileIconId}.
    icon = body_int(body.get("profileIconId"), 0)
    if str(icon) in st.get("cards", {}):
        _set_key_value(st, "profileIconId", icon)
    return {"keyValues": _key_values(st)}


def r_player_ad(body, st):
    st["dailyAdCount"] = body_int(st.get("dailyAdCount"), 0, lo=0) + 1
    save_state(st)
    return {"dailyAdCount": st["dailyAdCount"]}


def r_player_other(body, st):
    from roster import player_by_id
    st = player_by_id(body_int(body.get("targetId"), 0), st)
    d = _PC["defaults"]
    decks = st.get("decks") or srv.DEFAULT_DECKS
    preset = body_int(st.get("currentDeckPreset"), 0, lo=0, hi=len(decks) - 1)
    deck = decks[preset]
    cards = st.get("cards", {})
    current_deck = []
    for unit_id in deck.get("deck", []):
        if not unit_id:
            continue
        card = cards.get(str(unit_id), {})
        current_deck.append({
            "cardId": unit_id,
            "level": card.get("level", 1),
            "skin": card.get("currentSkin", 0),
            "potentialTier": card.get("potentialTier", 0),
            "isLevelSyncApplied": card.get("isLevelSynced", False),
            "treasure": None,
            "accessories": [],
        })
    return {
        "name": st.get("name", d["name"]),
        "castleName": st.get("castleName", d["castleName"]),
        "kingPostfix": st.get("kingPostfix", 0),
        "castlePostfix": st.get("castlePostfix", 0),
        "profileIconId": body_int(_key_value(st, "profileIconId"), d["profileIconId"]),
        "profileIconBackgroundId": body_int(_key_value(st, "profileIconBackgroundId"), 0),
        "nameTagId": st.get("nameTagId", 0),
        "level": st.get("level", d["level"]),
        "exp": st.get("exp", d["exp"]),
        "invasionDifficultyRecords": r_player({}, st)["invasionDifficultyRecords"],
        "eventModeRecord": st.get("eventModeRecord", []),
        "rogueLikeBuildingChallengeLevelRecord": st.get("rogueLikeBuildingChallengeLevelRecord", []),
        "babelRecord": st.get("babelRecord", []),
        "winCount": st.get("winCount", 0),
        "heroCount": len(cards),
        "currentAltar": st.get("currentAltar", 0),
        "currentDeck": current_deck,
        "currentPotential": deck.get("potential", []),
        "firstComerIndex": deck.get("firstComerIndex", 0),
        "currentRanking": st.get("currentRanking", []),
        "currentHardRanking": st.get("currentHardRanking", []),
        "clanId": st.get("clanId", 0),
        "clanMark": st.get("clanMark", 0),
        "clanRole": st.get("clanRole", 0),
        "clanName": st.get("clanName", ""),
    }


def r_transfer_issue(body, st):
    """Issue a transfer code bound to the current player. Short-lived and single
    use: the redeem path pops it, so a replayed code can never log a second
    account in. The player id is recoverable from the code, which is the point."""
    import secrets as _s
    code = _s.token_hex(4).upper()
    st["transfer"] = {"code": code, "expiresAt": now_iso(1)}
    save_state(st)
    return {"secretCode": code}


def _transfer_lookup(code):
    """uid whose unexpired save carries this transfer code, else None."""
    for uid, st, _updated in playerdb.all_players():
        t = (st or {}).get("transfer") or {}
        if t.get("code") == code and t.get("expiresAt", "") > now_iso(0):
            return uid
    return None


def r_transfer_redeem(body, st):
    """Redeem a code: bind the caller's login to the save that issued it and hand
    back a session for it. A wrong or expired code logs nobody in."""
    code = body_str(body.get("secretCode")).upper()
    uid = _transfer_lookup(code)
    if uid is None:
        admin_log("[auth] transfer redeem refused: unknown or expired code")
        return {"success": False, "msg": "invalid transfer code"}
    src = playerdb.load(uid) or {}
    src.pop("transfer", None)           # single use
    playerdb.save(uid, src)
    login_id = srv.CURRENT_LOGIN_ID.get() or body.get("id") or ""
    if MULTIPLAYER and playerdb.valid_login_id(login_id):
        # Only multiplayer owns the account table; in single-player _uid_for_login
        # ignores login ids entirely and writing one here would pin it forever.
        playerdb.bind_login(login_id, uid)
    token = "DEV." + secrets.token_hex(16)
    playerdb.bind_session(token, uid)
    CURRENT_UID.set(uid)
    admin_log(f"[auth] transfer redeemed -> uid={uid}")
    return {"accessToken": token, "expiredAt": now_iso(7),
            "seed": secrets.token_hex(8), "serverTime": now_iso(0),
            "blockedUntilAt": now_iso(0), "blockedComment": "", "loginId": uid, "userId": uid}


def r_event_mode(body, st):
    """Which limited-time battle modes are open. Every list must be present - the
    panel zips them together by index, and a null list is a NullReference before it
    ever gets to check whether the mode is empty. No event mode is running, so they
    are all empty rather than absent."""
    return {"eventModes": [], "eventModeFlags": [], "eventModeHeartCost": [],
            "eventModeMaxPlayCount": [], "allEventModes": [], "eventModeFlagCost": []}


def r_wiki(body, st):
    """The wiki's per-category unlock state. Percentages are computed by the client
    from the element list, so an absent category reads as 0% rather than crashing."""
    empty = {"wikiElements": [], "percentage": 0}
    return {k: dict(empty) for k in
            ("unitWiki", "artifactWiki", "treasureWiki", "accessoryWiki",
             "riftWeaponWiki", "cutsceneWiki", "storyInventoryWiki")} | \
           {"riftWeaponArchives": st.get("riftWeaponArchives", [])}


def r_wiki_archive(body, st):
    """Archive a rift weapon so its rolled options can be looked at later."""
    archives = st.setdefault("riftWeaponArchives", [])
    wid = body_int(body.get("riftWeaponId") or body.get("id"), 0)
    weapon = next((w for w in srv.DEFAULT_RIFT_WEAPONS if w.get("id") == wid), None)
    if weapon and not any(a.get("id") == wid for a in archives):
        archives.append(weapon)
        save_state(st)
    return {"riftWeapons": archives, "deletedRiftWeapons": [],
            "rewardListResponseData": None, "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0), "upgradeState": 0,
            "equippedWeaponIds": []}


def r_wiki_archive_delete(body, st):
    wid = body_int(body.get("riftWeaponId") or body.get("id"), 0)
    st["riftWeaponArchives"] = [a for a in st.get("riftWeaponArchives", [])
                                if a.get("id") != wid]
    save_state(st)
    return r_wiki(body, st)
