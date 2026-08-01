#!/usr/bin/env python3
"""KGC private server emulator.

Reconstructed from il2cpp dump (RestAPI class + Awesomepiece.Model + route strings).
Implements the full login critical path so the client boots past the title screen,
plus a generic dispatcher that returns a wire-valid ResponseModel for all ~284
endpoints. Player save is a single editable JSON in state/player.json with full
state persistence for cards, decks, inventory, missions, and game loop.

Run:  uvicorn server:app --host 0.0.0.0 --port 8080
"""
import asyncio, contextvars, json, time, copy, secrets, datetime, pathlib, hashlib, os, sys, random
import shutil, subprocess
import playerdb
import rewardbox
import shop
import missions
import challenge
import territory
import decoration
import dimension
import attendance
import babel
import clan
import colosseum
import player_events
# import mini_games
import roster
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, HTMLResponse
from Crypto.Cipher import AES

AES_KEY = b"b53019bb76da6b34"

# Shared primitives now live in common.py so domain modules can use them without
# importing server.py back. Re-exported under their old names: every handler below,
# and the tests, call them unqualified.
from common import (LOG_BUF, admin_log, trace, now_iso, next_reset_iso,
                    body_int, body_list, body_str, date_default)

# Cross-account reads (boards, matchmaking, player lookup) live in roster.py. Kept
# under their old private names so handlers and srv.* lookups did not have to move.
from roster import (all_states as _all_states, board as _board, current_uid as _current_uid,
                    deck_units as _deck_units, leaderboard as _leaderboard,
                    opponents as _opponents, player_by_id as _player_by_id,
                    rank_row as _rank_row)

def aes_encrypt(payload: dict) -> bytes:
    # Space-pad to 16-byte blocks (NOT PKCS7): the client's Newtonsoft JSON reader
    # throws "Additional text after JSON" on non-whitespace trailing bytes, but
    # tolerates trailing spaces. (Confirmed via JsonReaderException at runtime.)
    raw = json.dumps(payload).encode()
    if len(raw) % 16:
        raw += b" " * (16 - len(raw) % 16)
    return AES.new(AES_KEY, AES.MODE_ECB).encrypt(raw)

def encrypted_response(payload: dict) -> Response:
    """Standard AES-encrypted JSON response the game client expects."""
    return Response(aes_encrypt(payload), media_type="application/json",
                    headers={"encryptedWithHex": "true"})

def aes_decrypt(data: bytes) -> dict:
    # Some request bodies (e.g. /deck/set) arrive as ASCII hex text of the
    # ciphertext, not raw binary - matches the "encryptedWithHex" header name
    # literally. Endpoints with meaningful POST bodies need this; GET-only /
    # body-ignoring endpoints never exposed the bug. Detect and unwrap first.
    if len(data) % 2 == 0 and all(c in b"0123456789abcdefABCDEF" for c in data):
        try:
            data = bytes.fromhex(data.decode("ascii"))
        except ValueError:
            pass
    # Tolerant of any padding scheme the client uses (PKCS7, space, or null):
    # decode the first JSON object and ignore trailing pad bytes.
    raw = AES.new(AES_KEY, AES.MODE_ECB).decrypt(data)
    text = raw.decode("utf-8", "ignore").lstrip()
    return json.JSONDecoder().raw_decode(text)[0]

# Paths, response config and the content gate live in config.py - a domain module
# needs RCFG/XML_DIR and cannot import server.py back. Re-exported under their old
# names so every handler below reads unqualified.
from config import (ROOT, DATA_DIR, STATE_DIR, MODELS, RCFG, STATIC_OVERRIDES,
                    ITEM_TEMPLATES, CONFIG_FILE, PATCH_FOLDER, SERVER_VERSION,
                    CONTENT_GATE, XML_DIR)
import config

ROUTE_MODELS = config.load_route_models()
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Player state lives in state/players.db (SQLite, WAL). The old JSON files are
# imported once and then left alone as a cold backup - they are NOT read again.
_migrated = playerdb.migrate_from_json(STATE_DIR)
if _migrated:
    admin_log(f"[state] migrated {_migrated} player(s) from JSON into {playerdb.DB_PATH.name}")
admin_log(f"[gate] serverVersion {SERVER_VERSION} -> content gate {CONTENT_GATE}")
admin_log(f"[xml] master data dir: {XML_DIR} ({len(list(XML_DIR.iterdir()))} files)")

# Identity, the save template and the read/write path live in state.py so handler
# modules can persist without importing server.py back. Re-exported under their old
# names; _registration_allowed keeps its underscore because tests reach for it.
from state import (CURRENT_UID, CURRENT_IP, MULTIPLAYER, MAX_PLAYERS, ADOPT_LONE_SAVE,
                   NEW_PLAYER_PER_IP, NEW_PLAYER_WINDOW,
                   load_state, save_state, patch_state,
                   registration_allowed as _registration_allowed)
import state
state.announce()

def _all_hero_ids():
    """Playable heroes = <Type>Player</Type>, id 1xxxx, from Units.xml."""
    import re
    txt = (XML_DIR / "Units.xml").read_text(encoding="utf-8")
    ids = []
    for blk in re.split(r'(?=<Unit ID=)', txt):
        m = re.match(r'<Unit ID="(\d+)"', blk)
        if not m:
            continue
        uid = int(m.group(1))
        t = re.search(r'<Type>(\w+)</Type>', blk)
        if t and t.group(1) == "Player" and 10000 <= uid < 20000:
            visible = re.search(r'<Visible>(false|False)</Visible>', blk)
            summoner = re.search(r'<Summoner>', blk)
            min_ver = re.search(r'<MinVersion>(\d+)</MinVersion>', blk)
            is_unreleased = min_ver and int(min_ver.group(1)) > CONTENT_GATE
            if not visible and not summoner and not is_unreleased:
                ids.append(uid)
    return ids

ALL_HERO_IDS = _all_hero_ids()

def _all_artifact_ids():
    """Real collectible artifacts (Type=Artifact) from Artifacts.xml, Root/
    Normal tier only (King/God/KingGod tier IDs are the same artifact at
    higher quality, not separate items). Excludes FromType=Special (Ghidra:
    ResourceArtifact.FromType enum value 5) - these are synthesis-stone
    materials (e.g. id 501/511/598, "합성석"), and live testing (2026-07-02)
    confirmed InventoryPanel.GetArtifactItems NullReferenceExceptions trace
    to exactly these 3 IDs; ResourceBase<ResourceArtifact>.Get() apparently
    never registers FromType=Special entries in its lookup dictionary."""
    import re
    txt = (XML_DIR / "Artifacts.xml").read_text(encoding="utf-8")
    txt = re.sub(r'<!--.*?-->', '', txt, flags=re.DOTALL)
    ids = []
    for blk in re.split(r'(?=<Artifact ID=)', txt):
        m = re.match(r'<Artifact ID="(\d+)"', blk)
        if not m:
            continue
        aid = int(m.group(1))
        t = re.search(r'<Type>(\w+)</Type>', blk)
        if not t or t.group(1) != "Artifact":
            continue
        from_type = re.search(r'<FromType>(\w+)</FromType>', blk)
        if from_type and from_type.group(1) in ("Special", "RogueLike", "RogueLikeBuildingArtifact", "Event"):
            continue
        min_ver = re.search(r'<MinVersion>(\d+)</MinVersion>', blk)
        if min_ver and int(min_ver.group(1)) > CONTENT_GATE:
            continue
        level_m = re.search(r'<Level>(.*?)</Level>', blk)
        level = level_m.group(1) if level_m else "Normal"
        if aid not in ids:
            ids.append(aid)
            
        # Store level info for option generation
        if not hasattr(_all_artifact_ids, 'levels'):
            _all_artifact_ids.levels = {}
        _all_artifact_ids.levels[aid] = level

    return ids, getattr(_all_artifact_ids, 'levels', {})

def _all_treasure_ids():
    """Real treasures from Treasures.xml, excluding unreleased (MinVersion)."""
    import re
    txt = (XML_DIR / "Treasures.xml").read_text(encoding="utf-8")
    txt = re.sub(r'<!--.*?-->', '', txt, flags=re.DOTALL)
    ids = []
    for blk in re.split(r'(?=<Treasure ID=)', txt):
        m = re.match(r'<Treasure ID="(\d+)"', blk)
        if not m:
            continue
        min_ver = re.search(r'<MinVersion>(\d+)</MinVersion>', blk)
        if min_ver and int(min_ver.group(1)) > CONTENT_GATE:
            continue
        tid = int(m.group(1))
        if tid == 20099:
            continue
        ids.append(tid)
    return ids

def _all_rift_weapon_ids():
    """Real rift weapons from RiftWeapons.xml (one per class/role, 6 total)."""
    import re
    txt = (XML_DIR / "RiftWeapons.xml").read_text(encoding="utf-8")
    txt = re.sub(r'<!--.*?-->', '', txt, flags=re.DOTALL)
    return [int(m) for m in re.findall(r'<RiftWeapon ID="(\d+)"', txt)]

def _rift_building_count():
    """How many altars a rift crystal carries a level for.

    Buildings.xml holds two ranges: the 6 in-battle altars (ids 0-5) and the
    upgradeable altars (ids 100+) that `BuildingName_0..N` name and that
    RiftWeaponBuffs.xml's `Building` attribute indexes into ("building indexes :
    제단 인덱스 (Buildings.xml id)" per that file's own header).

    `RiftCrystalModel.buildingLevels` is one level per altar in that second range,
    positioned by each entry's own `<Index>` (0-8), not by its id. `GetMaxBuildingIdx`
    (v171 RVA 0x2CCA1B4) walks the whole list and returns the index of the largest
    value, so a list shorter than the altar count silently hides every altar past its
    end - which is why a 3-element list always resolved to altar 0 ("Rift Crystal of
    Hero") no matter what the crystal was meant to be.

    Parsed with ElementTree, not a regex: Buildings.xml quotes its attributes with
    single quotes, so the `ID="..."` pattern the other loaders here use matches nothing
    and would silently report zero altars.
    """
    import xml.etree.ElementTree as _ET
    root = _ET.parse(XML_DIR / "Buildings.xml").getroot()
    idxs = [int(b.findtext("Index") or -1) for b in root
            if (b.findtext("Name") or "").startswith("BuildingName_")]
    assert idxs, "Buildings.xml has no BuildingName_* altars - rift crystals would be empty"
    return max(idxs) + 1

def _all_inventory_item_ids():
    """Consumables/keys/tokens/boxes from InventoryItems.xml."""
    import re
    txt = (XML_DIR / "InventoryItems.xml").read_text(encoding="utf-8")
    txt = re.sub(r'<!--.*?-->', '', txt, flags=re.DOTALL)
    return [int(m) for m in re.findall(r'<InventoryItem ID="(\d+)"', txt)]

ALL_ITEM_IDS = _all_inventory_item_ids()

# Seed data (player identity/currencies, card template, deck presets) lives in
# data/default_player.json - editable without touching code, simulates a DB
# seed row. Only used to build state/player.json on first boot; after that
# the live file is the source of truth.
SEED = json.loads((ROOT / "data" / "default_player.json").read_text())
INV_COUNT = SEED["invCount"]

# God account: own every hero, level 30. Units.xml only defines Tier='1'
# potential (ReqLevel=16, matches Constants.PotentialTier.Max=1 in the client) -
# awakening (thức tỉnh) is a single tier: 0 = not awakened, 1 = awakened (max).
# Seed potentialTier=0 (default_player.json cardTemplate) so fresh heroes do NOT
# show the awakened badge (client renders "CardPotentialTier_{tier}"); the client
# only enables the awaken button at level >= ReqLevel(16) and tier < Max(1).
# An earlier retest blamed potentialTier=1 for the DeckPanel boot crash, but
# Ghidra (2026-07-02, arm32 dump.cs FUN_01e1a018) proved the real cause was deck
# length vs. DeckPanel.currentDeck's fixed 6-slot UI array (see DEFAULT_DECKS
# below) - potentialTier was never the culprit, that test just happened to run
# before the deck-length fix was in place.
DEFAULT_CARDS = {
    str(uid): {"unitId": uid, **SEED["cardTemplate"]}
    for uid in ALL_HERO_IDS
}

# Ghidra-confirmed (2026-07-02, arm32 dump.cs offsets, FUN_01e1a018/DeckPanel.
# ReloadDeck @0x1e1a018): the loop bound is DeckPanel.currentDeck (UnitCard[]
# @0xa4), a Unity-prefab-FIXED-size UI array, not server data - it indexes
# PlayerData.currentDeck (our deck array, int[] @0x5c on PlayerData) with that
# fixed bound, so our deck must be >= DeckPanel's fixed UI slot count or it
# throws IndexOutOfRangeException. WorldPanel.ReloadLobbyDeck (@0x21f4b98) is
# the mirror case: it loops over OUR deck length and indexes its own fixed
# lobbyDeckObjects/lobbyDeckParents/lobbyDeckUnitName arrays, so our deck must
# be <= that fixed UI slot count. Testing deck=6 now to find where both fixed
# sizes actually land (previous 5-vs-6 flip-flop was guesswork, not verified
# against decompiled bounds).
DEFAULT_DECKS = SEED["decks"]
DECK_SLOTS = len(DEFAULT_DECKS[0]["deck"])
# Every "pad this list up to the index the client asked for" loop needs a ceiling.
# The index is client-supplied and unauthenticated, so without one a single request
# naming preset 999999999 makes the server allocate until it dies.
DECK_PRESETS = len(DEFAULT_DECKS)
BUILDING_PRESETS = 10          # _get_building_data pads to this
from clan import CLAN_RAID_DECKS

def _pad_deck(deck, potential):
    # Client (DraggableUnitCard.SwapCard, Ghidra-confirmed) crashes on drag-swap
    # into an occupied slot with an unhandled IndexOutOfRangeException (GetIndex
    # FromCurrentDeck returns -1 for the dragged card, used unguarded as an array
    # index). Whatever partial/corrupt deck state exists at that moment still
    # gets persisted via /deck/set before the crash - e.g. deck:[] wipes the
    # active preset, which then breaks DeckPanel.ReloadDeck on next boot
    # (needs len==DECK_SLOTS, see above). Pad/truncate every incoming write so
    # the stored deck can never violate that invariant, regardless of what
    # broken state the client sends.
    deck = (list(deck) + [0] * DECK_SLOTS)[:DECK_SLOTS]
    potential = (list(potential) + [0] * DECK_SLOTS)[:DECK_SLOTS]
    return deck, potential

DEFAULT_PLAYER = {
    **SEED["player"],
    "accountCreatedAt": now_iso(0),
    "lastHeartTime": now_iso(0), "tomorrow": now_iso(1), "nextWeek": now_iso(7),
    "cards": DEFAULT_CARDS,
    "decks": DEFAULT_DECKS,
    "defaultPotential": {"unit": [], "potential": []},
    "inventory": {"itemIds": list(ALL_ITEM_IDS), "counts": [INV_COUNT] * len(ALL_ITEM_IDS)},
    "inventoryItems": {},
    "tutorialKeyValues": [],
    "missions": [{"missionId": 1, "value": 1, "goalValue": 10, "clear": False, "createdAt": now_iso(0), "untilAt": now_iso(86400)}],
    "eventFlag": 0,
    "tokens": [],
}
# state.load_state() needs the template, and it is only complete here - the hero,
# item and deck lists above are content-gated against master data.
state.use_default_player(DEFAULT_PLAYER)

_game_store = {}

def build_model(name, overlay=None):
    out = {}
    spec = MODELS.get(name)
    if spec:
        for f in spec["fields"]:
            out[f["name"]] = f["default"]
    else:
        out = {"code": 0, "msg": ""}
    out["code"] = 200
    out["msg"] = None
    out["success"] = True
    if overlay:
        out.update(overlay)
    if spec:
        # AFTER the overlay, not before. The client hands date-shaped strings to
        # DateTime.Parse, which throws on null AND on "" - and the nulls do not only
        # come from unset defaults. data/static_overrides.json writes some literally
        # (`"eventPackageItemsUntilAt": null`) and a handler writes `"passEndedAt": ""`,
        # so filling defaults alone left seven routes still carrying an unparseable
        # value. A handler that means "no deadline" has to say so with a date, because
        # null is not something the client can read.
        for f in spec["fields"]:
            if f["jtype"] == "string" and not out.get(f["name"]):
                out[f["name"]] = date_default(f["name"], now_iso) or out.get(f["name"])
    return out

def card_to_dict(c):
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": c.get("potentialTier", 0),
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": 0, "playerCash": 0, "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": c.get("potentialTier", 0),
        "isLevelSynced": False, "isTemporaryRecruited": False,
        "createdAt": now_iso(-30),
        # Null for an ordinary hero, which is correct; a dimension hero needs it or
        # its sync panel opens with no level, no gauge and no next cost.
        "dimensionUnit": dimension.model(c["unitId"], c.get("dimensionLevel", 0),
                                         c.get("dimensionGauge", 0),
                                         c.get("overcome", 0), XML_DIR),
    }

def cards_list(st):
    return [card_to_dict(c) for c in st.get("cards", {}).values()]

# The client's account id for the request being handled: `?id=` on /auth/auth,
# or `id` in the /auth/register body. Only r_login reads it.
CURRENT_LOGIN_ID = contextvars.ContextVar("current_login_id", default=None)

def _uid_for_login(login_id, prev_token, acct_type=None):
    """Which player a login belongs to.

    Order: known account id -> the session the presented token already belongs to
    (/auth/login carries a token, not an id) -> first-login adoption of a lone
    existing save -> a fresh per-account save (multiplayer) -> the active player.
    """
    login_id = str(login_id or "")
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
            if not _registration_allowed(ip):
                admin_log(f"[auth] rate-limited new player from {ip} "
                          f"({NEW_PLAYER_PER_IP}/{NEW_PLAYER_WINDOW}s)")
                return None
            st = copy.deepcopy(DEFAULT_PLAYER)
            st["uid"] = uid
            st["accountId"] = playerdb.next_account_id()
            st["name"] = f"Player{random.randint(1000, 9999)}"
            st["castleName"] = f"Castle{random.randint(1000, 9999)}"
            st["accountCreatedAt"] = now_iso(0)
            if acct_type is not None:
                st["accountType"] = acct_type
            playerdb.save(uid, st)
            admin_log(f"[auth] new player {uid} (accountType={acct_type})")
        playerdb.bind_login(login_id, uid)
        return uid
    return playerdb.active()

def r_login(body, st):
    # All date-ish fields must be non-null parseable strings: HandleAuthResponse
    # does DateTime.Parse on expiredAt / serverTime / blockedUntilAt -> null throws
    # ArgumentNullException.
    # str(): the id is a bearer credential the client picks, and it is hashed - a
    # numeric one used to raise AttributeError on .encode() and 500 the whole login.
    login_id = str(CURRENT_LOGIN_ID.get() or body.get("id") or "")
    # Constants.AccountType: 0 Test, 1 Google, 2 GameCenter, 3 AppleID, 4 Guest.
    # Only /auth/register carries it; None on the token-refresh paths.
    acct_type = body_int(body["type"], None) if isinstance(body, dict) and "type" in body else None
    # No bind_login() here: in single-player mode _uid_for_login falls back to the
    # ACTIVE player, and recording that as "account X owns save Y" would pin every
    # account that ever logged in to it - permanently, so a later switch to
    # multiplayer would still hand them all the same save. Only the multiplayer
    # branch, which actually owns the account, writes that mapping.
    uid = _uid_for_login(login_id, body.get("token"), acct_type)
    if uid is None:
        # No save and none may be created (cap or rate limit). Nothing to bind a
        # session to; the alternative was logging the caller into someone else.
        return {"success": False, "msg": "cannot create an account right now"}
    # Remember which social login this account used, so PlayerDataResponseModel
    # reports the right accountType (Google vs Guest) and the client shows it.
    if acct_type is not None:
        acct = playerdb.load(uid)
        if acct is not None and acct.get("accountType") != acct_type:
            acct["accountType"] = acct_type
            playerdb.save(uid, acct)
    token = "DEV." + secrets.token_hex(16)
    playerdb.bind_session(token, uid)   # every later request identifies via this
    CURRENT_UID.set(uid)                # rest of THIS request is already this player
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
    uid = _uid_for_login(str(login_id or ""), None, acct_type)
    token = "DEV." + secrets.token_hex(16)
    playerdb.bind_session(token, uid)
    admin_log(f"[glogin] minted token for uid={uid}")
    return token



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

def r_building_save(body, st):
    preset = body_int(body.get("preset"), 0, lo=0, hi=BUILDING_PRESETS - 1)
    levels = body.get("levels", [0] * 6)
    presets = _get_building_data(st)
    while len(presets) <= preset:
        presets.append({"buildingLevels": [0]*6})
    presets[preset]["buildingLevels"] = levels
    st["buildingPresets"] = presets
    save_state(st)
    return {"buildingPoint": st.get("buildingPoints", 25), "buildingData": presets}

def r_building_reset_point(body, st):
    preset = body_int(body.get("preset"), 0, lo=0, hi=BUILDING_PRESETS - 1)
    presets = _get_building_data(st)
    while len(presets) <= preset:
        presets.append({"buildingLevels": [0]*6})
    presets[preset]["buildingLevels"] = [0] * 6
    st["buildingPresets"] = presets
    save_state(st)
    return {"buildingPoint": st.get("buildingPoints", 25), "buildingData": presets}


def r_player_rename(body, st):
    """POST /player/rename - RestAPI.ChangeNickname.

    Request is ChangeNicknameRequestModel{userName, castleName, kingPostfix, castlePostfix},
    response is ChangeNicknameResponseModel{playerCash} (path confirmed from the literal at
    .data slot 0x67fe0f0 in the v171 lib). This used to be a lambda that echoed
    {"name": ...} back: wrong field for the model, and it never wrote state, so the popup
    closed and the next /player served the old name. Rename stays free here - the client
    only charges cash when hasFreeRename is false, and we keep it true.
    """
    name = body_str(body.get("userName")) or body_str(body.get("name"))
    castle = body_str(body.get("castleName"))
    if name:
        st["name"] = name
    if castle:
        st["castleName"] = castle
    st["kingPostfix"] = body_int(body.get("kingPostfix"), st.get("kingPostfix", 0))
    st["castlePostfix"] = body_int(body.get("castlePostfix"), st.get("castlePostfix", 0))
    save_state(st)
    # The route is mapped to PlayerDataResponseModel, so `playerCash` alone left every
    # other player field at its zero default - if the client rebinds the player from
    # this response it reads a level-0, no-gold account. Answer with the real player
    # and keep `playerCash` alongside it.
    return {**r_player({}, st), "playerCash": st.get("cash", 0)}



# ProfilePanel.ReloadChallenge indexes invasion/difficulty records per
# unlockedDifficulty tier (up to 15) -> a shorter list throws
# IndexOutOfRangeException, aborting Reload() before name/avatar/clan/date ever
# get set (root cause of the whole profile-popup bug batch).
from config import PLAYER_DEFAULTS as _PC
_INVASION_THEMES = [t for a, b in _PC["invasionThemeRanges"] for t in range(a, b)]
# Theme 16 (Invasion I-1) requires ReqPrevThemeDifficulty=3 on the PREVIOUS theme (15,
# the last Story chapter) - ThemeSelectPanel.IsThemeLocked looks this up by ID-1 in the
# same invasionDifficultyRecords dictionary (no separate "story difficulty" field exists
# on PlayerDataResponseModel). Without a record for 15, the lookup returns 0 < 3 -> locked,
# and OnSelectTheme silently falls back to theme=1 instead of refusing selection.
_PREREQ_THEMES = [15]

def r_player(body, st):
    # Field set matches PlayerDataResponseModel exactly (dump.cs @0x18-0xC4) - any
    # extra key here is dead weight the client silently ignores (Newtonsoft default),
    # and any missing real field risks an NRE downstream. Ghidra-verified 2026-07-03:
    # buildingPoint/altarPoints/altarLevels/difficultyRecords/season/semiSeason/
    # pvpEnabled/seasonUntilAtDates/nextSeasonStartAtDates/score/tier/rank/bestScore/
    # bestTier/loseCount/theme/deckRecordDifficulty do NOT exist on this model - they
    # were dead fields from an earlier draft. Altar/building data belongs on
    # BuildingResponseModel (/player/building*), not here.
    d = _PC["defaults"]
    ld = _PC["listDefaults"]
    unlocked = _PC["invasionUnlockedDifficulty"]
    return {
        "accountId": st.get("accountId", d["accountId"]),
        "name": st.get("name", d["name"]), "castleName": st.get("castleName", d["castleName"]),
        "kingPostfix": st.get("kingPostfix", 0), "castlePostfix": st.get("castlePostfix", 0),
        "uid": st.get("uid", "dev-0001"), "accountType": st.get("accountType", d["accountType"]),
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
            # .First(theme).difficulty) - must be `unlocked`, not the loop var, or the
            # first per-theme record reports cleared=1 and content gates (accessory@6,
            # riftweapon@11) stay locked. The d-loop only pads list length for
            # ProfilePanel.ReloadChallenge's per-tier indexing.
            {"theme": i, "difficulty": unlocked, "unlockedDifficulty": unlocked}
            for i in _INVASION_THEMES + _PREREQ_THEMES
            for d in range(1, unlocked + 1)
        ],
        "eventModeRecord": st.get("eventModeRecord", [ld["eventModeRecordValue"]] * ld["eventModeRecordCount"]),
        "rogueLikeBuildingChallengeLevelRecord": st.get(
            "rogueLikeBuildingChallengeLevelRecord",
            [ld["rogueLikeBuildingChallengeLevelRecordValue"]] * ld["rogueLikeBuildingChallengeLevelRecordCount"]),
        "rogueLikeGameIndex": st.get("rogueLikeGameIndex", d["rogueLikeGameIndex"]),
        "dimensionRiftGameIndex": st.get("dimensionRiftGameIndex", d["dimensionRiftGameIndex"]),
        "currentRanking": st.get("currentRanking", [ld["currentRankingValue"]] * ld["currentRankingCount"]),
        "currentHardRanking": st.get("currentHardRanking", [ld["currentHardRankingValue"]] * ld["currentHardRankingCount"]),
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
        ],
        "attendedCustomEvents": st.get("attendedCustomEvents", []),
        "customEventDatas": st.get("customEventDatas", []),
        "eventMissionData": st.get("eventMissionData", []),
        "eventData": st.get("eventData", []),
        "rogueLikeBoughtDlcs": st.get("rogueLikeBoughtDlcs", []),
        "accountCreatedAt": st.get("accountCreatedAt", now_iso(0)),
    }

def r_game_start(body, st):
    print(f"  [GAME/START] body={body}")
    gc = RCFG["gameStart"]
    theme = body_int(body.get("theme"), 1, lo=0)
    stage = body_int(body.get("stage"), 1, lo=0)
    heart_cost = gc["heartCostLow"] if theme <= gc["heartCostThemeThreshold"] else gc["heartCostHigh"]
    heart = max(0, st.get("heart", 999) - heart_cost)
    st["heart"] = heart
    gid = secrets.token_hex(8)
    _game_store[gid] = {"theme": theme, "stage": stage, "heartCost": heart_cost}
    save_state(st)
    # The client loops over rankingStageUnits up to 6 times (Deck size).
    # Provide 6 valid units (10260) spread out to avoid physics explosions.
    ranking_stage_units = [{"x": i, "y": i, "unitId": 10260, "level": 1} for i in range(6)]
    return {
        "heart": heart,
        "lastHeartTime": st.get("lastHeartTime", now_iso(0)),
        "buildingData": _get_building_data(st),
        "cards": cards_list(st),
        "gameId": gid,
        "eventFlag": st.get("eventFlag", 0),
        "rankingStageUnits": ranking_stage_units,
    }

def r_game_complete(body, st):
    gc = RCFG["gameComplete"]
    babel_rewards = []
    gid = body_str(body.get("gameId"))
    win = bool(body.get("win", False))
    theme = body_int(body.get("theme"), 1, lo=0)
    stage = body_int(body.get("stage"), 1, lo=0)
    _game_store.pop(gid, None)
    add_gold = gc["baseGold"] + theme * gc["goldPerTheme"] + (gc["winBonusGold"] if win else 0)
    add_exp = gc["baseExp"] + theme * gc["expPerTheme"]
    st["gold"] += add_gold
    st["exp"] += add_exp
    if win:
        st["winCount"] = st.get("winCount", 0) + 1
        if theme > st.get("bestClearedTheme", 0):
            st["bestClearedTheme"] = theme
            st["bestClearedStage"] = stage
        elif theme == st.get("bestClearedTheme", 0) and stage > st.get("bestClearedStage", 0):
            st["bestClearedStage"] = stage
    st["playedCount"] = st.get("playedCount", 0) + 1
    bump(st, "playGame")
    bump(st, "playTheme", sub=theme)
    if win:
        bump(st, "clearGame")
        bump(st, "clearTheme", sub=theme)
        # Challenge runs report their difficulty alongside the theme; without this the
        # challenge reward track can never advance past zero. Themes below 4000 are
        # the ordinary story/invasion ones and carry no challenge difficulty.
        if theme >= _CHALLENGE_THEME_MIN and body.get("difficulty"):
            cs = _challenge_state(st)
            cs["bestDifficulty"] = max(cs["bestDifficulty"],
                                       body_int(body.get("difficulty"), 0))
            cs["clearedBattles"] = max(cs["clearedBattles"], int(stage) + 1)
        # A Babel floor pays its own reward on first clear; nothing else advances the
        # tower, so without this hook every tower stays on floor 0 forever.
        babel_rewards = _babel_clear(st, theme, int(stage))
    if st.get("exp", 0) >= gc["expPerLevel"]:
        st["level"] += st["exp"] // gc["expPerLevel"]
        st["exp"] = st["exp"] % gc["expPerLevel"]
    save_state(st)
    out = {"addGold": add_gold, "addExp": add_exp,
           "playerGold": st["gold"], "playerLevel": st["level"], "playerExp": st["exp"]}
    out.update(gc["fixed"])
    if babel_rewards:
        out["rewardListData"] = _reward_list_data(babel_rewards)
    return out

def r_card_all(body, st):
    return {"cards": cards_list(st)}

def r_card_upgrade(body, st):
    unit_id = body.get("unitId", 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["level"] += 1
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": 1, "exp": 0, "potentialTier": 0,
                        "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
                        "randomSkinApply": False, "soul": 0})
    player_gold = st.get("gold", 0)
    player_cash = st.get("cash", 0)
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": c.get("potentialTier", 0),
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": player_gold, "playerCash": player_cash,
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": c.get("potentialTier", 0),
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }

def r_card_fast_upgrade(body, st):
    unit_id = body.get("unitId", 0)
    target_level = body.get("targetLevel", 1)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["level"] = target_level
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": target_level, "exp": 0, "potentialTier": 0,
                        "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
                        "randomSkinApply": False, "soul": 0})
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": c.get("potentialTier", 0),
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": c.get("potentialTier", 0),
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }

def r_card_use_candy(body, st):
    unit_id = body.get("unitId", 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["level"] += 1
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": 1})
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": c.get("potentialTier", 0),
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": c.get("potentialTier", 0),
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
    return {**card_to_dict(c),
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
    return {
        "unitId": c["unitId"], "level": c.get("level", 1), "exp": c.get("exp", 0),
        "potentialTier": c.get("potentialTier", 0),
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c.get("level", 1), "originPotentialTier": c.get("potentialTier", 0),
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
    decks = st.get("decks", DEFAULT_DECKS)
    deck_infos = [{"deck": d["deck"], "potential": d.get("potential", []),
                   "firstComerIndex": d.get("firstComerIndex", 0)} for d in decks]
    return {"deckInfos": deck_infos, "defaultPotentialInfo": st.get("defaultPotential", {"unit": [], "potential": []})}

def r_deck_set(body, st):
    # `or []` rather than a get() default: the client sends the key with a null
    # value when a preset is empty, and a default only fires on a missing key.
    preset_idx = body_int(body.get("presetIdx"), 0, lo=0, hi=DECK_PRESETS - 1)
    decks = st.setdefault("decks", list(DEFAULT_DECKS))
    admin_log(f"[DECK/SET] preset={preset_idx} body_keys={list(body.keys())}")
    deck, potential = _pad_deck(body_list(body.get("deck")),
                                body_list(body.get("potential")))
    first_comer = body_int(body.get("firstComerIndex"), 0, lo=0)
    while len(decks) <= preset_idx:
        decks.append({"deck": [0] * DECK_SLOTS, "potential": [0] * DECK_SLOTS, "firstComerIndex": 0})
    decks[preset_idx] = {"deck": deck, "potential": potential, "firstComerIndex": first_comer}
    st["decks"] = decks
    save_state(st)
    return {"deckInfos": [{"deck": d["deck"], "potential": d.get("potential", []),
                           "firstComerIndex": d.get("firstComerIndex", 0)} for d in decks],
            "defaultPotentialInfo": st.get("defaultPotential", {"unit": [], "potential": []})}

def r_deck_set_potential(body, st):
    preset_idx = body_int(body.get("presetIdx"), 0, lo=0, hi=DECK_PRESETS - 1)
    idx = body_int(body.get("idx"), 0, lo=0, hi=DECK_SLOTS - 1)
    unit_id = body_int(body.get("unitId"), 0)
    potential = body_int(body.get("potential"), 0)
    decks = st.setdefault("decks", list(DEFAULT_DECKS))
    admin_log(f"[DECK/SET-POTENTIAL] preset={preset_idx} idx={idx} unitId={unit_id} potential={potential}")
    while len(decks) <= preset_idx:
        decks.append({"deck": [0] * DECK_SLOTS, "potential": [0] * DECK_SLOTS, "firstComerIndex": 0})
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

def r_player_inventory(body, st):
    inv = st.get("inventory", {"itemIds": [], "counts": []})
    return {"itemIds": inv.get("itemIds", []), "counts": inv.get("counts", [])}

def _inventory(st):
    return st.setdefault("inventory", {"itemIds": [], "counts": []})

def _inventory_models(st):
    """The inventory as List<InventoryItem> ({id, count}) - the shape the use-item
    responses return, as opposed to the parallel-array shape /player/getInventory uses."""
    inv = _inventory(st)
    return [{"id": i, "count": c}
            for i, c in zip(inv.get("itemIds", []), inv.get("counts", []))]

def _item_count(st, item_id):
    inv = _inventory(st)
    ids = inv.get("itemIds", [])
    return inv.get("counts", [])[ids.index(item_id)] if item_id in ids else 0

def _take_item(st, item_id, n=1):
    """Spend n of an item. Returns how many were actually spent (0 if the player has none).

    The count is clamped rather than refused: the client sends what its own cached
    inventory believes, and a stale cache should not brick the item behind an error."""
    inv = _inventory(st)
    ids, cnts = inv.setdefault("itemIds", []), inv.setdefault("counts", [])
    if item_id not in ids:
        return 0
    i = ids.index(item_id)
    n = max(0, min(n, cnts[i]))
    cnts[i] -= n
    if cnts[i] <= 0:
        ids.pop(i)
        cnts.pop(i)
    return n

def _next_accessory_id(st):
    return max((a.get("id", 0) for a in get_st_accessories(st)), default=0) + 1

def _open_reward_box(st, item_id, select_idx=None, times=1):
    """Open `times` copies of a reward box item, granting everything it yields.

    Returns the flat reward list for the client's popup. Accessories are appended to
    the player's accessory list here (they are fully specified, unlike artifacts, so
    they do not trip a client panel invariant); treasures stay display-only."""
    spent = _take_item(st, item_id, times)
    rewards = []
    for _ in range(spent):
        got, accs = rewardbox.open_box(item_id, select_idx, XML_DIR,
                                       next_id=_next_accessory_id(st), now=now_iso(0))
        if accs:
            get_st_accessories(st).extend(accs)
        for r in got:
            rt = r["type"]
            if rt in ("Key", "CardOrSoul"):
                # Same tags Missions.xml uses, so share the resolver: a Key names a
                # ShopItem whose <KeyItem> is the real inventory row, and a CardOrSoul
                # converts to soul when the hero is already owned. It grants and returns
                # the reward already in RewardResponseData shape.
                rewards.append(_grant_mission_reward(st, r))
                continue
            if rt not in ("Accessory", "Treasure"):
                _grant_reward(st, rt, r["id"], r["count"])
            rewards.append(r)
    return rewards

# RewardResponseData.type is matched against a fixed vocabulary of strings - the same
# ones the master data uses (InventoryItem / Key / UnitSoulItem / CardSoul / Card /
# Gold / Cash / Heart / Artifact / Treasure / Skin ...), which the client compares in
# ResourceInventoryItem.GetByRewardTypeAndID. **There is no "Item"**: an unmatched type
# resolves to no ResourceInventoryItem, and the reward then renders with a wrong icon
# and a nonsense count in the results popup (what "Temple of Challenge Reward Chest
# gives x999 of the wrong thing" was). The server's own vocabulary is shorter and used
# by _grant_reward; translate at the wire boundary only, so state keys never move.
_WIRE_TYPE = {"Item": "InventoryItem", "Unit": "Card", "UnitSoul": "CardSoul"}

def _wire_rewards(rewards):
    return [{**r, "type": _WIRE_TYPE.get(r.get("type"), r.get("type"))} for r in rewards]

def _reward_list_data(rewards):
    return {"rewardList": _wire_rewards(rewards), "artifactResult": None,
            "treasureResult": None, "accessoryResult": None}

def r_use_inventory(body, st):
    """Consume a plain inventory item.

    InventoryItems.xml carries no effect payload (only tooltip/category metadata), and
    the client applies the visible effect itself off that metadata, so the server's job
    is to spend the item and hand back the authoritative inventory.
    ponytail: no per-item effect table; add one if an item turns out to need server state."""
    item_id = body.get("itemID") or body.get("itemId") or 0
    _take_item(st, item_id, body_int(body.get("count"), 1, lo=1))
    save_state(st)
    return {"playerHeart": st.get("heart", 0), "eventFlag": 0,
            "inventoryItems": _inventory_models(st)}

def r_use_reward_box(body, st):
    item_id = body.get("itemId") or body.get("itemID") or 0
    rewards = _open_reward_box(st, item_id, body.get("selectIdx"),
                               body_int(body.get("count"), 1, lo=1))
    save_state(st)
    return {"rewardList": _reward_list_data(rewards),
            "addedRewardList": _reward_list_data([]),
            "boxRewardInventory": {"id": item_id, "count": _item_count(st, item_id)}}

def r_use_skin_box(body, st):
    """Skin boxes name their own prize: the client sends the skin the player picked."""
    item_id = body.get("itemId") or body.get("itemID") or 0
    skin_id = body.get("skinId") or 0
    spent = _take_item(st, item_id, 1)
    if spent and skin_id:
        unit = str(skin_id // 1000)
        card = st.setdefault("cards", {}).get(unit)
        if card is not None and skin_id not in card.setdefault("skins", []):
            card["skins"].append(skin_id)
    save_state(st)
    return {"rewardList": _reward_list_data(
                [{"type": "Skin", "id": skin_id, "count": 1}] if spent else []),
            "skin": skin_id,
            "boxRewardInventory": {"id": item_id, "count": _item_count(st, item_id)}}

def _invasion_rewards():
    """InvasionRewards.xml as {(theme, difficulty): {"Rewards": [...], "PassRewards": [...]}}.

    The entry id encodes both: 101 is theme 1 difficulty 1, 6905 is theme 69
    difficulty 5. Each section lists tag-named rewards (Cash, Key, InventoryItem,
    Artifact, ...) with ID/Count attributes."""
    import xml.etree.ElementTree as _ET
    root = _ET.parse(XML_DIR / "InvasionRewards.xml").getroot()
    out = {}
    for e in root:
        if not e.get("ID"):
            continue
        rid = int(e.get("ID"))
        theme, diff = divmod(rid, 100)
        sections = {}
        for sec in ("Rewards", "PassRewards"):
            node = e.find(sec)
            sections[sec] = [] if node is None else [
                {"type": t.tag, "id": int(t.get("ID", 0)), "count": int(t.get("Count", 1))}
                for t in node]
        out[(theme, diff)] = sections
    return out

INVASION_REWARDS = _invasion_rewards()
admin_log(f"[invasion] {len(INVASION_REWARDS)} theme/difficulty reward rows")

def _invasion_claimed(st):
    """theme -> bitmask of claimed difficulties, matching the client's `rewardState`."""
    return st.setdefault("invasionRewardState", {})

def _invasion_grant(st, rewards):
    """Apply one invasion reward row. Shares the mission reward mapping - the tag
    names are the same vocabulary (Key names a ShopItem, Artifact is display-only)."""
    out = []
    for r in rewards:
        t = r["type"]
        if t == "InventoryItem":
            _grant_reward(st, "Item", r["id"], r["count"])
            out.append({"type": "Item", "id": r["id"], "count": r["count"]})
        elif t in ("Cash", "Gold", "Heart"):
            _grant_reward(st, t, 0, r["count"])
            out.append({"type": t, "id": 0, "count": r["count"]})
        elif t == "Card":
            out.append(_grant_mission_reward(st, {"type": "CardOrSoul", **r}))
        elif t == "Key":
            out.append(_grant_mission_reward(st, {"type": "Key", **r}))
        else:
            # Artifact / Treasure_Special / NewUnitGachaItem: shown, not written into
            # state, per the existing _grant_reward policy.
            out.append({"type": t, "id": r["id"], "count": r["count"]})
    return out

def _invasion_claim(st, theme, difficulty, with_pass):
    """Claim one theme/difficulty. Returns the reward list; empty if not eligible."""
    unlocked = RCFG["player"]["invasionUnlockedDifficulty"]
    if not (1 <= difficulty <= unlocked):
        return []
    row = INVASION_REWARDS.get((theme, difficulty))
    if row is None:
        return []
    mask = _invasion_claimed(st).get(str(theme), 0)
    bit = 1 << (difficulty - 1)
    if mask & bit:
        return []
    rewards = _invasion_grant(st, row["Rewards"])
    if with_pass:
        rewards += _invasion_grant(st, row["PassRewards"])
    _invasion_claimed(st)[str(theme)] = mask | bit
    return rewards

def r_invasion_reward(body, st):
    """GET lists what is claimable, POST claims one theme/difficulty.

    Same GET/POST split as /shop and /accessory: a request naming a theme is a claim,
    a bare one is a listing. ReceiveInvasionRewardRequestModel is {theme, difficulty,
    pass}, so `theme` is the discriminator the client already sends."""
    if not body.get("theme"):
        return {"rewardDatas": [
            {"theme": t, "difficulty": d,
             "rewards": row["Rewards"], "passRewards": row["PassRewards"],
             "received": bool(_invasion_claimed(st).get(str(t), 0) & (1 << (d - 1)))}
            for (t, d), row in sorted(INVASION_REWARDS.items())]}
    theme = body_int(body.get("theme"), 0)
    rewards = _invasion_claim(st, theme, body_int(body.get("difficulty"), 1),
                              bool(body.get("pass")))
    save_state(st)
    admin_log(f"[invasion] theme {theme} d{body.get('difficulty')} -> {len(rewards)} rewards")
    return {"rewardListData": _reward_list_data(rewards),
            "rewardState": _invasion_claimed(st).get(str(theme), 0)}

def r_invasion_reward_all(body, st):
    """Claim every unclaimed, unlocked difficulty across every theme."""
    with_pass = bool(body.get("pass"))
    rewards = []
    for theme, diff in sorted(INVASION_REWARDS):
        rewards += _invasion_claim(st, theme, diff, with_pass)
    save_state(st)
    admin_log(f"[invasion] receive-all -> {len(rewards)} rewards")
    return {"rewardListData": _reward_list_data(rewards), "rewardState": 0}

# Challenge/roguelike themes start at 4000 (the Season 71 Story-Challenge boss 30000000
# sits on theme 4100); the story and invasion themes are all below it.
_CHALLENGE_THEME_MIN = 4000

def _challenge_state(st):
    st.setdefault("challenge", {"bestDifficulty": 0, "clearedBattles": 0,
                                "claimed": [], "dailyClaimedOn": ""})
    return st["challenge"]

def r_challenge_info(body, st):
    cs = _challenge_state(st)
    entries = challenge.track(xml_dir=XML_DIR)
    return {"bestClearedDifficulty": cs["bestDifficulty"],
            "unlockedDifficulty": challenge.unlocked_difficulty(xml_dir=XML_DIR),
            # Parallel to challenge.track()'s document order: 0 = not earned,
            # 1 = earned but unclaimed, 2 = claimed. Re-ordering the track would
            # silently misalign every index the client sends back.
            "rewardStates": [
                2 if i in cs["claimed"] else
                1 if challenge.earned(e, cs["bestDifficulty"], cs["clearedBattles"]) else 0
                for i, e in enumerate(entries)],
            "rewardResponse": None, "seasonEnabled": True,
            "startAt": now_iso(-30), "endAt": now_iso(30)}

def _challenge_grant(st, rewards):
    """Challenge rewards reuse the mission vocabulary, so Key still resolves through
    the ShopItem it names instead of landing in the inventory as item 0."""
    return [_grant_mission_reward(st, r) for r in rewards]

def r_challenge_reward(body, st):
    """Claim one track entry, or every earned one when no index is given."""
    cs = _challenge_state(st)
    entries = challenge.track(xml_dir=XML_DIR)
    idx = body.get("index") if body.get("index") is not None else body.get("rewardIdx")
    want = [body_int(idx, -1)] if idx is not None else range(len(entries))
    rewards = []
    for i in want:
        if not (0 <= i < len(entries)) or i in cs["claimed"]:
            continue
        if not challenge.earned(entries[i], cs["bestDifficulty"], cs["clearedBattles"]):
            continue
        rewards += _challenge_grant(st, entries[i]["rewards"])
        cs["claimed"].append(i)
    cs["claimed"].sort()
    save_state(st)
    admin_log(f"[challenge] claimed {len(rewards)} rewards, track {len(cs['claimed'])}/{len(entries)}")
    out = r_challenge_info(body, st)
    out["rewardResponse"] = _reward_list_data(rewards)
    return out

def r_challenge_daily(body, st):
    """One claim per UTC day, paying the tier for the best difficulty reached."""
    cs = _challenge_state(st)
    today = now_iso(0)[:10]
    if cs.get("dailyClaimedOn") == today:
        out = r_challenge_info(body, st)
        out["rewardResponse"] = _reward_list_data([])
        return out
    tiers = challenge.daily_track(xml_dir=XML_DIR)
    best = cs["bestDifficulty"]
    tier = max((d for d in tiers if d <= best), default=None)
    rewards = _challenge_grant(st, tiers[tier]) if tier is not None else []
    if rewards:
        cs["dailyClaimedOn"] = today
    save_state(st)
    admin_log(f"[challenge] daily tier {tier} -> {len(rewards)} rewards")
    out = r_challenge_info(body, st)
    out["rewardResponse"] = _reward_list_data(rewards)
    return out

def counters(st):
    """Server-side progress tallies for the mission conditions this server can see.

    Only the routes below write here, so a counter can never advance for something
    that did not actually go through the server - see missions.py on why a mission it
    cannot observe stays unclaimable rather than being marked complete."""
    return st.setdefault("counters", {})

def bump(st, key, n=1, sub=None):
    c = counters(st)
    if sub is None:
        c[key] = c.get(key, 0) + n
    else:
        d = c.setdefault(key, {})
        d[str(sub)] = d.get(str(sub), 0) + n

def _claimed_missions(st):
    return set(st.setdefault("claimedMissions", []))

# Routes whose mere occurrence is a mission condition. Kept as a table applied in
# respond() rather than an increment inside each handler, because several of these
# paths share one handler (every /artifact/* mutation returns r_artifact_result), so
# per-handler bumps could not tell them apart.
_PATH_COUNTERS = {
    "/artifact/crafting": "artifactCraft",
    "/artifact/merge": "artifactMerge",
    "/artifact/dismantle": "artifactDismantle",
    "/artifact/polish": "artifactPolish",
    "/artifact/set-reroll": "artifactReforge",
    "/artifact/smart-reroll": "artifactReforge",
    "/artifact/gacha": "artifactGacha",
    "/accessory/dismantle": "accessoryDismantle",
    "/accessory/add-exp": "accessoryLevelUp",
    "/player/heart/recover": "chargeHeart",
    "/pvp/matching": "playArena",
    "/colosseum": "playArena",
    "/clan/requestSupport": "clanSupport",
    "/clan/support": "clanSupport",
}

def r_mission(body, st):
    return {"missions": missions.listing(st, counters(st), _claimed_missions(st),
                                         now_iso(0), XML_DIR),
            "missionGoal": st.get("missionGoal", 0),
            "missionKeyStack": st.get("missionKeyStack", 0)}

def _grant_mission_reward(st, r):
    """Apply one Missions.xml reward. Returns it in RewardResponseData shape.

    A `Key` reward names a ShopItem: normally its <KeyItem> inventory row, but the
    artifact boxes have no KeyItem and are counted in artifactBoxKey by box index
    instead, so those go to a different store entirely."""
    rt, rid, amt = r["type"], r["id"], r["count"]
    if rt == "Key":
        item = missions.key_item_for(rid, XML_DIR)
        if item:
            _grant_reward(st, "Item", item, amt)
            return {"type": "Item", "id": item, "count": amt}
        box = missions.artifact_box_for(rid, XML_DIR)
        if box is not None:
            keys = st.setdefault("artifactBoxKey", [0, 0, 0, 0])
            while len(keys) <= box:
                keys.append(0)
            keys[box] += amt
            return {"type": "ArtifactBoxKey", "id": box, "count": amt}
        return {"type": "Key", "id": rid, "count": amt}
    if rt == "CardOrSoul":
        rt = "UnitSoul" if str(rid) in st.get("cards", {}) else "Unit"
    if rt == "CardExp":
        card = st.setdefault("cards", {}).get(str(rid))
        if card is not None:
            card["exp"] = card.get("exp", 0) + amt
        return {"type": "CardExp", "id": rid, "count": amt}
    if rt == "FixedAccessory":
        acc = rewardbox.make_fixed_accessory(rid, _next_accessory_id(st), XML_DIR, now_iso(0))
        if acc:
            get_st_accessories(st).append(acc)
            return {"type": "Accessory", "id": acc["id"], "count": 1}
        return {"type": "FixedAccessory", "id": rid, "count": amt}
    if rt in ("Gold", "Cash", "Heart", "Item", "Unit", "UnitSoul"):
        _grant_reward(st, rt, rid, amt)
    return {"type": rt, "id": rid, "count": amt}

def _claim_missions(st, ids):
    """Claim every cleared, unclaimed mission in `ids`. Returns the reward list."""
    claimed = _claimed_missions(st)
    catalog = missions.load(XML_DIR)
    out = []
    # Coerced here, not in the caller: the id list arrives straight off the request
    # and every claim route funnels through this loop.
    for mid in body_list(ids, int):
        m = catalog.get(mid)
        if m is None or mid in claimed:
            continue
        if missions.progress(m, st, counters(st)) < missions.goal_value(m):
            continue
        for r in missions.rewards_of(m):
            out.append(_grant_mission_reward(st, r))
        claimed.add(mid)
        bump(st, "missionClear")
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
            "rewardListResponseData": _reward_list_data(rewards)}

def r_event_cache(body, st):
    return {"events": []}


ALL_ARTIFACT_IDS, ARTIFACT_LEVELS = _all_artifact_ids()
ALL_TREASURE_IDS = _all_treasure_ids()
ALL_RIFT_WEAPON_IDS = _all_rift_weapon_ids()



# Ghidra ROOT CAUSE (2026-07-02, ResourceArtifactOption.GetValue crash):
# ArtifactOptionUI.Init's loop gate is `uVar8 < targets.Count` (top-level
# ArtifactOptions.targets, NOT types/lvs). Only when the gate is open does it call
# GetValue(types[i], lvs[i], ...) which does a Dictionary["AtkSpeedPer"] style
# lookup - "None" is never a registered key, so ANY slot reached with type="None"
# throws KeyNotFoundException. Fix: targets.Count must equal opt_count exactly, so
# the loop's else/hide branch (which never touches types/lvs) handles slots
# opt_count..3 instead of trying to look up "None". types_list/lvs_list stay
# padded to optionSlots (loop only ever reads indices < opt_count from them, so
# the tail values are never touched, but keep them present per the JSON schema).
#
# positionIcons (icon highlighting) separately requires: idx values 1-based
# (FUN_02e91408 = List<int>.IndexOf), and BOTH idx (nested struct list) and lvs
# (parallel list) must stay UNIFORM in length/value across all sent slots or the
# client's JSON parser corrupts subsequent fields (live-verified both ways).
# idx > 1 element still crashes for unknown reasons - capped at safePositions.
def make_artifact(i, art_id):
    t = ITEM_TEMPLATES["artifact"]
    level = ARTIFACT_LEVELS.get(art_id, "Normal")
    opt_count = t["optCountByLevel"].get(level, 1)
    types_pool = t["typesPool"]
    max_roll_lvs = t["maxRollLvs"]
    safe_positions = t["safePositions"]

    opt_data = []
    types_list = []
    lvs_list = []
    targets_list = []
    locks = []

    for idx in range(opt_count):
        ty = types_pool[idx % len(types_pool)]
        opt_data.append({"targets": safe_positions, "type": ty, "value": 24, "level": max_roll_lvs})
        types_list.append(ty)
        targets_list.append({"idx": safe_positions})
        lvs_list.append(max_roll_lvs)
        locks.append(False)

    for idx in range(opt_count, 4):
        opt_data.append({"targets": safe_positions, "type": "None", "value": 0, "level": 0})
        types_list.append("None")
        lvs_list.append(0)
        locks.append(False)

    return {
        "id": i,
        "artifactId": art_id,
        "count": t["count"],
        "polishPoint": t["polishPoint"],
        "data": {"options": opt_data},
        "options": {
            "targets": targets_list,
            "types": types_list,
            "lvs": lvs_list
        },
        "optionLock": locks,
        "customType": t["customType"],
        "createdAt": now_iso()
    }

def make_accessory(i, unit_id=0):
    t = ITEM_TEMPLATES["accessory"]
    return {
        "id": i, "accountId": t["accountId"], "unitId": unit_id, "slot": t["slot"],
        "type": (i % t["typeCount"]) + 1,
        "rarity": t["rarity"], "level": t["level"], "exp": t["exp"], "synergy": t["synergy"], "state": t["state"],
        "data": t["data"], "subStats": t["subStats"], "subStatScores": t["subStatScores"],
        "coolTimeEndAt": t["coolTimeEndAt"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
        "usedThemeList": t["usedThemeList"],
        "isEarlyAccessModeTestAccessory": t["isEarlyAccessModeTestAccessory"],
    }

def _acc_perscore(key):
    # AccessoryConstants.xml: BaseDef/BaseMDef roll in ValuePerScore=20 units; every other
    # substat uses ValueByScore=1. score = summed value / perScore.
    return 20.0 if key in ("BaseDef", "BaseMDef") else 1.0

def load_corruption_accessories():
    """Real 'Corruption II-1' first-clear reward accessories (FixedAccessoryPreset 2000-2003,
    one per type) - the exact items the client grants for clearing the stage that unlocks the
    accessory system. Mirrors AccessoryModel (data.mainStat + data.subStats[{key,value}]) so
    the client renders proper name/stats/grade instead of the 99.9% garbage a fabricated
    template with an invalid mainStat produced."""
    import xml.etree.ElementTree as ET
    root = ET.parse(XML_DIR / "FixedAccessoryPresets.xml").getroot()
    out, inst = [], 1
    for p in root.findall("FixedAccessoryPreset"):
        if p.get("ID", "") not in ("2000", "2001", "2002", "2003"):
            continue
        rolls = [(s.get("Key"), float(s.get("Value"))) for s in p.findall("./SubStats/SubStat")]
        fb = p.find("FixedBonusSubStat")
        if fb is not None:
            rolls.append((fb.get("Key"), float(fb.get("Value"))))
        scores = {}
        for k, v in rolls:
            scores[k] = scores.get(k, 0.0) + v / _acc_perscore(k)
        out.append({
            "id": inst, "accountId": 1, "unitId": 0, "slot": 0,
            "type": int(p.findtext("Type", "1")), "rarity": int(p.findtext("Rarity", "3")),
            "level": int(p.findtext("Level", "20")), "exp": 0,
            "synergy": int(p.findtext("Synergy", "0")), "state": 0,
            "data": {"mainStat": p.findtext("MainStat", "AtkPer"),
                     "subStats": [{"key": k, "value": v} for k, v in rolls]},
            "subStats": list(scores.keys()), "subStatScores": [round(s, 3) for s in scores.values()],
            "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
            "createdAt": now_iso(), "updatedAt": now_iso(),
            "usedThemeList": [], "isEarlyAccessModeTestAccessory": False,
        })
        inst += 1
    return out

def get_st_accessories(st):
    if "accessories" not in st:
        st["accessories"] = copy.deepcopy(DEFAULT_ACCESSORIES)
    return st["accessories"]

def r_accessory(body, st):
    accs = get_st_accessories(st)
    target_id = body.get("targetId", 0)
    unit_id = body.get("unitId", 0)
    if target_id and unit_id:
        for a in accs:
            if a["unitId"] == unit_id:
                a["unitId"] = 0
            if a["id"] == target_id:
                a["unitId"] = unit_id
        save_state(st)
    return {"accessories": accs, "presets": []}

def r_accessory_release(body, st):
    accs = get_st_accessories(st)
    target_id = body.get("targetId", 0)
    if target_id:
        for a in accs:
            if a["id"] == target_id:
                a["unitId"] = 0
        save_state(st)
    return {"accessories": accs, "presets": []}

def r_accessory_result(body, st):
    return {"accessories": get_st_accessories(st), "deletedAccessories": [], "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0), "inventories": [], "addedExpItems": 0}

def make_treasure(i, tr_id):
    t = ITEM_TEMPLATES["treasure"]
    return {
        "id": i, "treasureId": tr_id, "accountId": t["accountId"],
        "level": t["level"], "exp": t["exp"], "overcome": t["overcome"], "unitId": t["unitId"], "state": t["state"],
        "coolTimeEndAt": t["coolTimeEndAt"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
        "usedThemeList": t["usedThemeList"],
        "isEarlyAccessModeTestTreasure": t["isEarlyAccessModeTestTreasure"],
    }

def make_rift_weapon(i, rw_id):
    t = ITEM_TEMPLATES["riftWeapon"]
    return {
        "id": i, "weaponId": rw_id, "buildingIndexes": t["buildingIndexes"],
        "level": t["level"], "rarity": t["rarity"], "broken": t["broken"],
        "subStat": t["subStat"], "state": t["state"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
    }

RIFT_BUILDING_COUNT = _rift_building_count()
# CrystalRarity (ResourceRiftWeaponConstant.CrystalRarity): None=0, Common=1, UnCommon=2,
# Rare=3, Epic=4, Legendary=5. Rarity 0 names the crystal via the key
# `RiftCrystalNameKeyword_None`, which does not exist in any locale - the client then
# renders the raw key. Only 1-5 have a keyword (Faded/Ordinary/King/God/King God).
RIFT_CRYSTAL_RARITIES = {1: "Common", 2: "UnCommon", 3: "Rare", 4: "Epic", 5: "Legendary"}
# Altars cap at level 15 ("You have an Altar with more than 15 points" / the 16 entries
# of RiftWeaponConstants.xml BuildingOptionSlotLevelValue = levels 0..15).
RIFT_BUILDING_MAX_LEVEL = 15

def make_rift_crystal(i, rw_id, main_idx=None):
    t = ITEM_TEMPLATES["riftCrystal"]
    main_idx = t["mainBuildingIdx"] if main_idx is None else main_idx
    main_idx %= max(RIFT_BUILDING_COUNT, 1)
    level = min(int(t["mainBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL)
    other = min(int(t["otherBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL)
    # One level per altar, with the main altar strictly highest: GetMaxBuildingIdx
    # returns the FIRST maximum, so an all-equal list would name every crystal after
    # altar 0 regardless of mainBuildingIdx.
    levels = [other] * RIFT_BUILDING_COUNT
    levels[main_idx] = max(level, other + 1)
    rarity = int(t["rarity"])
    assert rarity in RIFT_CRYSTAL_RARITIES, (
        f"riftCrystal rarity {rarity} has no RiftCrystalNameKeyword_* string; "
        f"valid: {sorted(RIFT_CRYSTAL_RARITIES)}")
    return {
        "id": i, "weaponId": rw_id, "mainBuildingIdx": main_idx,
        "buildingLevels": levels, "rarity": rarity,
        "ceilCount": t["ceilCount"], "state": t["state"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
    }

def _repair_rift_crystals(crystals):
    """Upgrade crystals saved before the shape was understood. Returns True if anything
    changed, so the caller can persist.

    Two legacy defects, both of which the client renders rather than rejects:
      * rarity 0 (CrystalRarity.None) -> the name resolves `RiftCrystalNameKeyword_None`,
        a key that exists in no locale, so the panel shows the raw key;
      * buildingLevels shorter than the altar count -> GetMaxBuildingIdx can only ever
        return an index inside the short list, so every crystal named itself after
        altar 0 and the altars past the end contributed nothing.
    """
    t = ITEM_TEMPLATES["riftCrystal"]
    changed = False
    for c in crystals:
        if c.get("rarity") not in RIFT_CRYSTAL_RARITIES:
            c["rarity"] = int(t["rarity"])
            changed = True
        levels = c.get("buildingLevels") or []
        if len(levels) != RIFT_BUILDING_COUNT:
            main = int(c.get("mainBuildingIdx", 0)) % max(RIFT_BUILDING_COUNT, 1)
            other = min(int(t["otherBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL)
            # Keep whatever levels the save already had; only extend to full width.
            fixed = [min(int(v), RIFT_BUILDING_MAX_LEVEL) for v in levels[:RIFT_BUILDING_COUNT]]
            fixed += [other] * (RIFT_BUILDING_COUNT - len(fixed))
            fixed[main] = max(min(int(t["mainBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL), other + 1)
            c["buildingLevels"] = fixed
            c["mainBuildingIdx"] = main
            changed = True
    return changed

DEFAULT_ARTIFACTS = [make_artifact(i + 1, aid) for i, aid in enumerate(ALL_ARTIFACT_IDS)]
DEFAULT_TREASURES = [make_treasure(i + 1, tid) for i, tid in enumerate(ALL_TREASURE_IDS)]
DEFAULT_ACCESSORIES = load_corruption_accessories() or [make_accessory(i + 1) for i in range(ITEM_TEMPLATES["accessory"]["count"])]
DEFAULT_RIFT_WEAPONS = [make_rift_weapon(i + 1, rwid) for i, rwid in enumerate(ALL_RIFT_WEAPON_IDS)]
ARTIFACT_BY_ID = {a["id"]: a for a in DEFAULT_ARTIFACTS}

# ArtifactRequestModel.targetId = the equipped artifact's instance `id` (dump.cs
# ArtifactRequestModel @0x8 targetId, @0x1C index, @0x20 deckPreset).
# ArtifactResultResponseModel.equippedArtifacts = List<EquippedArtifactData>
# {deckPreset, index, artifact} (dump.cs @0x2C). Persisted server-side as
# {deckPreset, index, artifactId} in state and resolved to a full ArtifactModel
# at response time - storing the id (not the full model) means an equipped slot
# always reflects the artifact's current data if it's ever regenerated.
def _resolve_equipped_artifacts(st):
    out = []
    for e in st.get("equippedArtifacts", []):
        art = ARTIFACT_BY_ID.get(e.get("artifactId"))
        if art:
            out.append({"deckPreset": e.get("deckPreset", 0), "index": e.get("index", 0), "artifact": art})
    return out

def r_artifact_inventory(body, st):
    return {"artifacts": DEFAULT_ARTIFACTS, "dustCount": 99999,
            "equippedArtifacts": _resolve_equipped_artifacts(st), "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0)}

def r_artifact_equip(body, st):
    target_id = body_int(body.get("targetId"), 0)
    index = body_int(body.get("index"), 0)
    deck_preset = body_int(body.get("deckPreset"), 0)
    equipped = [e for e in st.get("equippedArtifacts", [])
                if not (e.get("deckPreset", 0) == deck_preset and e.get("index", 0) == index)]
    if target_id and target_id in ARTIFACT_BY_ID:
        equipped.append({"deckPreset": deck_preset, "index": index, "artifactId": target_id})
    st["equippedArtifacts"] = equipped
    save_state(st)
    return {"artifacts": DEFAULT_ARTIFACTS, "dustCount": 99999,
            "equippedArtifacts": _resolve_equipped_artifacts(st), "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "changeEquipped": True, "polishItemAdded": False,
            "results": []}

def r_artifact_result(body, st):
    return {"artifacts": DEFAULT_ARTIFACTS, "dustCount": 99999,
            "equippedArtifacts": _resolve_equipped_artifacts(st), "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "changeEquipped": False, "polishItemAdded": False,
            "results": DEFAULT_ARTIFACTS}

def get_st_treasures(st):
    if "treasures" not in st:
        st["treasures"] = copy.deepcopy(DEFAULT_TREASURES)
    return st["treasures"]

def r_treasure(body, st):
    tr = get_st_treasures(st)
    target_id = body.get("targetId", 0)
    unit_id = body.get("unitId", 0)
    if target_id and unit_id:
        for t in tr:
            if t["unitId"] == unit_id:
                t["unitId"] = 0
            if t["id"] == target_id:
                t["unitId"] = unit_id
        save_state(st)
    return {"treasures": tr, "treasureCapacity": 9999, "capacity": 9999, "maxCapacity": 9999, "maxTreasureCount": 9999, "deletedTreasures": [], "inventories": []}

def r_treasure_equip(body, st):
    return r_treasure(body, st)

def r_treasure_release(body, st):
    tr = get_st_treasures(st)
    inv_id = body.get("targetId")
    for t in tr:
        if t["id"] == inv_id:
            t["unitId"] = 0
    save_state(st)
    return r_treasure(body, st)

def r_treasure_add_exp(body, st):
    return {"treasures": get_st_treasures(st), "treasureCapacity": 9999, "capacity": 9999, "maxCapacity": 9999, "maxTreasureCount": 9999, "addExpItems": [], "deletedTreasures": [], "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0), "inventories": [], "addedExpItems": 0}

def r_rift_weapon(body, st):
    rift_crystals = st.setdefault("riftCrystals", [])
    if _repair_rift_crystals(rift_crystals):
        save_state(st)
    return {"riftWeapons": DEFAULT_RIFT_WEAPONS, "equippedWeapons": {}, "riftCrystals": rift_crystals, "deletedRiftWeapons": [], "deletedCrystals": [], "riftGauge": 0, "rewardListResponseData": None, "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0), "playerHeart": st.get("heart", 0), "upgradeState": 0, "equippedWeaponIds": []}

def r_pass(body, st):
    c = RCFG["pass"]
    out = {"seasonStartAtDate": now_iso(c["seasonStartDayOffset"]),
           "seasonUntilAtDate": now_iso(c["seasonUntilDayOffset"]),
           "nextSeasonStartAtDate": now_iso(c["nextSeasonStartDayOffset"])}
    out.update(c["fixed"])
    return out



from decoration import block as _deco


# --- Dimension heroes ---------------------------------------------------------

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
    out = card_to_dict(c)
    out["playerGold"] = st.get("gold", 0)
    out["playerCash"] = st.get("cash", 0)
    return out

def r_dimension_upgrade(body, st):
    """Spend 차원의 잔향 to raise one sync level.

    One level per call, not one per affordable step: the panel animates a single
    level-up and re-reads the card, so jumping several would desync the display from
    the state it just paid for."""
    unit_id = body_int(body.get("unitId"), 0)
    c = _card(st, unit_id)
    if c is None or dimension.model(unit_id, xml_dir=XML_DIR) is None:
        return r_card(body, st)
    level = c.get("dimensionLevel", 0)
    cost = dimension.next_cost(level, XML_DIR)
    if cost and _item_count(st, dimension.REMNANT) >= cost:
        _take_item(st, dimension.REMNANT, cost)
        c["dimensionLevel"] = level + 1
        c["dimensionGauge"] = 0
        save_state(st)
    return r_card(body, st)

def r_dimension_overcome(body, st):
    """Spend 차원 영웅 돌파권, one per step, up to OvercomeMax."""
    unit_id = body_int(body.get("unitId"), 0)
    count = body_int(body.get("count"), 1, lo=1)
    c = _card(st, unit_id)
    if c is None or dimension.model(unit_id, xml_dir=XML_DIR) is None:
        return {"unit": dimension.model(unit_id, xml_dir=XML_DIR),
                "remainTicket": _item_count(st, dimension.TICKET)}
    room = dimension.overcome_max(XML_DIR) - c.get("overcome", 0)
    step = min(count, room, _item_count(st, dimension.TICKET))
    if step > 0:
        _take_item(st, dimension.TICKET, step)
        c["overcome"] = c.get("overcome", 0) + step
        save_state(st)
    return {"unit": dimension.model(unit_id, c.get("dimensionLevel", 0),
                                    c.get("dimensionGauge", 0), c.get("overcome", 0),
                                    XML_DIR),
            "remainTicket": _item_count(st, dimension.TICKET)}


def r_ack(body, st):
    """Bare acknowledgement. Several colosseum routes report progress the server has
    nothing to keep (a cancelled match, a re-entry attempt) but still must answer."""
    return {}


# --- The rest of /player ------------------------------------------------------
# Seventeen /player routes answered an empty model. Most are one-way telemetry the
# client posts and never reads back (an ad watched, an exception, a notice clicked)
# and an acknowledgement is the whole correct answer. The three that carry state are
# the profile icon, the journey ladder and the anniversary event.

def _key_values(st):
    """The player's own key-values, as a list of {key, value} the client reads."""
    return st.setdefault("keyValues", [{"key": "profileIconId",
                                        "value": _PC["defaults"]["profileIconId"]}])

def _set_key_value(st, key, value):
    for kv in _key_values(st):
        if kv.get("key") == key:
            kv["value"] = value
            return
    _key_values(st).append({"key": key, "value": value})

def _key_value(st, key, default=None):
    for kv in _key_values(st):
        if kv.get("key") == key:
            return kv.get("value")
    return default

def r_change_profile_icon(body, st):
    """profileIconId must stay a real Unit id - ResourceBase<Unit>.Get is what draws
    the avatar, and an id that does not resolve gives a blank white circle."""
    icon = body_int(body.get("profileIconId") or body.get("iconId"), 0)
    if str(icon) in st.get("cards", {}):
        _set_key_value(st, "profileIconId", icon)
        save_state(st)
    return {"keyValues": _key_values(st)}

def r_player_ad(body, st):
    """Rewarded-video counter. Nothing here plays an ad, but the count is what the
    button reads to decide whether it is still offering one today."""
    st["dailyAdCount"] = int(st.get("dailyAdCount", 0)) + 1
    save_state(st)
    return {"dailyAdCount": st["dailyAdCount"]}

def r_player_other(body, st):
    """Another player's profile, looked up by the client's `targetId` (their
    accountId). Unknown id falls back to the current player, so a solo server still
    answers - which is also what the clan and leaderboard panels link to."""
    st = _player_by_id(body_int(body.get("targetId"), 0), st)
    d = _PC["defaults"]
    deco = _deco(st)
    return {"name": st.get("name", d["name"]),
            "castleName": st.get("castleName", d["castleName"]),
            "kingPostfix": st.get("kingPostfix", 0), "castlePostfix": st.get("castlePostfix", 0),
            "profileIconId": _key_value(st, "profileIconId", d["profileIconId"]),
            "profileIconBackgroundId": 0, "nameTagId": deco["nameTag"],
            "level": st.get("level", 1), "exp": st.get("exp", 0),
            "invasionDifficultyRecords": [], "eventModeRecord": [],
            "rogueLikeBuildingChallengeLevelRecord": [],
            "babelRecord": [b["floor"] for b in _babel(st).values()] or [0],
            "winCount": st.get("pvpWin", 0), "heroCount": len(st.get("cards", {})),
            "currentAltar": 0, "currentDeck": pvp.card_infos(st),
            "currentPotential": [], "firstComerIndex": 0,
            "currentRanking": [], "currentHardRanking": [],
            "clanId": st.get("clanId", 0), "clanMark": 0,
            "clanRole": st.get("clanRole", 0), "clanName": st.get("clanName", ""),
            "clanTier": 0, "clanRoleNames": []}

# --- Mini-games ----------------------------------------------------------------
# Roguelike, Territory Tycoon, stock event, KG Marble, event-card collecting


# --- Account transfer ---------------------------------------------------------
# Moving a save to another device: one side asks for a code, the other redeems it.
# The code is the whole security model - whoever has it gets the save - so it is
# random, single-use, and expires.

TRANSFER_TTL_HOURS = 24

def r_transfer_issue(body, st):
    """Mint a transfer code for this save, replacing any code still outstanding."""
    code = secrets.token_hex(4).upper()
    st["transfer"] = {"code": code, "expiresAt": now_iso(seconds=TRANSFER_TTL_HOURS * 3600)}
    save_state(st)
    admin_log(f"[auth] transfer code issued for uid={st.get('uid', '?')}")
    return {"secretCode": code}

def _transfer_lookup(code):
    """The uid holding an unexpired copy of `code`. Scans every save, which is fine
    at KGC_MAX_PLAYERS and avoids a second table that could drift out of sync."""
    if not code:
        return None
    for uid, saved, _updated in playerdb.all_players():
        t = (saved or {}).get("transfer") or {}
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
    login_id = str(CURRENT_LOGIN_ID.get() or body.get("id") or "")
    if MULTIPLAYER and login_id:
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


# --- The last few odds and ends -----------------------------------------------

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
    weapon = next((w for w in DEFAULT_RIFT_WEAPONS if w.get("id") == wid), None)
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
            "rewardList": _reward_list_data([])}

def r_cloud_run_services(body, st):
    """Infrastructure discovery. The real backend answers with the regional service
    endpoints it wants the client to use; here everything is this server, so the
    honest answer is an empty list and the client keeps its configured host."""
    return {"services": [], "ranking": []}

# --- Babel: the six towers ----------------------------------------------------

def _babel(st):
    return st.setdefault("babel", {})     # babelId (str) -> {"floor": n, "passes": []}

def r_babel(body, st):
    b = _babel(st)
    out = []
    for bid, t in sorted(babel.towers(XML_DIR).items()):
        rec = b.get(str(bid), {})
        nxt = babel.next_open(bid, xml_dir=XML_DIR)
        out.append({"id": bid,
                    "available": babel.available(bid, xml_dir=XML_DIR),
                    "maxClearedFloor": rec.get("floor", 0),
                    "boughtPasses": rec.get("passes", []),
                    "availableAt": nxt.strftime("%Y-%m-%dT%H:%M:%S.000Z") if nxt else ""})
    return {"babels": out}

def _babel_clear(st, theme, floor):
    """Record a cleared floor and pay it, once. Returns the granted rewards.

    Only a new best floor pays: the towers can be re-run for practice, and paying
    every run turns floor 1 of an always-open tower into an unlimited faucet."""
    bid = babel.theme_to_id(XML_DIR).get(theme)
    if bid is None:
        return []
    rec = _babel(st).setdefault(str(bid), {"floor": 0, "passes": []})
    if floor <= rec["floor"] or floor > babel.towers(XML_DIR)[bid]["maxFloor"]:
        return []
    rec["floor"] = floor
    return [_grant_mission_reward(st, r)
            for r in babel.floor_reward(theme, floor, XML_DIR)]


# --- Attendance check-ins -----------------------------------------------------
# Neither system has a claim route: the reads grant. The check-in is opening the
# game that day, which is why the reward tables carry no button.

def _today_str():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")

def _attend(st):
    a = st.setdefault("attendance", {})
    a.setdefault("daily", {})       # eventId -> {"day": n, "on": "YYYYMMDD"}
    a.setdefault("surprise", {})    # {"id", "day", "lastRewardDay", "on", "continuous"}
    return a

def r_daily_attendance_events(body, st):
    """Advance every daily board by at most one day, and pay for the day landed on.

    Capped at one advance per UTC day per event: this route is called on every lobby
    refresh, so advancing per call would walk a 14-day board in fourteen taps."""
    a = _attend(st)
    today = _today_str()
    events = attendance.daily_events(XML_DIR)
    granted = []
    for eid in sorted(events):
        rec = a["daily"].setdefault(str(eid), {"day": -1, "on": ""})
        length = attendance.daily_length(eid, XML_DIR)
        if rec["on"] != today and rec["day"] + 1 < length:
            rec["day"] += 1
            rec["on"] = today
            for r in events[eid].get(rec["day"], []):
                granted.append(_grant_mission_reward(st, r))
    if granted:
        save_state(st)
    ids = sorted(events)
    return {"eventIds": ids,
            # attendances is parallel to eventIds and counts days attended, so a board
            # sitting on 0-based day 0 has attended one day.
            "attendances": [a["daily"].get(str(i), {}).get("day", -1) + 1 for i in ids],
            "rewardList": _reward_list_data(granted)}

def _surprise_state(st, ev):
    a = _attend(st)
    s = a["surprise"]
    if not ev:
        return s
    if s.get("id") != ev["id"]:
        # A new event replaces the old board rather than resuming it.
        s.clear()
        s.update({"id": ev["id"], "day": 0, "lastRewardDay": 0, "on": "",
                  "continuous": True})
    return s

def _surprise_response(st, ev):
    s = _surprise_state(st, ev)
    if not ev:
        return {"eventId": 0, "currentAttendanceDay": 0, "lastAttendanceRewardDay": 0,
                "isContinuous": False, "eventUntilAt": ""}
    end = datetime.datetime.strptime(str(ev["end"]), "%Y%m%d") + datetime.timedelta(days=1)
    return {"eventId": ev["id"], "currentAttendanceDay": s.get("day", 0),
            "lastAttendanceRewardDay": s.get("lastRewardDay", 0),
            "isContinuous": bool(s.get("continuous", True)),
            "eventUntilAt": end.strftime("%Y-%m-%dT%H:%M:%S.000Z")}

def r_surprise_attendance(body, st):
    """Opening the panel is the check-in; the reward is claimed by the other route."""
    ev = attendance.current_surprise(xml_dir=XML_DIR)
    s = _surprise_state(st, ev)
    if ev:
        today = _today_str()
        if s.get("on") != today and s.get("day", 0) < len(ev["rewards"]):
            # A skipped day breaks the streak, which is what the continuous bonus
            # at the end of the board is gated on.
            if s.get("on") and s["on"] != (datetime.datetime.strptime(today, "%Y%m%d")
                                           - datetime.timedelta(days=1)).strftime("%Y%m%d"):
                s["continuous"] = False
            s["day"] = s.get("day", 0) + 1
            s["on"] = today
            save_state(st)
    return _surprise_response(st, ev)

def r_surprise_attendance_reward(body, st):
    """Pay every day reached but not yet claimed, plus the continuous bonus once the
    whole board is done without a break."""
    ev = attendance.current_surprise(xml_dir=XML_DIR)
    if not ev:
        return {"eventResponseModel": _surprise_response(st, ev),
                "rewardListResponseData": _reward_list_data([])}
    s = _surprise_state(st, ev)
    granted = []
    while s.get("lastRewardDay", 0) < s.get("day", 0):
        s["lastRewardDay"] += 1
        for r in ev["rewards"].get(s["lastRewardDay"], []):
            granted.append(_grant_mission_reward(st, r))
    if (s["lastRewardDay"] >= len(ev["rewards"]) and s.get("continuous")
            and not s.get("continuousPaid")):
        s["continuousPaid"] = True
        for r in ev["continuous"]:
            granted.append(_grant_mission_reward(st, r))
    if granted:
        save_state(st)
    return {"eventResponseModel": _surprise_response(st, ev),
            "rewardListResponseData": _reward_list_data(granted)}

def r_game_revive(body, st):
    """Reviving mid-battle. The coupon is free; otherwise it costs cash, and a player
    who cannot pay must not be revived silently for nothing."""
    gc = RCFG["gameComplete"]
    if not body.get("useReviveCoupon"):
        price = gc.get("revivePrice", 30)
        if st.get("cash", 0) < price:
            return {"msg": "not enough cash", "playerGold": st.get("gold", 0),
                    "playerLevel": st.get("level", 1), "playerExp": st.get("exp", 0)}
        st["cash"] -= price
        save_state(st)
    return {"addGold": 0, "addExp": 0, "playerGold": st.get("gold", 0),
            "playerLevel": st.get("level", 1), "playerExp": st.get("exp", 0)}


# Dynamic overrides: routes whose response genuinely depends on request-time
# state/body (auth tokens, st.get() reads, mutations) or config wiring. Pure
# literal responses live in data/static_overrides.json instead (merged in below).
DYNAMIC_OVERRIDES = {
    "/auth/checkPatchVersion": lambda b, st: {"patchVersion": SERVER_VERSION},
    "/auth/getPatchFolder": lambda b, st: {"patchFolder": PATCH_FOLDER},
    "/auth": r_login,
    "/auth/login": r_login,
    "/auth/register": r_login,
    "/auth/link": r_login,
    "/auth/xcdSeed": lambda b, st: {"seed": secrets.token_hex(8), "serverTime": now_iso(0)},
    "/player": r_player,
    "/player/currencies": lambda b, st: {"gold": st.get("gold", 0), "cash": st.get("cash", 0), "heart": st.get("heart", 0)},
    "/player/tutorial-status": lambda b, st: {"keyValues": st.get("tutorialKeyValues", [])},
    "/player/tutorial/complete": lambda b, st: {"keyValues": st.get("tutorialKeyValues", [])},
    "/player/getInventory": r_player_inventory,
    "/player/useInventory": r_use_inventory,
    "/player/use-reward-box-inventory-item": r_use_reward_box,
    "/player/use-skin-box-inventory-item": r_use_skin_box,
    "/player/receive-skin-box-alternate-reward": r_use_skin_box,
    "/player/add-inventory-count": lambda b, st: {
        "playerCash": st.get("cash", 0),
        "inventoryCount": 999
    },
    "/player/rename": r_player_rename,
    "/player/building": lambda b, st: {"buildingPoint": st.get("buildingPoints", 25), "buildingData": _get_building_data(st)},
    "/player/building/point": lambda b, st: {"buildingPoint": st.get("buildingPoints", 25), "buildingData": _get_building_data(st)},
    "/player/building/save": r_building_save,
    "/player/building/resetPoint": r_building_reset_point,
    "/player/heart/recover": lambda b, st: {"heart": st.get("heart", 999), "lastHeartTime": now_iso(0)},
    "/game/start": r_game_start,
    "/game/complete": r_game_complete,
    "/game/skip": r_game_complete,
    "/card/all": r_card_all,
    "/card/upgrade": r_card_upgrade,
    "/card/fast-upgrade": r_card_fast_upgrade,
    "/card/upgradePotentialTier": r_card_upgrade_potential,
    "/card/useCandy": r_card_use_candy,
    "/card/useUnitExpItem": r_card_use_candy,
    "/card/useUnitSoulItem": r_card_use_candy,
    "/card/useUnitSoulItemToExp": r_card_use_candy,
    "/card/useUnitSoulToExp": r_card_use_candy,
    "/card/buySkin": r_card_buy_skin,
    "/card/equipSkin": r_card_equip_skin,
    "/card/set-random-skin-apply": r_card_set_random_skin,
    "/card/set-skin-favorite": r_card_set_skin_favorite,
    "/deck": r_deck,
    "/deck/set": r_deck_set,
    "/deck/setPotential": r_deck_set_potential,
    "/deck/setAllPotential": r_deck_set_all_potential,
    "/deck/buyDeckSlot": r_deck,
    "/deck/set-deck-slot-name": r_deck,
    "/mission": r_mission,
    "/mission/reward-all": r_mission_reward_all,
    "/story-mode/challenge/info": r_challenge_info,
    "/story-mode/challenge/reward": r_challenge_reward,
    "/story-mode/challenge/daily-reward": r_challenge_daily,
    "/invasion/reward": r_invasion_reward,
    "/invasion/reward/receive": r_invasion_reward,
    "/invasion/reward/receive-all": r_invasion_reward_all,
    "/mission/check": r_mission,
    "/eventcache": r_event_cache,
    "/auth/transfer/code": r_transfer_issue,
    "/auth/transfer": r_transfer_redeem,
    # GameManager.usePatch is hardcoded to 1 in the binary, so this answer is
    # advisory only - but it has to be the truthful one, since the CDN check runs
    # either way and we serve real cloned bundles.
    "/auth/usePatch": lambda b, st: {"usePatch": True},
    "/game/eventMode": r_event_mode,
    "/game/check-dimension-rift-complete-success": r_ack,
    "/kg-wiki/insert-wiki": r_wiki,
    "/kg-wiki/rift-weapon/archive": r_wiki_archive,
    "/kg-wiki/rift-weapon/archive-delete": r_wiki_archive_delete,
    "/pass/reroll-mission": r_pass_reroll_mission,
    "/shop-event/cumulative-purchase": r_cumulative_purchase,
    "/shop-event/cumulative-purchase/claim": r_cumulative_purchase_claim,
    "/api/cloud-run/services": r_cloud_run_services,
    "/api/cloud-run/default-ranking": r_cloud_run_services,
    "/kgc-main": r_ack,
    "/kgc-ranking": roster.r_ranking,
    "/seasonal-event/april-fools/reward": lambda b, st: {
        "rewardListResponseData": _reward_list_data([])},
    "/artifact/reroll": r_artifact_result,
"/artifact/polish/replace-option-slot-idx": r_artifact_result,
    "/mission/roguelike/check-on-clear": r_ack,
    # /test/* are the client's own dev buttons. They exist in the build, so they
    # must answer, but nothing here is meant to rewrite a save from a debug menu.
    "/test/roguelike/clear-count": r_ack,
    "/test/roguelike/play-count": r_ack,
    "/test/roguelike/mission-clear-count": r_ack,
    "/test/roguelike/reset-mission": r_ack,
    "/player/ad": r_player_ad,
    "/player/changeProfileIcon": r_change_profile_icon,
    "/player/other": r_player_other,
    "/player/tutorial/progress-mission": lambda b, st: {
        "keyValues": st.get("tutorialKeyValues", [])},
    # One-way telemetry: posted, never read back.
    "/player/exception": r_ack,
    "/player/xcdReport": r_ack,
    "/player/customEvent": r_ack,
    "/player/logClickNotice": r_ack,
    "/player/completeKingGakReturnEvent": r_ack,
    "/artifact/inventory": r_artifact_inventory,
    "/artifact/equip": r_artifact_equip,
    "/artifact/crafting": r_artifact_result,
    "/artifact/dismantle": r_artifact_result,
    "/artifact/merge": r_artifact_result,
    "/artifact/polish": r_artifact_result,
    "/artifact/gacha": r_artifact_result,
    "/artifact/set-reroll": r_artifact_result,
    "/artifact/smart-reroll": r_artifact_result,
    "/artifact/fetch-reroll": r_artifact_result,
    "/artifact/open-catalyst-box": r_artifact_result,
    "/artifact/set-favorites": r_artifact_result,
    "/treasure": r_treasure,
    "/treasure/equip": r_treasure_equip,
    "/treasure/add-exp": r_treasure_add_exp,
    "/treasure/dismantle": r_treasure,
    "/treasure/equip-tutorial": r_treasure_equip,
    "/treasure/overcome": r_treasure,
    "/treasure/release-equip": r_treasure_release,
    "/treasure/set-state": r_treasure,
    "/rift-weapon": r_rift_weapon,
    "/rift-weapon/upgrade": r_rift_weapon,
    "/rift-weapon/equip": r_rift_weapon,
    "/rift-weapon/release-equip": r_rift_weapon,
    "/rift-weapon/dismantle": r_rift_weapon,
    "/rift-weapon/re-roll": r_rift_weapon,
    "/rift-weapon/reset-weapon": r_rift_weapon,
    "/rift-weapon/set-state": r_rift_weapon,
    "/rift-weapon/set-crystal-state": r_rift_weapon,
    "/rift-weapon/crystal-charge": r_rift_weapon,
    "/rift-weapon/crystal-destroy": r_rift_weapon,
    "/rift-weapon/crystal-inventory": r_rift_weapon,
    "/rift-weapon/buy-rift-gauge": r_rift_weapon,
    **clan.handlers(),
    "/pass": r_pass,
    "/pass/reward": r_pass,
    "/pass/all-rewards": r_pass,
    "/pass/bonusReward": r_pass,
    "/pass/buyLevel": r_pass,
    "/pass/passEventBooster": r_pass,
    "/accessory": r_accessory,
    "/accessory/equip-tutorial": lambda b, st: {"accessories": get_st_accessories(st)},
    "/accessory/add-exp": r_accessory_result,
    "/accessory/dismantle": lambda b, st: {"accessories": get_st_accessories(st), "deletedAccessories": b.get("accessoryIds", []), "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0), "inventories": [], "addedExpItems": 0},
    "/accessory/release-equip": r_accessory_release,
    "/accessory/set-state-all": r_accessory_result,
    "/accessory/change-sub-stat": r_accessory_result,
    "/accessory/preset": lambda b, st: {"presets": []},
    "/accessory/set-preset": lambda b, st: {"presets": []},
    "/accessory/set-preset-name": lambda b, st: {"presets": []},
    "/accessory/equip": r_accessory,
    "/card": r_card,
    "/dimension-unit/upgrade": r_dimension_upgrade,
    "/dimension-unit/overcome": r_dimension_overcome,
    # The v171 client uses both spellings of the battle-start route.
    "/game": r_game_start,
    "/game/revive": r_game_revive,
    "/babel": r_babel,
    "/player/dailyAttendanceEvents": r_daily_attendance_events,
    "/player/surprise-attendance-event": r_surprise_attendance,
    "/player/surprise-attendance-event-daily-attendance-reward": r_surprise_attendance_reward,
}

SERVER_START_TIME = time.time()

app = FastAPI(title="KGC private server", version=SERVER_VERSION)
_STATE_GATE = asyncio.Lock()

# A public server holds other people's progress. Cron is the textbook answer and
# nobody sets it up, so this runs in-process; playerdb.backup_if_due does the
# due-check under the cross-process lock, which is what stops :8080 and :8443 both
# firing. KGC_BACKUP_HOURS=0 turns it off (use your own backups instead).
BACKUP_HOURS = float(os.environ.get("KGC_BACKUP_HOURS") or 24)


@app.on_event("startup")
async def periodic_backup():
    if BACKUP_HOURS <= 0:
        admin_log("[state] automatic backups off (KGC_BACKUP_HOURS=0)")
        return

    async def loop():
        interval = BACKUP_HOURS * 3600
        while True:
            try:
                # to_thread: the lock and the copy are blocking, and this must not
                # stall the event loop while a player is mid-request.
                dst = await asyncio.to_thread(playerdb.backup_if_due, interval)
                if dst:
                    admin_log(f"[state] backup -> {dst.name}")
            except Exception as e:
                admin_log(f"[state] backup failed: {type(e).__name__}: {e}")
            await asyncio.sleep(min(3600, interval))

    asyncio.create_task(loop())

# Google login web flow (client's Google button -> /glogin -> deep link back).
import google_login
google_login.register(app)
admin_log(f"[auth] google login {'ENABLED' if google_login.enabled() else 'not configured'}")

# Behind Cloudflare Tunnel, nginx, or any port-forward that rewrites the source, every
# request arrives from 127.0.0.1 - so the per-IP limits below collapse into a single
# bucket shared by every player on earth, and five new accounts an hour becomes the
# whole server's budget. The forwarded header is the real address, but it is also
# trivially forged by anyone talking to us directly, so trusting it is opt-in and
# belongs ONLY on a deployment where a proxy is the sole way in.
TRUST_PROXY = os.environ.get("KGC_TRUST_PROXY") == "1"


def client_ip(request):
    peer = request.client.host if request.client else "-"
    if not TRUST_PROXY:
        return peer
    fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
    # x-forwarded-for is a chain; the leftmost entry is the original client.
    return fwd.split(",")[0].strip() or peer


ADMIN_TOKEN = os.environ.get("KGC_ADMIN_TOKEN")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
ADMIN_COOKIE = "kgc_admin"          # same session cookie the dashboard issues


def _admin_ok(request):
    """Whether this request may touch /admin. Three ladders, most specific first.

    The loopback fallback is last and weakest: behind a tunnel or any reverse proxy
    EVERY request arrives from loopback, so it is only safe on a box nobody else can
    reach. It is therefore refused outright once a real credential exists - the hole
    it plugged was serve_public.sh accepting a dashboard account instead of a token,
    which left this middleware with nothing to check and everything to allow.
    """
    if ADMIN_TOKEN:
        sent = (request.headers.get("x-admin-token")
                or request.query_params.get("admin_token") or "")
        return secrets.compare_digest(sent, ADMIN_TOKEN)
    if playerdb.admin_count():
        token = (request.cookies.get(ADMIN_COOKIE)
                 or request.headers.get("x-admin-token") or "")
        return playerdb.admin_for_token(token) is not None
    # client_ip, not the raw peer: with KGC_TRUST_PROXY on we can tell a real remote
    # player apart from the proxy in front of us, and this check stops lying.
    return client_ip(request) in _LOOPBACK


@app.middleware("http")
async def guard_admin(request: Request, call_next):
    """The /admin routes can rewrite or delete any player's save.

    serve_public.sh binds 0.0.0.0 so remote players can reach the game API - which
    exposes these too.
    """
    if request.url.path.startswith("/admin") and not _admin_ok(request):
        return JSONResponse(
            {"error": "admin credentials required", "login": True}, status_code=403)
    return await call_next(request)

# A public server is reachable by anyone, and every route does real work (master-data
# lookups, a state read-modify-write under a cross-process lock). This is the ceiling
# on how fast one address can drive that, so a single misbehaving client - or a bored
# one with curl - cannot starve everyone else.
# ponytail: fixed window per process, no burst smoothing. Two uvicorns and a human
# operator; move it to Redis if this ever fronts real traffic.
# 600/min is deliberately generous. A lobby boot is a burst of ~60-80 requests, and
# the address is often shared: friends behind one NAT, or - without KGC_TRUST_PROXY -
# every player on the server behind one tunnel. Too tight and legitimate players fail
# to boot, which looks exactly like the server being down. It still bounds a runaway
# client to something the state lock can absorb.
RATE_LIMIT = int(os.environ.get("KGC_RATE_LIMIT") or 600)      # requests
RATE_WINDOW = int(os.environ.get("KGC_RATE_WINDOW") or 60)     # seconds
# Blowing the window once is a misbehaving client; blowing it repeatedly is an
# attacker. After RATE_BAN_AFTER consecutive 429s the address is banned for
# RATE_BAN_SECONDS: banned requests are refused BEFORE the rate table is touched,
# so a spammer can no longer burn a state-lock cycle (or the event loop) per
# request. KGC_IPTABLES_BAN=1 also drops the address at the firewall - needs a
# sudoers rule granting `sudo -n iptables -I/-D INPUT -s <ip> -j DROP` to the
# service user, see serve_public.sh. The ban is in-memory per process: the two
# uvicorns (8080/8443) each keep their own copy, which is fine - the firewall
# rule is what actually stops the bytes.
RATE_BAN_AFTER = int(os.environ.get("KGC_RATE_BAN_AFTER") or 5)
RATE_BAN_SECONDS = int(os.environ.get("KGC_RATE_BAN_SECONDS") or 900)
IPTABLES_BAN = os.environ.get("KGC_IPTABLES_BAN") == "1"
_rate_hits = {}
_banned = {}             # ip -> unban wall-clock timestamp
_ban_strikes = {}        # ip -> consecutive 429 count
_IPTABLES = shutil.which("iptables") if IPTABLES_BAN else None


def _iptables_rule(action, ip):
    """action: "-I" (insert, position 1) or "-D" (delete). Never touch the loopback
    or a proxy address - banning 127.0.0.1 behind a tunnel locks everyone out."""
    if not _IPTABLES or ":" in ip or ip in _LOOPBACK:
        return
    cmd = [_IPTABLES, "-I", "INPUT", "1", "-s", ip, "-j", "DROP"] if action == "-I" \
        else [_IPTABLES, "-D", "INPUT", "-s", ip, "-j", "DROP"]
    try:
        subprocess.run(["sudo", "-n"] + cmd, capture_output=True, timeout=10)
    except Exception as e:
        admin_log(f"[ban] iptables {action} {ip} failed: {type(e).__name__}: {e}")


async def _unban_later(ip):
    await asyncio.sleep(RATE_BAN_SECONDS)
    _banned.pop(ip, None)
    await asyncio.to_thread(_iptables_rule, "-D", ip)


def _ban(ip, now=None):
    now = time.time() if now is None else now
    _banned[ip] = now + RATE_BAN_SECONDS
    _ban_strikes.pop(ip, None)
    if len(_banned) > 5000:                # bound memory, drop everyone expired
        _banned.clear()
    admin_log(f"[ban] {ip} -> {RATE_BAN_SECONDS}s (rate abuse)")
    if IPTABLES_BAN:
        _iptables_rule("-I", ip)
        asyncio.create_task(_unban_later(ip))


def _rate_ok(ip, now=None):
    if RATE_LIMIT <= 0:
        return True                       # KGC_RATE_LIMIT=0 turns it off
    now = time.time() if now is None else now
    window = int(now // RATE_WINDOW)
    key, count = _rate_hits.get(ip, (None, 0))
    if key != window:
        if len(_rate_hits) > 5000:        # bound it: drop everyone from older windows
            _rate_hits.clear()
        _rate_hits[ip] = (window, 1)
        return True
    if count >= RATE_LIMIT:
        return False
    _rate_hits[ip] = (window, count + 1)
    return True


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    # The CDN is static bytes off a dict and is what a fresh install hammers hardest
    # (six bundles, one after another) - limiting it would break first launches.
    if request.url.path.startswith("/patch/"):
        return await call_next(request)
    ip = client_ip(request)
    now = time.time()
    until = _banned.get(ip)
    if until is not None:
        if until > now:
            return JSONResponse({"error": "temporarily banned"}, status_code=429,
                                headers={"retry-after": str(int(until - now) + 1)})
        _banned.pop(ip, None)
    if not _rate_ok(ip, now):
        strikes = _ban_strikes.get(ip, 0) + 1
        _ban_strikes[ip] = strikes
        if strikes >= RATE_BAN_AFTER:
            _ban(ip, now)
        return JSONResponse({"error": "too many requests"}, status_code=429,
                            headers={"retry-after": str(RATE_WINDOW)})
    _ban_strikes.pop(ip, None)   # a healthy request earns a clean slate
    return await call_next(request)


# The real client's biggest body is a roguelike save blob, a few KB. Starlette buffers
# the whole body in memory before a handler sees it, so with no cap one POST of a few
# hundred MB is a one-line denial of service against a public server.
MAX_BODY = int(os.environ.get("KGC_MAX_BODY") or 1_000_000)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY:
        admin_log(f"[limit] rejected {declared}-byte body on {request.url.path}")
        return JSONResponse({"error": "request body too large"}, status_code=413)
    return await call_next(request)


@app.middleware("http")
async def serialize_state_writes(request: Request, call_next):
    """One request at a time may read-modify-write player state.

    Handlers load state, mutate it and save it as separate steps, so without
    this the :8080 and :8443 processes interleave and one silently discards the
    other's changes. CDN traffic never touches state - skip it, it is the bulk
    of the bytes.
    """
    if request.url.path.startswith("/patch/"):
        return await call_next(request)
    # Resolve identity BEFORE taking the lock: the ContextVar must be set in this
    # task so the child task call_next() spawns inherits it.
    token = CURRENT_UID.set(playerdb.uid_for_token(request.headers.get("accesstoken")))
    ip_token = CURRENT_IP.set(client_ip(request))
    try:
        # asyncio.Lock first: flock blocks the thread, so a second request in THIS
        # process waiting on it would freeze the event loop and never let the holder
        # finish. Serialize in-process, then contend with the other process.
        async with _STATE_GATE:
            with playerdb.write_lock():
                return await call_next(request)
    finally:
        CURRENT_UID.reset(token)
        CURRENT_IP.reset(ip_token)

@app.get("/")
def health():
    return {"server": "kgc-private", "version": SERVER_VERSION, "routes": len(ROUTE_MODELS), "patchFolder": PATCH_FOLDER}

# Real patch-set files cloned byte-for-byte from Awesomepiece CDN
# (https://kgc-cdn-1.awesomepiece.com/patch/LIVE/<patchFolder>/ANDROID/). These are
# guaranteed version-compatible with the client (they ARE the real bundles), so
# UpdatePatchSetList loads the manifest + validates hashes without error.
# AssetHash.txt confirms format <name>:<md5>_<size>; manifest is the "ANDROID" file.
REAL_CDN = ROOT / "real_cdn"
_CDN_FILES = {p.name: p.read_bytes() for p in REAL_CDN.iterdir()} if REAL_CDN.is_dir() else {}
admin_log(f"[cdn] cloned {len(_CDN_FILES)} real patch files: {sorted(_CDN_FILES)}")

@app.get("/patch/{path:path}")
async def cdn_patch(path: str, request: Request):
    host = request.headers.get("host", "?")
    fname = path.split("/")[-1]
    data = _CDN_FILES.get(fname)
    admin_log(f"[{host}] CDN GET /patch/{path} -> {'HIT' if data is not None else 'MISS'}")
    if data is None:
        return Response(status_code=404)
    if fname in ("PatchVersion.txt", "AssetHash.txt"):
        return Response(data, media_type="text/plain")
    return Response(data, media_type="application/octet-stream")

async def _read_capped(request):
    """The body, refusing to buffer more than MAX_BODY of it.

    The Content-Length middleware covers every real client request, but a chunked
    upload declares no length - and `request.body()` buffers the whole thing before
    anyone can check it. Reading the stream ourselves means an attacker gets one
    MAX_BODY allocation, not one per gigabyte they feel like sending.
    """
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY:
            raise ValueError(f"body exceeded {MAX_BODY} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def respond(path: str, request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    try:
        raw = await _read_capped(request)
    except ValueError as e:
        admin_log(f"[limit] {path}: {e}")
        return JSONResponse({"error": "request body too large"}, status_code=413)
    body = {}
    if raw:
        try:
            body = aes_decrypt(raw)
        except Exception:
            try:
                body = json.loads(raw)
            except Exception:
                if path == "/deck/set":
                    admin_log(f"[DECK/SET DECRYPT FAIL] raw_len={len(raw)} raw_hex={raw[:64].hex()}")
                body = {}
    # A body of `5`, `"x"` or `[1,2]` is valid JSON but not an object, and every
    # handler below indexes it like a dict. Coerce here rather than guarding each
    # one: `/auth/register` with a bare integer body reached `body.get("id")` and
    # 500'd, which the client cannot parse (it wants the AES envelope) - it sits on
    # the loading screen instead of failing.
    if not isinstance(body, dict):
        body = {}
    # Many routes carry their arguments in the query string, not the body:
    # /territory/upgrade-building?posIndex={0}, /card?cardId={0}, /player/other?targetId={0}.
    # Handlers only ever saw the body, so every one of those arrived as an empty dict
    # and the request looked like it had no arguments at all. Body wins on a clash,
    # since a route that sends both means the body.
    if request.query_params:
        merged = {}
        for k, v in request.query_params.items():
            if v.lstrip("-").isdigit():
                merged[k] = int(v)
            elif v.lower() in ("true", "false"):
                merged[k] = v.lower() == "true"
            else:
                merged[k] = v
        merged.update(body)
        body = merged

    info = ROUTE_MODELS.get(path, {"response": "ResponseModel", "method": None})
    # /auth/auth carries the account id as ?id=, /auth/register as body.id.
    if path.startswith("/auth/"):
        CURRENT_LOGIN_ID.set(request.query_params.get("id") or body.get("id") or "")
    if path in _PATH_COUNTERS:
        bump(st, _PATH_COUNTERS[path])
        save_state(st)
    try:
        overlay = OVERRIDES[path](body, st) if path in OVERRIDES else None
    except Exception as e:
        # One player sending one bad body must not 500 - the client cannot parse a
        # FastAPI error page (it expects the AES envelope) and would sit on the
        # loading screen. Fall back to the route's empty model, which is the same
        # shape it would get from a route with no handler.
        admin_log(f"[HANDLER ERROR] {path}: {type(e).__name__}: {e}")
        overlay = None
    if overlay is None and path not in ROUTE_MODELS:
        # Every route the v171 client can call is now mapped (route_models.json plus
        # data/route_models_extra.json), so reaching here means either a route the
        # string-table scan missed or a client newer than this server.
        admin_log(f"[UNKNOWN PATH] {request.method} {path}")
    payload = build_model(info["response"], overlay)
    trace(f"[{host}] {request.method} {path} -> {info.get('response')}")
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

def make_handler(path):
    async def h(request: Request):
        return await respond(path, request)
    return h

def _grant_reward(st, rt, rid, amt):
    """Apply a claimed mail reward to player state. Currencies, inventory items, and hero
    souls/cards persist here; the client re-fetches /player, /player/getInventory and /card/all
    after a claim so the granted state appears. Treasure is granted as a real owned instance
    (same shape make_treasure builds for the default inventory). Artifact/Accessory stay
    display-only - they trip client panel invariants (see AGENTS.md ArtifactOptionUI crash);
    gift those as an Item reward box (InventoryItems.xml Type=RewardBoxInventory/
    InstantRewardBox) which the player opens."""
    if rt == "Gold":
        st["gold"] = st.get("gold", 0) + amt
    elif rt == "Cash":
        st["cash"] = st.get("cash", 0) + amt
    elif rt == "Heart":
        st["heart"] = st.get("heart", 0) + amt
    elif rt == "Item" and rid:
        inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
        ids = inv.setdefault("itemIds", [])
        cnts = inv.setdefault("counts", [])
        if rid in ids:
            cnts[ids.index(rid)] += (amt or 1)
        else:
            ids.append(rid)
            cnts.append(amt or 1)
    elif rt in ("Unit", "Card") and rid:
        st.setdefault("cards", {}).setdefault(str(rid), {"unitId": rid, **SEED["cardTemplate"]})
    elif rt == "UnitSoul" and rid:
        c = st.setdefault("cards", {}).setdefault(str(rid), {"unitId": rid, **SEED["cardTemplate"]})
        c["soul"] = c.get("soul", 0) + amt
    elif rt == "Treasure" and rid:
        # A default save already owns every treasure, so this only fires for a save
        # whose treasure list was trimmed. Duplicates are skipped - the client keys the
        # treasure panel on treasureId and shows a second copy as an empty slot.
        tr = get_st_treasures(st)
        if not any(t.get("treasureId") == rid for t in tr):
            tr.append(make_treasure(max((t.get("id", 0) for t in tr), default=0) + 1, rid))

# ── Admin, Inbox, Direct routes ──
# Registered before ROUTE_MODELS so they take priority over the generic dispatcher.
# One crystal per weapon, each pointed at a different altar so the set actually covers
# distinct options instead of six copies of "Rift Crystal of Hero".
DEFAULT_RIFT_CRYSTALS = [make_rift_crystal(i + 1, rwid, main_idx=i)
                         for i, rwid in enumerate(ALL_RIFT_WEAPON_IDS)]

import admin_api
import inbox
import direct_routes
import decoration_routes
import pvp
import territory_routes
import shop_routes
import seasonal
import mini_games
admin_api.register(app, sys.modules[__name__])
inbox.register(app, sys.modules[__name__])
_admin_changed = playerdb.backfill_account_ids()
if _admin_changed:
    admin_log(f"[accounts] backfilled {_admin_changed} duplicate/missing accountId(s)")
decoration_routes.register(app, sys.modules[__name__])
pvp.register(app, sys.modules[__name__])
territory_routes.register(app, sys.modules[__name__])
shop_routes.register(app, sys.modules[__name__])
seasonal.register(app, sys.modules[__name__])
roster.register(app, sys.modules[__name__])
mini_games.register(app, sys.modules[__name__])
# Last: its /pvp/info reads srv.PVP_OVERRIDES, which pvp.register above installs.
direct_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(DECORATION_OVERRIDES)
DYNAMIC_OVERRIDES.update(MINI_GAME_OVERRIDES)
DYNAMIC_OVERRIDES.update(PVP_OVERRIDES)
DYNAMIC_OVERRIDES.update(TERRITORY_OVERRIDES)
DYNAMIC_OVERRIDES.update(SHOP_OVERRIDES)
DYNAMIC_OVERRIDES.update(SEASONAL_OVERRIDES)
DYNAMIC_OVERRIDES.update(RANKING_OVERRIDES)

# Every extracted handler is re-exported here under the name it had while it lived in
# this file. The tests and the dashboard reach for `server.r_shop`, `server.r_clan`,
# `server.r_territory_fetch` and 80 more; rewriting 36 test files to chase a handler
# between modules is churn that would have to happen again on the next extraction, and
# it is also what makes a handler moving out of here a silent breakage rather than a
# failed import. One loop, one place to look.
for _mod in (clan, pvp, shop_routes, roster, seasonal, mini_games,
             territory_routes, decoration_routes, inbox, direct_routes):
    for _n in dir(_mod):
        # Handlers and their helpers, plus the module's own SHOUTY constants
        # (CLAN_MASTER, TYCOON_TOKENS, JOURNEY_LAST, ...) which callers pin against.
        if _n.startswith("__") or _n in ("srv", "app"):
            continue
        if _n.startswith(("r_", "get_st_", "_")) or _n.isupper():
            globals().setdefault(_n, getattr(_mod, _n))
del _mod, _n

# OVERRIDES is what respond() dispatches on, and it is built HERE - after every
# handler group has been merged into DYNAMIC_OVERRIDES. It used to be built right
# after the DYNAMIC_OVERRIDES literal, which was correct until the decoration and
# mini-game handlers moved into their own modules and merged in below: the snapshot
# had already been taken, so ~30 routes silently answered an empty model. Nothing
# caught it, because route_coverage was reading DYNAMIC_OVERRIDES rather than the
# table that actually dispatches.
#
# Pure-literal routes (no st/body dependency) load straight from JSON; wrap each in a
# lambda returning the same shared dict (build_model only reads it via .update(),
# never mutates it, so no copy is needed).
OVERRIDES = {path: (lambda b, st, r=resp: r) for path, resp in STATIC_OVERRIDES.items()}
OVERRIDES.update(DYNAMIC_OVERRIDES)
assert set(DYNAMIC_OVERRIDES) <= set(OVERRIDES), "a handler group registered too late"

for _r in ROUTE_MODELS:
    app.add_api_route(_r, make_handler(_r), methods=["GET", "POST", "PUT"])

@app.get("/x2/xls.cgi")
async def cdn_xls_cgi(request: Request):
    """Handle CDN patch-query requests: /x2/xls.cgi?p=XXXX&q=base64data"""
    host = request.headers.get("host", "?")
    q = request.query_params.get("q", "")
    p = request.query_params.get("p", "")
    admin_log(f"[{host}] CDN XLS query p={p} q_len={len(q)}")
    return Response(PATCH_FOLDER.encode(), media_type="text/plain")

@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT"])
async def catch_all(full_path: str, request: Request):
    return await respond("/" + full_path, request)
