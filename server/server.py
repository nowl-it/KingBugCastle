#!/usr/bin/env python3
"""KGC private server emulator.

Reconstructed from il2cpp dump (RestAPI class + Awesomepiece.Model + route strings).
Implements the full login critical path so the client boots past the title screen,
plus a generic dispatcher that returns a wire-valid ResponseModel for all ~284
endpoints. Player save is a single editable JSON in state/player.json with full
state persistence for cards, decks, inventory, missions, and game loop.

Run:  uvicorn server:app --host 0.0.0.0 --port 8080
"""
import asyncio, contextvars, json, time, copy, secrets, datetime, pathlib, hashlib, os, sys
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
import colosseum
import player_events
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, HTMLResponse
from Crypto.Cipher import AES

AES_KEY = b"b53019bb76da6b34"

LOG_BUF = []

def admin_log(*args):
    msg = datetime.datetime.now().strftime("%H:%M:%S") + " " + " ".join(str(a) for a in args)
    LOG_BUF.append(msg)
    if len(LOG_BUF) > 500:
        LOG_BUF[:] = LOG_BUF[-400:]
    print(*args, file=sys.stderr)

def aes_encrypt(payload: dict) -> bytes:
    # Space-pad to 16-byte blocks (NOT PKCS7): the client's Newtonsoft JSON reader
    # throws "Additional text after JSON" on non-whitespace trailing bytes, but
    # tolerates trailing spaces. (Confirmed via JsonReaderException at runtime.)
    raw = json.dumps(payload).encode()
    if len(raw) % 16:
        raw += b" " * (16 - len(raw) % 16)
    return AES.new(AES_KEY, AES.MODE_ECB).encrypt(raw)

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

ROOT = pathlib.Path(__file__).parent
G = ROOT / "generated"
MODELS = json.loads((G / "models.json").read_text())
ROUTE_MODELS = json.loads((G / "route_models.json").read_text())
ROUTE_MODELS.update({
    "/treasure": {"method": "Treasure", "response": "TreasureResultResponseModel"},
    "/treasure/equip": {"method": "TreasureEquip", "response": "TreasureResultResponseModel"},
    "/treasure/add-exp": {"method": "TreasureAddExp", "response": "TreasureResultResponseModel"},
    "/treasure/dismantle": {"method": "TreasureDismantle", "response": "TreasureResultResponseModel"},
    "/treasure/release-equip": {"method": "TreasureReleaseEquip", "response": "TreasureResultResponseModel"},
    "/treasure/set-state": {"method": "TreasureSetState", "response": "TreasureResultResponseModel"},
    "/treasure/overcome": {"method": "TreasureOvercome", "response": "TreasureResultResponseModel"},
})
# map_routes.py pairs a route with a RestAPI method by name similarity and drops
# what it cannot score, so 70 real v171 routes had no model and were answered with a
# bare ResponseModel - the right envelope, none of the fields the client reads.
# data/route_models_extra.json hand-maps them; route_coverage.py reports the gap.
ROUTE_MODELS.update({
    p: {"method": v.get("_method"), "response": v["response"]}
    for p, v in json.loads((ROOT / "data" / "route_models_extra.json").read_text()).items()
    if not p.startswith("_")
})
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Player state lives in state/players.db (SQLite, WAL). The old JSON files are
# imported once and then left alone as a cold backup - they are NOT read again.
_migrated = playerdb.migrate_from_json(STATE_DIR)
if _migrated:
    admin_log(f"[state] migrated {_migrated} player(s) from JSON into {playerdb.DB_PATH.name}")

# All response data that isn't request-time-computed logic lives under data/ as
# JSON - editable without touching code, and the shape mirrors what a future
# SQL migration would look like (one table/row per file/key).
DATA_DIR = ROOT / "data"
RCFG = json.loads((DATA_DIR / "response_config.json").read_text())
STATIC_OVERRIDES = json.loads((DATA_DIR / "static_overrides.json").read_text())
ITEM_TEMPLATES = json.loads((DATA_DIR / "item_templates.json").read_text())

PATCH_FOLDER = RCFG["server"]["patchFolder"]
SERVER_VERSION = RCFG["server"]["serverVersion"]

def _content_gate(version):
    """Master-data MinVersion cutoff, derived from serverVersion.

    MinVersion is a 6-digit build code: "170.1.00" -> 170100, "171.0.00" -> 171000.
    An entry above the gate is content the deployed client cannot render yet, so it
    is filtered out of the hero/artifact/treasure/shop listings.

    This used to be three separate `> 170100` literals, which stayed behind when the
    build moved to 171.0.00 - the server advertised v171 while hiding every v171
    hero, artifact and treasure from its own listings. Deriving it means the gate
    cannot drift from the version again. KGC_CONTENT_GATE overrides it, which is
    required if you deploy the v170.1.00 client against this server."""
    env = os.environ.get("KGC_CONTENT_GATE")
    if env:
        return int(env)
    parts = [int(p) for p in version.split(".")]
    parts += [0] * (3 - len(parts))
    return parts[0] * 1000 + parts[1] * 100 + parts[2]

CONTENT_GATE = _content_gate(SERVER_VERSION)
admin_log(f"[gate] serverVersion {SERVER_VERSION} -> content gate {CONTENT_GATE}")

def next_reset_iso(days=1):
    """Next UTC-midnight rollover boundary, `days` out.

    `tomorrow` / `nextWeek` are DERIVED, never served from stored state.
    Scene_Lobby.Update polls `if (now >= playerData.tomorrow_) FetchNextDay()`
    once a second, and FetchNextDay re-runs the whole login + lobby fetch chain.
    A stored value is frozen at account-creation time, so the check goes
    permanently true and the client re-logins at 1 Hz forever.
    """
    midnight = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight + datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def now_iso(delta_days=0, seconds=0):
    return (datetime.datetime.utcnow() + datetime.timedelta(days=delta_days, seconds=seconds)
            ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

# Set per request from the `accesstoken` header (see resolve_player middleware).
# None = no session -> fall back to the admin-selected active player, which is
# what every single-player setup and the whole pre-login boot sequence relies on.
CURRENT_UID = contextvars.ContextVar("current_uid", default=None)

# Auto-creating a save for an unknown account id is right for a real multi-player
# server and wrong for a single-player one, where a reinstall or a cleared cache
# would mint a fresh empty save and look exactly like losing your progress.
MULTIPLAYER = os.environ.get("KGC_MULTIPLAYER") == "1"
MAX_PLAYERS = int(os.environ.get("KGC_MAX_PLAYERS") or 200)
admin_log(f"[state] identity mode: {'multiplayer (account id -> own save)' if MULTIPLAYER else 'single-player (everyone -> active save)'}")

def load_state():
    """State of the player this request belongs to.

    Identity comes from the `accesstoken` header, bound to a uid at login. With
    no session (pre-login boot, CDN, admin UI) this is the active player.
    """
    uid = CURRENT_UID.get() or playerdb.active()
    if uid:
        st = playerdb.load(uid)
        if st is not None:
            return st
    st = copy.deepcopy(DEFAULT_PLAYER)
    uid = st.get("uid", "dev-0001")
    playerdb.save(uid, st)
    playerdb.set_active(uid)
    return st

def save_state(st):
    playerdb.save(st.get("uid", "dev-0001"), st)

def patch_state(st, updates):
    st.update(updates)
    save_state(st)

# Prefer user-edited master data in server/xml_live, then CDN-synced.
_XML_LIVE = ROOT / "xml_live"
XML_DIR = _XML_LIVE if _XML_LIVE.is_dir() else ROOT.parent / "xml" / PATCH_FOLDER
assert XML_DIR.is_dir(), f"XML master data not found: {XML_DIR}"
admin_log(f"[xml] master data dir: {XML_DIR} ({len(list(XML_DIR.iterdir()))} files)")

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
# level 30 >= 16 so potentialTier=1 (awakened) is correct. An earlier retest
# blamed potentialTier=1 for the DeckPanel boot crash, but Ghidra (2026-07-02,
# arm32 dump.cs FUN_01e1a018) proved the real cause was deck length vs.
# DeckPanel.currentDeck's fixed 6-slot UI array (see DEFAULT_DECKS below) -
# potentialTier was never the culprit, that test just happened to run before
# the deck-length fix was in place.
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

def _uid_for_login(login_id, prev_token):
    """Which player a login belongs to.

    Order: known account id -> the session the presented token already belongs to
    (/auth/login carries a token, not an id) -> new player, but only in
    multiplayer mode -> the active player.
    """
    uid = playerdb.uid_for_login(login_id) or playerdb.uid_for_token(prev_token)
    if uid and playerdb.load(uid) is not None:
        return uid
    if MULTIPLAYER and login_id:
        uid = "p-" + hashlib.sha1(login_id.encode()).hexdigest()[:12]
        if playerdb.load(uid) is None:
            # The account id is client-supplied and unauthenticated, so anyone who
            # can reach /auth/register can mint saves. Cap it - without this a loop
            # fills the disk.
            if playerdb.count() >= MAX_PLAYERS:
                admin_log(f"[auth] refused new player: at KGC_MAX_PLAYERS={MAX_PLAYERS}")
                return playerdb.active()
            st = copy.deepcopy(DEFAULT_PLAYER)
            st["uid"] = uid
            st["accountCreatedAt"] = now_iso(0)
            playerdb.save(uid, st)
            admin_log(f"[auth] new player {uid}")
        playerdb.bind_login(login_id, uid)
        return uid
    return playerdb.active()

def r_login(body, st):
    # All date-ish fields must be non-null parseable strings: HandleAuthResponse
    # does DateTime.Parse on expiredAt / serverTime / blockedUntilAt -> null throws
    # ArgumentNullException.
    login_id = CURRENT_LOGIN_ID.get() or body.get("id") or ""
    # No bind_login() here: in single-player mode _uid_for_login falls back to the
    # ACTIVE player, and recording that as "account X owns save Y" would pin every
    # account that ever logged in to it - permanently, so a later switch to
    # multiplayer would still hand them all the same save. Only the multiplayer
    # branch, which actually owns the account, writes that mapping.
    uid = _uid_for_login(login_id, body.get("token"))
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
        "loginId": uid,
    }



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
    preset = body.get("preset", 0)
    levels = body.get("levels", [0] * 6)
    presets = _get_building_data(st)
    while len(presets) <= preset:
        presets.append({"buildingLevels": [0]*6})
    presets[preset]["buildingLevels"] = levels
    st["buildingPresets"] = presets
    save_state(st)
    return {"buildingPoint": st.get("buildingPoints", 25), "buildingData": presets}

def r_building_reset_point(body, st):
    preset = body.get("preset", 0)
    presets = _get_building_data(st)
    while len(presets) <= preset:
        presets.append({"buildingLevels": [0]*6})
    presets[preset]["buildingLevels"] = [0] * 6
    st["buildingPresets"] = presets
    save_state(st)
    return {"buildingPoint": st.get("buildingPoints", 25), "buildingData": presets}



# ProfilePanel.ReloadChallenge indexes invasion/difficulty records per
# unlockedDifficulty tier (up to 15) -> a shorter list throws
# IndexOutOfRangeException, aborting Reload() before name/avatar/clan/date ever
# get set (root cause of the whole profile-popup bug batch).
_PC = RCFG["player"]
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
        "kingPostfix": 0, "castlePostfix": 0,
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
    theme = body.get("theme", 1)
    stage = body.get("stage", 1)
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
    gid = body.get("gameId", "")
    win = body.get("win", False)
    theme = body.get("theme", 1)
    stage = body.get("stage", 1)
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
            cs["bestDifficulty"] = max(cs["bestDifficulty"], int(body["difficulty"]))
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
    unit_id = body.get("unitId", 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["potentialTier"] = min(20, cards[key].get("potentialTier", 0) + 1)
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": 1})
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": c["potentialTier"],
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": c["potentialTier"],
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }

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
    preset_idx = body.get("presetIdx", 0)
    decks = st.setdefault("decks", list(DEFAULT_DECKS))
    admin_log(f"[DECK/SET] preset={preset_idx} body_keys={list(body.keys())}")
    deck, potential = _pad_deck(body.get("deck", []), body.get("potential", []))
    first_comer = body.get("firstComerIndex", 0)
    while len(decks) <= preset_idx:
        decks.append({"deck": [0] * DECK_SLOTS, "potential": [0] * DECK_SLOTS, "firstComerIndex": 0})
    decks[preset_idx] = {"deck": deck, "potential": potential, "firstComerIndex": first_comer}
    st["decks"] = decks
    save_state(st)
    return {"deckInfos": [{"deck": d["deck"], "potential": d.get("potential", []),
                           "firstComerIndex": d.get("firstComerIndex", 0)} for d in decks],
            "defaultPotentialInfo": st.get("defaultPotential", {"unit": [], "potential": []})}

def r_deck_set_potential(body, st):
    preset_idx = body.get("presetIdx", 0)
    idx = body.get("idx", 0)
    unit_id = body.get("unitId", 0)
    potential = body.get("potential", 0)
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
    potentials = body.get("potentials", [])
    st["defaultPotential"] = {"unit": [p.get("unitId", 0) for p in potentials],
                               "potential": [p.get("potential", 0) for p in potentials]}
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
            if rt == "CardOrSoul":
                # Already own the hero -> the copy converts to soul, same as live.
                rt = "UnitSoul" if str(r["id"]) in st.get("cards", {}) else "Unit"
            if rt not in ("Accessory", "Treasure"):
                _grant_reward(st, rt, r["id"], r["count"])
        rewards += got
    return rewards

def _reward_list_data(rewards):
    return {"rewardList": rewards, "artifactResult": None,
            "treasureResult": None, "accessoryResult": None}

def r_use_inventory(body, st):
    """Consume a plain inventory item.

    InventoryItems.xml carries no effect payload (only tooltip/category metadata), and
    the client applies the visible effect itself off that metadata, so the server's job
    is to spend the item and hand back the authoritative inventory.
    ponytail: no per-item effect table; add one if an item turns out to need server state."""
    item_id = body.get("itemID") or body.get("itemId") or 0
    _take_item(st, item_id, max(1, body.get("count") or 1))
    save_state(st)
    return {"playerHeart": st.get("heart", 0), "eventFlag": 0,
            "inventoryItems": _inventory_models(st)}

def r_use_reward_box(body, st):
    item_id = body.get("itemId") or body.get("itemID") or 0
    rewards = _open_reward_box(st, item_id, body.get("selectIdx"),
                               max(1, body.get("count") or 1))
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

def _shop_buys(st):
    """itemId (as a string key, so it survives a JSON round-trip) -> times bought."""
    return st.setdefault("shopBuys", {})

def r_shop(body, st):
    """List the shop, or buy from it.

    GetShop and BuyShopItem share the /shop path (GET lists, POST buys) - the same
    split /accessory uses. Rather than depend on the verb, which respond() does not
    pass down, a request carrying an itemId is a purchase; a bare one is a listing.
    That is also self-correcting if the client ever POSTs /shop just to refresh."""
    base = dict(STATIC_OVERRIDES["/shop"])
    if body.get("itemId"):
        base.update(_shop_buy(body, st))
        save_state(st)
    base.update(shop.build(CONTENT_GATE, _shop_buys(st), now_iso(0), XML_DIR))
    base["nextRefreshTime"] = next_reset_iso(1)
    base["playerGold"] = st.get("gold", 0)
    base["playerCash"] = st.get("cash", 0)
    base["playerHeart"] = st.get("heart", 0)
    return base

def _shop_buy(body, st):
    """Charge for a shop item and grant it. Returns the BuyResponseModel-ish extras.

    Real-money items are granted without charging: there is no store behind this
    server, so refusing them would make every package permanently unbuyable."""
    item_id = int(body.get("itemId") or 0)
    amount = max(1, int(body.get("buyAmount") or 1))
    el = shop.find(item_id, XML_DIR)
    if el is None:
        admin_log(f"[shop] refused: item {item_id} is not in ShopItems.xml")
        return {"msg": "no such shop item", "soldOut": True}

    buys = _shop_buys(st)
    bought = buys.get(str(item_id), 0)
    limit = shop._int(el, "BuyLimit", -1)
    if limit >= 0 and bought + amount > limit:
        amount = max(0, limit - bought)
        if amount == 0:
            admin_log(f"[shop] refused: item {item_id} at its BuyLimit {limit}")
            return {"msg": "buy limit reached", "soldOut": True}

    kind, cur_id, unit_price = shop.price_of(el)
    cost = unit_price * amount
    if kind == "gold" and st.get("gold", 0) < cost:
        return {"msg": "not enough gold", "soldOut": False}
    if kind == "cash" and st.get("cash", 0) < cost:
        return {"msg": "not enough cash", "soldOut": False}
    if kind == "item" and _item_count(st, cur_id) < cost:
        return {"msg": f"not enough of item {cur_id}", "soldOut": False}

    if kind == "gold":
        st["gold"] = st.get("gold", 0) - cost
        bump(st, "useGold", cost)
    elif kind == "cash":
        st["cash"] = st.get("cash", 0) - cost
    elif kind == "item":
        _take_item(st, cur_id, cost)
    shop_counter = {"ArenaShop": "useArenaShop", "ClanShop": "useClanShop",
                    "EventShop": "useEventShop"}.get(el.findtext("Type"))
    if shop_counter:
        bump(st, shop_counter, amount)

    rewards = []
    for r in shop.rewards_of(el):
        r = {**r, "count": r["count"] * amount}
        # Artifact/Treasure/Skin are reported for the reward popup but not written
        # into state - the same policy the mail rewards follow.
        if r["type"] not in ("Artifact", "Treasure", "Skin"):
            _grant_reward(st, r["type"], r["id"], r["count"])
        rewards.append(r)
    buys[str(item_id)] = bought + amount
    admin_log(f"[shop] bought {item_id} x{amount} for {cost} {kind} -> {len(rewards)} rewards")
    return {"gachaRewardResponseData": _reward_list_data(rewards),
            "inventoryItems": _inventory_models(st), "soldOut": False}

def r_shop_refresh(body, st):
    """Refreshing the daily shop clears its per-item buy counts, which is what makes
    the daily items buyable again."""
    for sid in list(_shop_buys(st)):
        el = shop.find(sid, XML_DIR)
        if el is not None and el.findtext("Type") == "DailyShop":
            _shop_buys(st).pop(sid, None)
    save_state(st)
    return r_shop({}, st)

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
    theme = int(body["theme"])
    rewards = _invasion_claim(st, theme, int(body.get("difficulty") or 1),
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
    idx = body.get("index", body.get("rewardIdx"))
    want = [int(idx)] if idx is not None else range(len(entries))
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
    for mid in ids:
        m = catalog.get(int(mid))
        if m is None or int(mid) in claimed:
            continue
        if missions.progress(m, st, counters(st)) < missions.goal_value(m):
            continue
        for r in missions.rewards_of(m):
            out.append(_grant_mission_reward(st, r))
        claimed.add(int(mid))
        bump(st, "missionClear")
    st["claimedMissions"] = sorted(claimed)
    save_state(st)
    return out

def r_mission_reward_all(body, st):
    """Claim missions. Despite the name this is also the single-mission claim.

    GetMissionRewardAll takes a `missionIdList` (MissionRewardRequestModel), so the
    client sends one id to claim one and several to claim a batch - there is no
    separate per-mission route. An empty list means "everything I can claim"."""
    ids = (body.get("missionIdList") or body.get("missionIds")
           or ([body["missionId"]] if body.get("missionId") else [])
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
    target_id = body.get("targetId", 0)
    index = body.get("index", 0)
    deck_preset = body.get("deckPreset", 0)
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

def r_clan(body, st):
    # clan:null -> GameManager.clan stays null -> HasClan() false -> profile's
    # clanInfoBox hidden. A fake clan object here (even self-authored) makes
    # GameManager.HasClan() true for every account, which is wrong for a fresh
    # god account that never joined one.
    return {"clan": None, "role": 0, "requestSupportCooltime": now_iso(-1)}

# --- Clan ---------------------------------------------------------------------
# A private server has one player, so it has a clan of one. All 28 remaining clan
# routes answered an empty model: the clan could be created but never read back,
# renamed, chatted in, or left.
#
# Constants.ClanRole: Requested -1, None 0, Member1..3 1..3, SubMaster 9, Master 10.
# The old /clan/create lambda handed the founder role 1, so the client hid every
# management control from the person who had just made the clan.
CLAN_MASTER = 10
CLAN_REQUESTED = -1

def _clan(st):
    return st.get("clan")

def _clan_new(st, body):
    c = dict(RCFG["clanCreate"])
    c.update({
        "id": 1,
        "name": (body.get("name") or "Clan").strip(),
        "markId": int(body.get("markId", body.get("mark", 0)) or 0),
        "language": int(body.get("language", 0) or 0),
        "keywords": list(body.get("keywords") or []),
        "joinType": int(body.get("joinType", 0) or 0),
        "intro": body.get("intro", ""),
        "notice": body.get("notice", ""),
        "tag": body.get("tag", ""),
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
            "seqId": c["seq"], "type": int(body.get("type", 0) or 0),
            "accountId": st.get("accountId", _PC["defaults"]["accountId"]),
            "sender": st.get("name", _PC["defaults"]["name"]),
            "message": msg, "targetUnit": int(body.get("targetUnit", 0) or 0),
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
        seq = int(body.get("seqId", body.get("id", 0)) or 0)
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
        role = int(body.get("role", 0) or 0)
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
        idx = int(body.get("index", 0) or 0)
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
        idx = int(body.get("index", -1))
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
        c["raidDamage"] = max(c.get("raidDamage", 0), int(body.get("damage", 0) or 0))
        save_state(st)
    return dict(STATIC_OVERRIDES["/clan/raid"])

def r_clan_support(body, st):
    """Support is one member handing another a hero. With one member there is nobody
    to ask and nobody to answer, so the lists stay empty and the cooldown stays clear
    rather than pretending a request is pending."""
    return {"supports": [], "requestSupportCooltime": now_iso(-1),
            "supportCompletedModel": None}


def r_pass(body, st):
    c = RCFG["pass"]
    out = {"seasonStartAtDate": now_iso(c["seasonStartDayOffset"]),
           "seasonUntilAtDate": now_iso(c["seasonUntilDayOffset"]),
           "nextSeasonStartAtDate": now_iso(c["nextSeasonStartDayOffset"])}
    out.update(c["fixed"])
    return out

def _terr(st):
    """The player's territory, seeded with a level 1 town hall on first access.

    Level 0 is the "not built yet" placeholder: starting there gives a stored-labor
    cap of 0, so the player could never bank the labor a first upgrade costs and the
    plot would be permanently stuck."""
    t = st.setdefault("territory", {})
    if "buildings" not in t:
        t.update({"buildings": territory.starting_layout(XML_DIR), "storedLabor": 0,
                  "lastLaborAt": now_iso(0), "stored": [], "hunting": [],
                  "levelSync": [], "tradeShop": [], "equippedSkin": 0})
    return t

def _terr_labor(st):
    """Current labor, rebased so the accrual clock restarts from now."""
    t = _terr(st)
    labor, _ = territory.accrued_labor(t.get("storedLabor", 0), t.get("lastLaborAt", ""),
                                       t["buildings"], xml_dir=XML_DIR)
    t["storedLabor"] = labor
    t["lastLaborAt"] = now_iso(0)
    return labor

def _terr_at(t, pos):
    return next((b for b in t["buildings"] if b["posIndex"] == int(pos)), None)

def r_territory_fetch(body, st):
    t = _terr(st)
    labor = _terr_labor(st)
    sk, default = territory.skins(CONTENT_GATE, XML_DIR)
    if not t.get("equippedSkin"):
        t["equippedSkin"] = default
    save_state(st)
    return {"labor": labor, "storedLabor": labor,
            "buildingDatas": t["buildings"], "lastLaborAt": t["lastLaborAt"],
            "statBuffPers": t.get("statBuffPers", []),
            "storedBuildings": t["stored"], "playerHuntingData": t["hunting"],
            "playerLevelSyncData": t["levelSync"],
            "tickets": [], "playerTradeShopItemData": t["tradeShop"],
            "passEndedAt": "", "skins": sk, "equippedSkin": t["equippedSkin"],
            # The lobby's own territory summary still reads these two.
            "buildingPoints": st.get("buildingPoints", 25),
            "maxLabor": territory.max_stored_labor(t["buildings"], XML_DIR)}

def r_territory(body, st):
    return r_territory_fetch(body, st)

def _terr_pay(st, bid):
    """Charge a build/upgrade. Returns None on success, else why it was refused."""
    c = territory.cost(bid, XML_DIR)
    labor = _terr_labor(st)
    if labor < c["labor"]:
        return f"not enough labor ({labor} < {c['labor']})"
    if st.get("gold", 0) < c["gold"]:
        return f"not enough gold ({st.get('gold', 0)} < {c['gold']})"
    _terr(st)["storedLabor"] = labor - c["labor"]
    st["gold"] = st.get("gold", 0) - c["gold"]
    return None

def r_territory_build(body, st):
    """Place a new building, or upgrade the one already at that slot.

    /territory/build carries an id, /territory/upgrade-building only a posIndex - both
    land here because both resolve to "the next level of what belongs at this slot"."""
    t = _terr(st)
    pos = int(body.get("posIndex", 0))
    existing = _terr_at(t, pos)
    if body.get("id"):
        bid = int(body["id"])
    elif existing:
        bid = existing["buildingId"] + 1
        if territory.level(bid) > territory.max_level(bid, XML_DIR):
            return {**r_territory_fetch({}, st), "msg": "already at max level"}
    else:
        return {**r_territory_fetch({}, st), "msg": "nothing to upgrade at this slot"}

    if bid not in territory.buildings(XML_DIR):
        return {**r_territory_fetch({}, st), "msg": f"no such building {bid}"}
    why = _terr_pay(st, bid)
    if why:
        return {**r_territory_fetch({}, st), "msg": why}

    secs = 0 if body.get("immediately") else territory.upgrade_seconds(bid, XML_DIR)
    end = now_iso(0) if not secs else (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=secs)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if existing:
        existing["buildingId"] = bid
        existing["upgradeEndAt"] = end
    else:
        t["buildings"].append({"buildingId": bid, "posIndex": pos, "assignedUnits": [],
                               "upgradeEndAt": end, "lastTokenAt": "", "data": ""})
    save_state(st)
    admin_log(f"[territory] slot {pos} -> building {bid}, done at {end}")
    out = r_territory_fetch({}, st)
    out.update({"buildingCore": 0, "townHallCore": 0, "gold": st.get("gold", 0),
                "cash": st.get("cash", 0), "seasonalToken": 0, "refreshRet": None})
    return out

def r_territory_upgrade_now(body, st):
    return r_territory_build({**body, "immediately": True}, st)

def r_territory_remove(body, st):
    t = _terr(st)
    b = _terr_at(t, body.get("posIndex", -1))
    if b:
        t["buildings"].remove(b)
        save_state(st)
    return r_territory_fetch({}, st)

def r_territory_store(body, st):
    """Move a building off the plot into storage. Only <CanStore> ones may go."""
    t = _terr(st)
    b = _terr_at(t, body.get("posIndex", -1))
    if b and territory.can_store(b["buildingId"], XML_DIR):
        t["buildings"].remove(b)
        t["stored"].append({"buildingId": b["buildingId"], "count": 1})
        save_state(st)
    return r_territory_fetch({}, st)

def r_territory_unstore(body, st):
    t = _terr(st)
    bid = int(body.get("buildingId", 0))
    pos = int(body.get("posIndex", 0))
    row = next((s for s in t["stored"] if s["buildingId"] == bid), None)
    if row and _terr_at(t, pos) is None:
        row["count"] -= 1
        if row["count"] <= 0:
            t["stored"].remove(row)
        t["buildings"].append({"buildingId": bid, "posIndex": pos, "assignedUnits": [],
                               "upgradeEndAt": "", "lastTokenAt": "", "data": ""})
        save_state(st)
    return r_territory_fetch({}, st)

def r_territory_replace(body, st):
    """Swap two slots. Both may be empty, one, or neither."""
    t = _terr(st)
    a, b = _terr_at(t, body.get("posIndex", -1)), _terr_at(t, body.get("targetPosIndex", -1))
    if a is not None and b is not None:
        a["posIndex"], b["posIndex"] = b["posIndex"], a["posIndex"]
    elif a is not None and body.get("targetPosIndex") is not None:
        a["posIndex"] = int(body["targetPosIndex"])
    save_state(st)
    return r_territory_fetch({}, st)

def r_territory_collect_labor(body, st):
    """Bank the accrued labor. `amount` moves it into the spendable pool."""
    labor = _terr_labor(st)
    save_state(st)
    return {"labor": labor, "storedLabor": labor}

def r_territory_assign(body, st):
    """Assign heroes to a building, capped by its <MaxUnitAssignCount>.

    A hero may only work one building at a time, so assigning them here removes them
    from wherever they were - otherwise the same hero could stack the labor bonus on
    every building at once."""
    t = _terr(st)
    b = _terr_at(t, body.get("posIndex", -1))
    if b is None:
        return r_territory_fetch({}, st)
    units = [int(u) for u in (body.get("unitIds") or body.get("units") or [])]
    cap = territory.spec(b["buildingId"], "MaxUnitAssignCount", 0, XML_DIR)
    units = units[:cap]
    for other in t["buildings"]:
        if other is not b:
            other["assignedUnits"] = [u for u in other.get("assignedUnits", [])
                                      if u not in units]
    b["assignedUnits"] = units
    save_state(st)
    out = r_territory_fetch({}, st)
    out["assignedUnits"] = units
    return out

def r_territory_hunting_start(body, st):
    t = _terr(st)
    hid = int(body.get("huntingId", 0))
    h = territory.huntings(XML_DIR).get(hid)
    if h is None:
        return {**r_territory_fetch({}, st), "msg": f"no such hunting {hid}"}
    t["hunting"] = [x for x in t["hunting"] if x["huntingId"] != hid]
    t["hunting"].append({"huntingId": hid, "specialCount": 0, "normalCount": 0,
                         "passApplied": False, "shortenPer": 0.0,
                         "startAt": now_iso(0), "endAt": now_iso(0)})
    save_state(st)
    return {**r_territory_fetch({}, st), "playerHuntingData": t["hunting"]}

def r_territory_hunting_end(body, st):
    """Finish a run and pay it out. Ending one that was never started pays nothing."""
    t = _terr(st)
    hid = int(body.get("huntingId", 0))
    row = next((x for x in t["hunting"] if x["huntingId"] == hid), None)
    if row is None:
        return {**r_territory_fetch({}, st), "rewardListData": _reward_list_data([])}
    rewards = []
    for r in territory.hunting_rewards(hid, XML_DIR):
        if r["type"] in ("Gold", "Cash", "Heart", "Item"):
            _grant_reward(st, r["type"], r["id"], r["count"])
        rewards.append(r)
    t["hunting"].remove(row)
    save_state(st)
    admin_log(f"[territory] hunting {hid} -> {len(rewards)} rewards")
    return {**r_territory_fetch({}, st), "rewardListData": _reward_list_data(rewards)}

def r_territory_hunting_stop(body, st):
    t = _terr(st)
    hid = int(body.get("huntingId", 0))
    t["hunting"] = [x for x in t["hunting"] if x["huntingId"] != hid]
    save_state(st)
    return r_territory_fetch({}, st)

def r_territory_trade_buy(body, st):
    """Buy from the trade shop. Priced in inventory items, per currency index."""
    _, items = territory.trade_shop(xml_dir=XML_DIR)
    uid = int(body.get("uid", body.get("itemId", 0)))
    item = next((i for i in items if i["id"] == uid or i["itemId"] == uid), None)
    if item is None:
        return {**r_territory_fetch({}, st), "msg": f"no such trade item {uid}"}
    t = _terr(st)
    row = next((r for r in t["tradeShop"] if r["uid"] == item["id"]), None)
    bought = row["buyCount"] if row else 0
    if item["buyLimit"] >= 0 and bought >= item["buyLimit"]:
        return {**r_territory_fetch({}, st), "msg": "buy limit reached"}
    currencies, _ = territory.trade_shop(xml_dir=XML_DIR)
    idx = int(body.get("currencyIndex", item["prices"][0]["index"]))
    price = next((p["price"] for p in item["prices"] if p["index"] == idx),
                 item["prices"][0]["price"])
    cur = next((c["id"] for c in currencies if c["index"] == idx), 0)
    if _item_count(st, cur) < price:
        return {**r_territory_fetch({}, st), "msg": f"not enough of item {cur}"}
    _take_item(st, cur, price)
    _grant_reward(st, "Item", item["itemId"] or item["id"], 1)
    if row:
        row["buyCount"] = bought + 1
    else:
        t["tradeShop"].append({"uid": item["id"], "itemVersion": 0, "buyCount": 1})
    save_state(st)
    return {**r_territory_fetch({}, st),
            "rewardListData": _reward_list_data(
                [{"type": "Item", "id": item["itemId"] or item["id"], "count": 1}])}

def r_territory_equip_skin(body, st):
    t = _terr(st)
    sk, _ = territory.skins(CONTENT_GATE, XML_DIR)
    sid = int(body.get("skinId", body.get("id", 0)))
    if sid in sk:
        t["equippedSkin"] = sid
        save_state(st)
    return r_territory_fetch({}, st)

def r_territory_stat_buffs(body, st):
    return {"statBuffPers": _terr(st).get("statBuffPers", [])}


# --- Decoration: flags, name tags, map skins, login skins, advisors -----------
# The tab used to be one fixed payload with five empty lists. Every other kind of
# owned content is granted in full on this server, so the cosmetics are too; only
# what is equipped is per-player state.

def _deco(st):
    d = st.setdefault("decoration", {})
    d.setdefault("flag", {"flagId": 0, "season": 0})
    d.setdefault("nameTag", 0)
    d.setdefault("favoriteMapSkins", [])
    d.setdefault("mapSkin", decoration.default_id("mapSkins", CONTENT_GATE, XML_DIR))
    d.setdefault("loginSkin", decoration.default_id("loginSkins", CONTENT_GATE, XML_DIR))
    d.setdefault("advisor", decoration.DEFAULT_ADVISOR)
    d.setdefault("contracts", {})
    return d

def _deco_flags(st):
    d = _deco(st)
    return {"flagsModel": [{"flagId": i, "season": 0}
                           for i in decoration.ids("flags", CONTENT_GATE, XML_DIR)],
            "equipedFlag": dict(d["flag"])}

def _deco_nametags(st):
    d = _deco(st)
    return {"nameTagsModel": [{"nameTagId": i}
                              for i in decoration.ids("nameTags", CONTENT_GATE, XML_DIR)],
            "equippedNameTag": {"nameTagId": d["nameTag"]}}

def _deco_advisors(st):
    """One AdvisorInfo per advisor. An advisor with no contract row still appears -
    the panel lists what exists and reads contractUntilAt to decide the state, so
    omitting it would hide the advisor rather than show it as un-contracted."""
    d = _deco(st)
    out = []
    for i in decoration.ids("advisors", CONTENT_GATE, XML_DIR):
        c = d["contracts"].get(str(i), {})
        out.append({"advisorId": i,
                    "contractUntilAt": c.get("until", ""),
                    "remainExtendCount": c.get("remainExtend", decoration.EXTEND_COUNT)})
    return {"advisorList": out}

def _deco_full(st):
    d = _deco(st)
    return {
        "flagInfo": _deco_flags(st),
        "nameTagInfo": _deco_nametags(st),
        "mapSkinInfo": {"mapSkinList": [
            {"skinId": i, "isFavorite": i in d["favoriteMapSkins"], "owned": True}
            for i in decoration.ids("mapSkins", CONTENT_GATE, XML_DIR)]},
        "advisorInfo": _deco_advisors(st),
        "loginSkinInfo": {"loginSkinList": decoration.ids("loginSkins", CONTENT_GATE, XML_DIR)},
        # appliedMapSkinData is Dictionary<int,int> and the only map-skin API taking a
        # second number is SetMapSkin(resMapSkin, probability), so it is read here as
        # skin id -> weight. One equipped skin is that skin at 100.
        "equipInfo": {"appliedMapSkinData": {str(d["mapSkin"]): 100},
                      "appliedAdvisor": d["advisor"],
                      "appliedLoginSkin": d["loginSkin"],
                      "loginSceneIllustData": decoration.login_scene(d["loginSkin"], XML_DIR)},
    }

def r_decoration(body, st):
    return _deco_full(st)

def r_flag_inventory(body, st):
    return _deco_flags(st)

def r_flag_set(body, st):
    d = _deco(st)
    fid = int(body.get("id", body.get("flagId", 0)) or 0)
    if fid in decoration.ids("flags", CONTENT_GATE, XML_DIR) or fid == 0:
        d["flag"] = {"flagId": fid, "season": int(body.get("season", 0) or 0)}
        save_state(st)
    return dict(d["flag"])

def r_nametag_inventory(body, st):
    return _deco_nametags(st)

def r_nametag_set(body, st):
    d = _deco(st)
    nid = int(body.get("id", body.get("nameTagId", 0)) or 0)
    if nid in decoration.ids("nameTags", CONTENT_GATE, XML_DIR) or nid == 0:
        d["nameTag"] = nid
        save_state(st)
    return {"nameTagId": d["nameTag"]}

def r_map_skin_equip(body, st):
    d = _deco(st)
    sid = int(body.get("skinId", 0) or 0)
    if sid in decoration.ids("mapSkins", CONTENT_GATE, XML_DIR):
        d["mapSkin"] = sid
        save_state(st)
    return _deco_full(st)

def r_map_skin_favorite(body, st):
    d = _deco(st)
    sid = int(body.get("skinId", 0) or 0)
    fav = d["favoriteMapSkins"]
    if body.get("set", True):
        if sid not in fav:
            fav.append(sid)
    elif sid in fav:
        fav.remove(sid)
    save_state(st)
    return _deco_full(st)

def r_map_skin_buy(body, st):
    """Owned already, so this only charges. Refusing outright would leave the buy
    button dead; charging keeps the token economy honest for anyone who cares."""
    sid = int(body.get("skinId", 0) or 0)
    if body.get("useSkinToken"):
        price = decoration.token_price("mapSkins", sid, "SkinTokenPrice", XML_DIR)
        if price and _item_count(st, decoration.SKIN_TOKEN) >= price:
            _take_item(st, decoration.SKIN_TOKEN, price)
    _deco(st)["mapSkin"] = sid if sid in decoration.ids("mapSkins", CONTENT_GATE, XML_DIR) \
        else _deco(st)["mapSkin"]
    save_state(st)
    return {"skinId": sid, "playerCash": st.get("cash", 0),
            "playerSkinToken": _item_count(st, decoration.SKIN_TOKEN),
            "playerPremiumSkinToken": 0}

def r_login_skin_equip(body, st):
    d = _deco(st)
    sid = int(body.get("skinId", 0) or 0)
    if sid in decoration.ids("loginSkins", CONTENT_GATE, XML_DIR):
        d["loginSkin"] = sid
        save_state(st)
    return decoration.login_scene(d["loginSkin"], XML_DIR) or {}

def r_login_scene_illust(body, st):
    return decoration.login_scene(_deco(st)["loginSkin"], XML_DIR) or {}

def _advisor_response(st, aid):
    c = _deco(st)["contracts"].get(str(aid), {})
    return {"advisorId": aid, "contractUntilAt": c.get("until", ""),
            "remainExtendCount": c.get("remainExtend", decoration.EXTEND_COUNT),
            "playerSkinToken": _item_count(st, decoration.SKIN_TOKEN),
            "advisorInfo": _deco_advisors(st)}

def r_advisor_contract(body, st):
    d = _deco(st)
    aid = int(body.get("advisorId", 0) or 0)
    if aid in decoration.ids("advisors", CONTENT_GATE, XML_DIR):
        price = decoration.token_price("advisors", aid, "ContractPrice", XML_DIR) or 0
        if price:
            _take_item(st, decoration.SKIN_TOKEN, min(price, _item_count(st, decoration.SKIN_TOKEN)))
        d["contracts"][str(aid)] = {"until": decoration.contract_until(),
                                    "remainExtend": decoration.EXTEND_COUNT}
        save_state(st)
    return _advisor_response(st, aid)

def r_advisor_extend(body, st):
    """Extends from the current expiry, not from now - extending early must not throw
    away the time already paid for."""
    d = _deco(st)
    aid = int(body.get("advisorId", 0) or 0)
    c = d["contracts"].get(str(aid))
    if c and c.get("remainExtend", 0) > 0:
        price = decoration.token_price("advisors", aid, "ExtendPrice", XML_DIR) or 0
        if price:
            _take_item(st, decoration.SKIN_TOKEN, min(price, _item_count(st, decoration.SKIN_TOKEN)))
        try:
            base = datetime.datetime.strptime(c["until"], "%Y-%m-%dT%H:%M:%S.000Z")
        except (KeyError, ValueError):
            base = None
        c["until"] = decoration.contract_until(base, decoration.EXTEND_DAYS)
        c["remainExtend"] -= 1
        save_state(st)
    return _advisor_response(st, aid)

def r_advisor_timeout(body, st):
    """The client reports a contract it believes has run out; drop it and fall back to
    the default advisor so the lobby is never left with nobody standing there."""
    d = _deco(st)
    aid = int(body.get("advisorId", 0) or 0)
    d["contracts"].pop(str(aid), None)
    if d["advisor"] == aid:
        d["advisor"] = decoration.DEFAULT_ADVISOR
    save_state(st)
    return _advisor_response(st, aid)

def r_advisor_equip(body, st):
    d = _deco(st)
    aid = int(body.get("advisorId", 0) or 0)
    if aid in decoration.ids("advisors", CONTENT_GATE, XML_DIR):
        d["advisor"] = aid
        save_state(st)
    return _deco_full(st)


# --- Dimension heroes ---------------------------------------------------------

def _card(st, unit_id):
    return st.setdefault("cards", {}).get(str(unit_id))

def r_card(body, st):
    """One card. The client asks for a single hero after upgrading it; answering with
    the whole roster is wrong shape, and answering with nothing blanks the panel."""
    unit_id = int(body.get("unitId", body.get("id", 0)) or 0)
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
    unit_id = int(body.get("unitId", 0) or 0)
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
    unit_id = int(body.get("unitId", 0) or 0)
    count = max(1, int(body.get("count", 1) or 1))
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

# --- Colosseum and Arena ------------------------------------------------------
# Twenty-two routes answered an empty model, so both PvP panels opened onto nothing:
# no match log, no statistics, no tier rewards to claim, and a score frozen at the
# 1000 the config seeds. What is missing is progression, not matchmaking - the live
# game plays these over a websocket against a real opponent, and there is no second
# player here, so the honest shape is a mode you play against the bot side that
# already exists client-side, with the server keeping score.
#
# Score, tier boundaries and every reward come from master data (colosseum.py). The
# server owns the running total; the client owns the battle.

# Both modes keep flat state keys so the leaderboards can read a score without
# knowing anything about this section.
_PVP_MODES = {
    "colosseum": {"prefix": "colosseum", "config": "colosseum"},
    "arena": {"prefix": "pvp", "config": "pvpInfo"},
}

def _pvp_state(st, mode):
    """(prefix, seeded config) for a mode, so a fresh save starts where the panel
    expects rather than at zero."""
    m = _PVP_MODES[mode]
    cfg = RCFG[m["config"]]["fixed"]
    p = m["prefix"]
    st.setdefault(p + "Score", cfg.get("score", 1000))
    st.setdefault(p + "Win", 0)
    st.setdefault(p + "Lose", 0)
    st.setdefault(p + "Claimed", [])
    st.setdefault(p + "Logs", [])
    return p, cfg

def _pvp_record(st, mode, win):
    """Apply one finished game. Returns the score delta so the result popup can
    show it - the client draws the arrow off this number, not off the new total."""
    p, _ = _pvp_state(st, mode)
    before = int(st[p + "Score"])
    after = colosseum.apply_result(before, win, XML_DIR)
    st[p + "Score"] = after
    st[p + "Win" if win else p + "Lose"] += 1
    st[p + "Tier"] = colosseum.tier_for(after, int(st.get(p + "Rank", 0)), XML_DIR)["id"]
    return after - before

def _pvp_log(st, mode, win, delta, extra=None):
    """Append a match to the mode's history, newest last, capped.

    The panel re-reads the whole list every time it opens, so it cannot grow
    without bound; 50 is more than the log view scrolls through."""
    p, cfg = _pvp_state(st, mode)
    logs = st[p + "Logs"]
    # The id counts every game ever played, not the length of the kept list -
    # deriving it from len() makes ids repeat as soon as the cap starts trimming,
    # and the log view keys its rows on them.
    st[p + "LogSeq"] = int(st.get(p + "LogSeq", 0)) + 1
    entry = {"logId": st[p + "LogSeq"], "myScoreDelta": delta,
             "semiSeason": cfg.get("semiSeason", 1),
             "startedAt": now_iso(0), "endedAt": now_iso(0), "win": win}
    entry.update(extra or {})
    logs.append(entry)
    del logs[:-50]
    return entry

def _pvp_deck_preview(st, mode, log_id=0):
    """A DeckInfoPreview row: who played, drawn beside each log line."""
    d = _PC["defaults"]
    deco = _deco(st)
    return {"logId": log_id, "accountId": st.get("accountId", d["accountId"]),
            "playerName": st.get("name", d["name"]),
            "castleName": st.get("castleName", d["castleName"]),
            "playerLevel": st.get("level", 1), "profileIcon": d["profileIconId"],
            "nameTagId": deco["nameTag"]}

def _pvp_card_infos(st):
    """CardInfo[] for the current deck. The opponent preview draws portraits from
    this, so an empty array is a row of blank slots."""
    out = []
    for unit_id in _deck_units(st):
        c = _card(st, unit_id) or {}
        out.append({"cardId": unit_id, "level": c.get("level", 1),
                    "skin": c.get("currentSkin", 0),
                    "potentialTier": c.get("potentialTier", 0),
                    "overcome": c.get("overcome", 0),
                    "dimensionLevel": c.get("dimensionLevel", 0),
                    "isLevelSyncApplied": False,
                    "treasure": None, "accessories": []})
    return out

def _colosseum_player(st):
    """ColosseumPlayerData for the one player there is."""
    d = _PC["defaults"]
    deco = _deco(st)
    return {"userId": str(st.get("accountId", d["accountId"])),
            "cardInfos": _pvp_card_infos(st),
            "potentials": [], "firstComerIndex": 0, "artifactModels": [],
            "buildingLevels": _get_building_data(st)[0].get("buildingLevels", []),
            "territoryStatBuffPers": [],
            "riftWeaponModels": [],
            "castleName": st.get("castleName", d["castleName"]),
            "userName": st.get("name", d["name"]),
            "profileIconId": d["profileIconId"], "nameTagId": deco["nameTag"],
            "mapSkinId": deco["mapSkin"], "flagModel": dict(deco["flag"]),
            "isBot": False, "roundData": [], "reported": False, "blinded": False}

def _pvp_deck_info(st, mode="arena"):
    """PvPDeckInfo - the arena's equivalent of the colosseum player block."""
    p, cfg = _pvp_state(st, mode)
    d = _PC["defaults"]
    deco = _deco(st)
    return {"id": 0, "season": cfg.get("season", 1), "score": int(st[p + "Score"]),
            "tier": colosseum.tier_for(int(st[p + "Score"]), 0, XML_DIR)["id"],
            "accountId": st.get("accountId", d["accountId"]),
            "playerName": st.get("name", d["name"]),
            "castleName": st.get("castleName", d["castleName"]),
            "profileIcon": d["profileIconId"], "flagId": deco["flag"]["flagId"],
            "nameTagId": deco["nameTag"], "mapSkinId": deco["mapSkin"],
            "cards": _pvp_card_infos(st), "buildings": [], "pvpDeckRecordData": [],
            "artifacts": [], "potentials": [], "territoryStatBuffPers": [],
            "riftWeapons": [], "encryptedUID": "", "playerLevel": st.get("level", 1)}

def _pvp_season_dates(cfg_key):
    c = RCFG[cfg_key]
    return ([now_iso(n) for n in c["seasonDayOffsets"]],
            [now_iso(n) for n in c["nextSeasonDayOffsets"]])

def _semi_season_scores(st, prefix, count):
    """One {score, rank} per semi-season. SetTier reads this by semi-season index,
    so a list shorter than the current semi-season leaves the tier badge blank."""
    score = int(st.get(prefix + "Score", 0))
    return [{"score": score, "rank": int(st.get(prefix + "Rank", 0))}
            for _ in range(max(1, count))]

def r_pvp_info(body, st):
    p, cfg = _pvp_state(st, "arena")
    until, nxt = _pvp_season_dates("pvpInfo")
    out = dict(cfg)
    score = int(st[p + "Score"])
    out.update({
        "seasonUntilAtDates": until, "nextSeasonStartAtDates": nxt,
        "score": score, "tier": colosseum.tier_for(score, 0, XML_DIR)["id"],
        "maxScore": max(score, int(st.get(p + "BestScore", score))),
        "winCount": st[p + "Win"], "loseCount": st[p + "Lose"],
        "semiSeasonScoreDatas": _semi_season_scores(st, p, cfg.get("semiSeason", 1)),
        "deckInfo": _pvp_deck_info(st), "receivedRewards": list(st[p + "Claimed"]),
        "winRewardReceived": list(st.setdefault(p + "WinSteps", [])),
        "currentSemiSeasonWinCount": st[p + "Win"],
    })
    out["maxTier"] = colosseum.tier_for(out["maxScore"], 0, XML_DIR)["id"]
    return out

def r_colosseum(body, st):
    p, cfg = _pvp_state(st, "colosseum")
    until, nxt = _pvp_season_dates("colosseum")
    out = dict(cfg)
    score = int(st[p + "Score"])
    rank = int(st.get(p + "Rank", 0))
    out.update({
        "seasonUntilAtDates": until, "nextSeasonStartAtDates": nxt,
        "score": score, "tier": colosseum.tier_for(score, rank, XML_DIR)["id"],
        "rank": rank,
        "maxScore": max(score, int(st.get(p + "BestScore", score))),
        "winCount": st[p + "Win"], "loseCount": st[p + "Lose"],
        "gameCount": st[p + "Win"] + st[p + "Lose"],
        "bestScore": max(score, int(st.get(p + "BestScore", score))),
        "receivedRewards": list(st[p + "Claimed"]),
        "semiSeasonScoreDatas": _semi_season_scores(st, p, cfg.get("semiSeason", 1)),
        # ponytail: the free-reward box count is not in any XML we parse, and a
        # wrong length indexes out of range. Empty is the length the client can
        # loop over safely; size it once a box is known to exist.
        "freeRewardCountPerBox": [],
    })
    out["bestTier"] = colosseum.tier_for(out["bestScore"], rank, XML_DIR)["id"]
    out["maxTier"] = out["bestTier"]
    return out

def r_colosseum_complete_round(body, st):
    """One colosseum round finished. `win` decides the score move."""
    win = bool(body.get("win", body.get("isWin", False)))
    delta = _pvp_record(st, "colosseum", win)
    _pvp_log(st, "colosseum", win, delta,
             {"gameId": str(body.get("gameId", "")), "rank": int(body.get("rank", 0) or 0),
              "round": int(body.get("round", 0) or 0)})
    save_state(st)
    admin_log(f"[colosseum] round {'win' if win else 'loss'} {delta:+d} "
              f"-> {st['colosseumScore']}")
    return {"score": st["colosseumScore"], "scoreDelta": delta,
            "tier": st.get("colosseumTier", 0)}

def r_colosseum_round_data(body, st):
    """Snapshot of a round in progress. Nothing to keep - the client replays its own
    rounds - but it must answer, or the battle stalls waiting on the round save."""
    return {"round": int(body.get("round", 0) or 0)}

def r_colosseum_logs(body, st):
    _pvp_state(st, "colosseum")
    logs = []
    for e in reversed(st["colosseumLogs"]):
        logs.append({"logId": e["logId"], "myScoreDelta": e["myScoreDelta"],
                     "semiSeason": e["semiSeason"], "startedAt": e["startedAt"],
                     "gameId": e.get("gameId", ""), "endedAt": e["endedAt"],
                     "playerDecks": [dict(_pvp_deck_preview(st, "colosseum", e["logId"]),
                                          rank=e.get("rank", 1),
                                          round=e.get("round", 0), isBot=False)]})
    return {"logList": logs, "targetUserData": _colosseum_player(st)}

def r_colosseum_statistics(body, st):
    p, cfg = _pvp_state(st, "colosseum")
    # countsByRank is a placement histogram: index 0 is first place. One entry per
    # possible rank, which the mode fixes at four players.
    counts = [st[p + "Win"], st[p + "Lose"], 0, 0]
    return {"dataList": [{"semiSeason": cfg.get("semiSeason", 1),
                          "winCount": st[p + "Win"], "loseCount": st[p + "Lose"],
                          "countsByRank": counts}]}

def r_colosseum_players(body, st):
    return {"colosseumPlayerDataList": [_colosseum_player(st)],
            "isCustomMatch": bool(body.get("isCustomMatch", False))}

def r_colosseum_tier_rewards(body, st):
    """Claim every tier reward the player's best score has earned.

    Rewards are per tier and pay once, so the claimed set is what stops a score
    that crosses the same boundary twice from paying twice."""
    p, _ = _pvp_state(st, "colosseum")
    best = max(int(st[p + "Score"]), int(st.get(p + "BestScore", 0)))
    tier = colosseum.tier_for(best, int(st.get(p + "Rank", 0)), XML_DIR)
    claimed = set(st[p + "Claimed"])
    rewards, new_ids = colosseum.tier_rewards_up_to(tier["id"], claimed, XML_DIR)
    for r in rewards:
        _grant_reward(st, r["type"], r["id"], r["count"])
    st[p + "Claimed"] = sorted(claimed | set(new_ids))
    save_state(st)
    admin_log(f"[colosseum] tier rewards up to {tier['id']} -> {len(rewards)} rewards")
    return {"rewardListResponseData": _reward_list_data(rewards),
            "receivedRewards": st[p + "Claimed"]}

def r_arena_win_reward(body, st):
    """The arena's cumulative win-count steps from ArenaSettings.xml."""
    p, _ = _pvp_state(st, "arena")
    steps = set(st.setdefault(p + "WinSteps", []))
    rewards, new_ids = colosseum.arena_rewards_for(st[p + "Win"], steps, XML_DIR)
    for r in rewards:
        _grant_reward(st, r["type"], r["id"], r["count"])
    st[p + "WinSteps"] = sorted(steps | set(new_ids))
    save_state(st)
    return {"rewardListResponseData": _reward_list_data(rewards),
            "winRewardReceived": st[p + "WinSteps"]}

def r_arena_logs(body, st):
    _pvp_state(st, "arena")
    me = _pvp_deck_preview(st, "arena")
    logs = []
    for e in reversed(st["pvpLogs"]):
        row = dict(me, logId=e["logId"], score=int(st["pvpScore"]),
                   tier=st.get("pvpTier", 0))
        logs.append({"logId": e["logId"], "myScoreDelta": e["myScoreDelta"],
                     "semiSeason": e["semiSeason"], "startedAt": e["startedAt"],
                     "myDeckId": 0, "myDeck": row, "enemyDeckId": 0,
                     "enemyDeck": dict(row, playerName=e.get("enemyName", "Bot"))})
    return {"logList": logs, "targetUserData": _pvp_deck_info(st)}

def r_arena_statistics(body, st):
    p, cfg = _pvp_state(st, "arena")
    return {"trainingCount": st.get(p + "Training", 0),
            "dataList": [{"semiSeason": cfg.get("semiSeason", 1),
                          "winCount": st[p + "Win"], "loseCount": st[p + "Lose"],
                          "trainingCount": st.get(p + "Training", 0)}]}

def r_arena_matching(body, st):
    """PvPMatchResponseModel. There is one player, so the opponent offered is the
    player's own deck - which is what the mode's training mode does anyway."""
    return {"targets": [_pvp_deck_info(st)]}

def r_colosseum_match(body, st):
    """ColosseumMatchResponseModel. No realtime match server exists here, so the
    address is empty and the client falls through to its own bot stage - the same
    path /colosseum/test-single-play takes."""
    return {"gameId": str(body.get("gameId") or f"local-{int(time.time())}"),
            "serverAddress": ""}

def r_colosseum_custom_match(body, st):
    return {"lobbyId": str(body.get("lobbyId") or ""), "endPoint": ""}

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
    icon = int(body.get("profileIconId", body.get("iconId", 0)) or 0)
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
    """Another player's profile. There is one save here, so it is this one - which is
    also what the clan and leaderboard panels link to."""
    d = _PC["defaults"]
    deco = _deco(st)
    return {"name": st.get("name", d["name"]),
            "castleName": st.get("castleName", d["castleName"]),
            "kingPostfix": 0, "castlePostfix": 0,
            "profileIconId": _key_value(st, "profileIconId", d["profileIconId"]),
            "profileIconBackgroundId": 0, "nameTagId": deco["nameTag"],
            "level": st.get("level", 1), "exp": st.get("exp", 0),
            "invasionDifficultyRecords": [], "eventModeRecord": [],
            "rogueLikeBuildingChallengeLevelRecord": [],
            "babelRecord": [b["floor"] for b in _babel(st).values()] or [0],
            "winCount": st.get("pvpWin", 0), "heroCount": len(st.get("cards", {})),
            "currentAltar": 0, "currentDeck": _pvp_card_infos(st),
            "currentPotential": [], "firstComerIndex": 0,
            "currentRanking": [], "currentHardRanking": [],
            "clanId": st.get("clanId", 0), "clanMark": 0,
            "clanRole": st.get("clanRole", 0), "clanName": st.get("clanName", ""),
            "clanTier": 0, "clanRoleNames": []}

# --- Journey ------------------------------------------------------------------
# The client drives this entirely off two key-values it reads back off the response,
# not off a model field: JourneyLastRewardId and JourneyNextRewardTime.

JOURNEY_LAST = "JourneyLastRewardId"
JOURNEY_NEXT = "JourneyNextRewardTime"

def _journey_arm(st, last_id):
    """Point the ladder at the reward after `last_id` and start its clock."""
    nxt = player_events.journey_next(last_id, XML_DIR)
    _set_key_value(st, JOURNEY_LAST, str(last_id))
    _set_key_value(st, JOURNEY_NEXT, "" if nxt is None
                   else now_iso(seconds=nxt["wait"]))
    return nxt

def r_journey_init(body, st):
    """Start the ladder. Re-initialising an armed journey must not reset its timer,
    or the panel becomes a way to never wait."""
    if _key_value(st, JOURNEY_NEXT) is None:
        _journey_arm(st, -1)
        save_state(st)
    return {"rewardList": _reward_list_data([]), "keyValues": _key_values(st)}

def r_journey_reward(body, st):
    """Claim the reward whose wait has elapsed, then arm the next one."""
    last = int(_key_value(st, JOURNEY_LAST, -1) or -1)
    due = _key_value(st, JOURNEY_NEXT)
    item = player_events.journey_next(last, XML_DIR)
    if item is None or not due or now_iso(0) < due:
        return {"rewardList": _reward_list_data([]), "keyValues": _key_values(st)}
    paid = [_grant_mission_reward(st, item["reward"])]
    _journey_arm(st, item["id"])
    save_state(st)
    admin_log(f"[journey] reward {item['id']} claimed -> {paid}")
    return {"rewardList": _reward_list_data(paid), "keyValues": _key_values(st)}

# --- Anniversary event --------------------------------------------------------
# FifthHalfYearEventRewards.xml carries no dates of its own, so whether the event is
# running is the server's call and lives in response_config.

def _year_state(st):
    y = st.setdefault("yearEvent", {})
    y.setdefault("startedAt", now_iso(RCFG["yearEvent"]["startDayOffset"]))
    y.setdefault("lastAttendanceDay", 0)
    y.setdefault("lastPassDay", 0)
    y.setdefault("passPoint", 0)
    y.setdefault("continuous", True)
    return y

def _year_day(st):
    y = _year_state(st)
    start = datetime.datetime.fromisoformat(y["startedAt"].replace("Z", ""))
    cfg = RCFG["yearEvent"]
    return min(player_events.elapsed_days(start), cfg["lengthDays"]), start

def r_year_event(body, st):
    cfg = RCFG["yearEvent"]
    y = _year_state(st)
    day, start = _year_day(st)
    save_state(st)
    return {"eventStartAt": y["startedAt"],
            "eventUntilAt": now_iso(cfg["startDayOffset"] + cfg["lengthDays"]),
            "currentAttendanceDay": day if cfg["enabled"] else 0,
            "lastAttendanceRewardDay": y["lastAttendanceDay"],
            "isContinuous": y["continuous"],
            "lastPassRewardDay": y["lastPassDay"],
            "passPoint": y["passPoint"]}

def _year_claim(st, track, table):
    """Pay every unclaimed day of a track up to today. Both tracks pay per day and
    only once, so the last claimed day is the whole bookkeeping."""
    cfg = RCFG["yearEvent"]
    y = _year_state(st)
    if not cfg["enabled"]:
        return []
    day, _ = _year_day(st)
    paid = []
    for d in sorted(table):
        if d <= y[track] or d > day:
            continue
        for r in table[d]:
            paid.append(_grant_mission_reward(st, r))
        y[track] = d
    return paid

def r_year_attendance_reward(body, st):
    table = player_events.year_attendance_rewards(XML_DIR)
    paid = _year_claim(st, "lastAttendanceDay", table)
    y = _year_state(st)
    # The continuous bonus is paid on top, once, when the board is completed
    # without a gap - claiming the last day late still leaves isContinuous true
    # here because there is nobody to break the streak on a single-player save.
    if y["lastAttendanceDay"] >= max(table or [0]) and not y.get("continuousPaid"):
        for r in player_events.year_continuous_reward(XML_DIR):
            paid.append(_grant_mission_reward(st, r))
        y["continuousPaid"] = True
    save_state(st)
    return {"eventResponseModel": r_year_event(body, st),
            "rewardListResponseData": _reward_list_data(paid)}

def r_year_pass_reward(body, st):
    paid = _year_claim(st, "lastPassDay", player_events.year_pass_rewards(XML_DIR))
    save_state(st)
    return {"eventResponseModel": r_year_event(body, st),
            "rewardListResponseData": _reward_list_data(paid)}

def r_year_buy_pass_point(body, st):
    """Buy pass points with cash. Refuses rather than going negative - the client
    re-reads the balance from this response."""
    cfg = RCFG["yearEvent"]
    y = _year_state(st)
    price = cfg["buyPassPointCashPrice"]
    if st.get("cash", 0) >= price:
        st["cash"] -= price
        y["passPoint"] += cfg["buyPassPointCount"]
        save_state(st)
    return {"eventResponseModel": r_year_event(body, st),
            "playerCash": st.get("cash", 0)}

# --- Roguelike ----------------------------------------------------------------
# The run itself lives entirely client-side: the client serialises the whole thing
# into one opaque string and posts it. The server's only job is to hold that string
# so a run survives closing the app - which is exactly what the static placeholder
# could not do, since it always answered with an empty save.

def _rogue(st, theme):
    return st.setdefault("rogueLike", {}).setdefault(str(int(theme or 0)), {
        "saveData": "", "ownCardSnapshot": "", "state": "", "saveVersion": 0,
        "lastHeartPaidFloor": 0, "lastGameStartedSeason": 0})

def r_rogue_save(body, st):
    """Store the run blob. An empty blob is a legitimate 'run over' write, so it is
    stored as sent rather than being treated as a missing field."""
    r = _rogue(st, body.get("themeId", 0))
    r["saveData"] = body.get("rogueLikeSaveData", "")
    r["state"] = body.get("state", "")
    r["saveVersion"] = int(body.get("saveVersion", 0) or 0)
    save_state(st)
    return {}

def r_rogue_snapshot(body, st):
    """The hero roster the run was started with, frozen so later lobby upgrades do
    not change a run in progress."""
    r = _rogue(st, body.get("themeId", 0))
    r["ownCardSnapshot"] = body.get("ownCardSnapshot", "")
    save_state(st)
    return {}

def r_rogue_load(body, st):
    r = _rogue(st, body.get("themeId", 0))
    save_state(st)
    return {"rogueLikeSaveData": r["saveData"],
            "rogueLikeOwnCardSnapshot": r["ownCardSnapshot"],
            "state": r["state"], "saveVersion": r["saveVersion"],
            "lastHeartPaidFloor": r["lastHeartPaidFloor"],
            "lastGameStartedSeason": r["lastGameStartedSeason"]}

def r_rogue_delete(body, st):
    """Abandon a run. The game index has to move, or the client keeps replaying the
    same index and the next run's saves collide with the deleted one's."""
    theme = body.get("rogueLikeThemeId", body.get("themeId", 0))
    st.setdefault("rogueLike", {}).pop(str(int(theme or 0)), None)
    st["rogueLikeGameIndex"] = int(st.get("rogueLikeGameIndex", 0)) + 1
    save_state(st)
    admin_log(f"[roguelike] run on theme {theme} deleted -> "
              f"index {st['rogueLikeGameIndex']}")
    return {"rogueLikeGameIndex": st["rogueLikeGameIndex"],
            "dimensionRiftGameIndex": st.get("dimensionRiftGameIndex", 0),
            "returnHeart": 0}

def r_rogue_revive(body, st):
    """Reviving inside a run costs the same cash as reviving in a normal battle."""
    return r_game_revive(body, st)

def r_rogue_can_revive_by_ad(body, st):
    """No ad network is wired up here, so the ad revive is never offered - reported
    as unavailable rather than left empty, which the button reads as an error."""
    return {"canReviveByAd": False, "remainCount": 0}

def r_rogue_statistics(body, st):
    """Clear rates across the playerbase. One player is not a sample, and inventing
    one would print made-up percentages next to real mission names."""
    return {"rogueLikeMissionStatistics": [], "totalRogueLikeUser": 1}

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
    return {"userId": code}

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
    code = (body.get("code") or body.get("userId") or "").strip().upper()
    uid = _transfer_lookup(code)
    if uid is None:
        admin_log("[auth] transfer redeem refused: unknown or expired code")
        return {"success": False, "msg": "invalid transfer code"}
    src = playerdb.load(uid) or {}
    src.pop("transfer", None)           # single use
    playerdb.save(uid, src)
    login_id = CURRENT_LOGIN_ID.get() or body.get("id") or ""
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
            "blockedUntilAt": now_iso(0), "blockedComment": "", "loginId": uid}


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
    wid = int(body.get("riftWeaponId", body.get("id", 0)) or 0)
    weapon = next((w for w in DEFAULT_RIFT_WEAPONS if w.get("id") == wid), None)
    if weapon and not any(a.get("id") == wid for a in archives):
        archives.append(weapon)
        save_state(st)
    return {"riftWeapons": archives, "deletedRiftWeapons": [],
            "rewardListResponseData": None, "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0), "upgradeState": 0,
            "equippedWeaponIds": []}

def r_wiki_archive_delete(body, st):
    wid = int(body.get("riftWeaponId", body.get("id", 0)) or 0)
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
    return {"eventId": int(body.get("eventId", 0) or 0), "state": 0,
            "rewardList": _reward_list_data([])}

def r_cloud_run_services(body, st):
    """Infrastructure discovery. The real backend answers with the regional service
    endpoints it wants the client to use; here everything is this server, so the
    honest answer is an empty list and the client keeps its configured host."""
    return {"services": [], "ranking": []}

# --- Shop bookkeeping ---------------------------------------------------------
# Nine shop routes answered an empty model. None of them buy anything - they are the
# places where the player's own choices are stored: which treasures they want out of
# a box, which heroes they pinned to a custom-pickup banner, and which purchases the
# store still owes them.

# ResourceTreasure.Rarity. The wish list is keyed by it, and Newtonsoft writes an
# enum dictionary key as its name, so the keys have to be the names.
TREASURE_RARITIES = ["Common", "Rare", "Special"]

def r_treasure_wish_list(body, st):
    saved = st.get("treasureWishList", {})
    return {"wishList": {r: list(saved.get(r, [])) for r in TREASURE_RARITIES}}

def r_save_treasure_wish_list(body, st):
    """Store the wish list, keeping only ids that are really treasures - a wish for
    something that does not exist comes back as a blank row in the panel."""
    sent = body.get("wishList") or {}
    known = set(ALL_TREASURE_IDS)
    out = {}
    for rarity in TREASURE_RARITIES:
        ids = sent.get(rarity) or sent.get(str(TREASURE_RARITIES.index(rarity) + 1)) or []
        out[rarity] = [int(i) for i in ids if int(i) in known]
    st["treasureWishList"] = out
    save_state(st)
    return {"wishList": out}

def r_custom_pickups(body, st):
    """The heroes pinned to a custom-pickup banner, per banner id."""
    banner = str(body.get("shopItemId", body.get("id", 0)) or 0)
    return {"customPickups": list(st.get("customPickups", {}).get(banner, []))}

def r_save_custom_pickups(body, st):
    banner = str(body.get("shopItemId", body.get("id", 0)) or 0)
    picks = [int(i) for i in (body.get("customPickups") or []) if int(i)]
    st.setdefault("customPickups", {})[banner] = picks
    save_state(st)
    return {"customPickups": picks}

def r_shop_choice(body, st):
    """A package that lets the buyer choose - a hero, or which treasure a pickup
    ceiling pays out. The choice is recorded so the panel stops asking; the item
    itself is granted by the purchase route that precedes this."""
    key = "packageChoices" if "unitId" in body else "pickupChoices"
    choice = int(body.get("unitId", body.get("treasureId", 0)) or 0)
    if choice:
        st.setdefault(key, {})[str(body.get("shopItemId", 0) or 0)] = choice
        save_state(st)
    return {}

def r_iap_restore_add(body, st):
    """A purchase the store charged for but the server has not yet delivered. There
    is no store here, so nothing is ever owed - but the list has to answer, because
    the client blocks the shop while it believes a restore is pending."""
    return {"restoreNeededIaps": st.get("restoreNeededIaps", [])}

def r_iap_restore_remove(body, st):
    pending = st.get("restoreNeededIaps", [])
    sku = body.get("productId") or body.get("sku")
    st["restoreNeededIaps"] = [p for p in pending if p != sku]
    save_state(st)
    return {"restoreNeededIaps": st["restoreNeededIaps"]}

def r_early_access(body, st):
    """Early-access test windows are dated in EarlyAccessModeInfos.xml and every one
    of them has closed, so there is nothing to enter. Reported as closed rather than
    left empty, which the panel reads as a failed request."""
    return {"earlyAccessModeId": 0, "applied": False, "keyValues": _key_values(st)}

# --- Leaderboards -------------------------------------------------------------
# Every board answered an empty model, so each one rendered as a blank list with no
# row for the player either. There is nobody else on a private server, so the honest
# board is one row: you, first. An empty `ranking` with a filled `playerRank` is not
# the same thing - several panels read the list to find themselves and show "unranked"
# when they cannot.

def _rank_row(st, score=0, extra=None):
    d = _PC["defaults"]
    deco = _deco(st)
    row = {"rank": 1, "score": int(score),
           "accountId": st.get("accountId", d["accountId"]),
           "userName": st.get("name", d["name"]),
           "castleName": st.get("castleName", d["castleName"]),
           "kingPostfix": 0, "castlePostfix": 0,
           "flagId": deco["flag"]["flagId"], "nameTagId": deco["nameTag"],
           "profileIcon": d["profileIconId"], "tier": 0}
    row.update(extra or {})
    return row

def _board(st, score=0, extra=None, player_key="playerRank"):
    row = _rank_row(st, score, extra)
    return {"ranking": [row], player_key: dict(row)}

def r_ranking(body, st):
    """The generic board. `score` is a long here and `deck` replaces the cosmetics."""
    d = _PC["defaults"]
    row = {"rank": 1, "score": int(st.get("bestClearedTheme", 0)) * 100
                               + int(st.get("bestClearedStage", 0)),
           "accountId": st.get("accountId", d["accountId"]),
           "userName": st.get("name", d["name"]),
           "castleName": st.get("castleName", d["castleName"]),
           "kingPostfix": 0, "castlePostfix": 0,
           "deck": _deck_units(st)}
    return {"rankingType": str(body.get("rankingType", "")), "ranking": [row],
            "playerRank": dict(row)}

def _deck_units(st):
    """The current preset's hero ids. The board draws these as portraits, so an empty
    list is a row of blank slots - fall back to the first non-empty preset rather than
    show nothing when the selected one has never been filled."""
    decks = st.get("decks") or []
    cur = st.get("currentDeckPreset", 0)
    order = ([decks[cur]] if cur < len(decks) else []) + list(decks)
    for deck in order:
        units = deck.get("deck", []) if isinstance(deck, dict) else deck
        got = [u for u in units if isinstance(u, int) and u]
        if got:
            return got
    return []

def r_pvp_ranking(body, st):
    return _board(st, st.get("pvpScore", 0), {"tier": st.get("pvpTier", 0)})

def r_colosseum_ranking(body, st):
    return _board(st, st.get("colosseumScore", 0), {"tier": st.get("colosseumTier", 0)})

def r_roguelike_ranking(body, st):
    return _board(st, st.get("rogueLikeScore", 0),
                  {"challenge": st.get("rogueLikeChallenge", 0),
                   "building": st.get("rogueLikeBuilding", 0)})

def r_challenge_ranking(body, st):
    cs = _challenge_state(st)
    row = _rank_row(st, cs.get("bestDifficulty", 0))
    # ChallengeModeRankingData has no flag/nameTag/tier but does carry a percentile.
    for k in ("flagId", "tier"):
        row.pop(k, None)
    row["rankPer"] = 100.0
    return {"ranking": [row], "playerRank": dict(row)}

def r_clan_point_ranking(body, st):
    """Clans are their own entity, and there is exactly one here: the player's."""
    row = {"rank": 1, "clanPoint": st.get("clanPoint", 0), "clanTier": 0,
           "battleTier": 0, "clanId": st.get("clanId", 0),
           "clanName": st.get("clanName", ""), "markId": 0}
    return {"ranking": [row] if row["clanId"] else [], "playerClanRank": row}

def r_unit_statistics(body, st):
    """Usage rates across the playerbase. One player means no meaningful sample, and
    inventing one would put fake percentages under real hero names."""
    return {"topPotentialUsage": [], "topTreasureUsage": [], "topAccessoryUsage": []}


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
    "/shop": r_shop,
    "/shop/iap": r_shop,
    "/shop/caniap": r_shop,
    "/shop/caniap_new": r_shop,
    "/shop/get-restore-needed-iaps": r_shop,
    "/shop/refreshDailyShop": r_shop_refresh,
    "/player/getInventory": r_player_inventory,
    "/player/useInventory": r_use_inventory,
    "/player/use-reward-box-inventory-item": r_use_reward_box,
    "/player/use-skin-box-inventory-item": r_use_skin_box,
    "/player/receive-skin-box-alternate-reward": r_use_skin_box,
    "/player/add-inventory-count": lambda b, st: {
        "playerCash": st.get("cash", 0),
        "inventoryCount": 999
    },
    "/player/rename": lambda b, st: {"name": b.get("name", "DevKing")},
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
    "/auth/transfer": r_transfer_issue,
    "/auth/transfer/code": r_transfer_redeem,
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
    "/kgc-ranking": r_ranking,
    "/seasonal-event/april-fools/reward": lambda b, st: {
        "rewardListResponseData": _reward_list_data([])},
    "/artifact/reroll": r_artifact_result,
    "/artifact/polish/replace-option-slot-idx": r_artifact_result,
    "/rogueLike/save-rogueLike": r_rogue_save,
    "/rogueLike/load-rogueLike-data": r_rogue_load,
    "/rogueLike/save-own-card-snapshot": r_rogue_snapshot,
    "/rogueLike/delete-roguelike": r_rogue_delete,
    "/rogueLike/revive": r_rogue_revive,
    "/rogueLike/can-revive-by-ad": r_rogue_can_revive_by_ad,
    "/mission/roguelike-statistics": r_rogue_statistics,
    "/mission/roguelike/check-on-clear": r_ack,
    # /test/* are the client's own dev buttons. They exist in the build, so they
    # must answer, but nothing here is meant to rewrite a save from a debug menu.
    "/test/roguelike/clear-count": r_ack,
    "/test/roguelike/play-count": r_ack,
    "/test/roguelike/mission-clear-count": r_ack,
    "/test/roguelike/reset-mission": r_ack,
    "/shop/get-treasure-wish-list": r_treasure_wish_list,
    "/shop/save-treasure-wish-list": r_save_treasure_wish_list,
    "/shop/check-treasure-wish-list-valid": r_treasure_wish_list,
    "/shop/load-custom-pickups": r_custom_pickups,
    "/shop/save-custom-pickups": r_save_custom_pickups,
    "/shop/choice-package-unit": r_shop_choice,
    "/shop/choice-treasure-pickup-ceil": r_shop_choice,
    "/shop/caniap-and-add-to-restore-needed-iaps": r_iap_restore_add,
    "/shop/remove-from-restore-needed-iaps": r_iap_restore_remove,
    "/player/ad": r_player_ad,
    "/player/changeProfileIcon": r_change_profile_icon,
    "/player/other": r_player_other,
    "/player/initialize-journey": r_journey_init,
    "/player/journey-reward": r_journey_reward,
    "/player/year-event": r_year_event,
    "/player/year-event-attendance-reward": r_year_attendance_reward,
    "/player/year-event-pass-reward": r_year_pass_reward,
    "/player/year-event-buy-pass-point": r_year_buy_pass_point,
    "/player/early-access-mode": r_early_access,
    "/player/early-access-mode-code": r_early_access,
    "/player/tutorial/progress-mission": lambda b, st: {
        "keyValues": st.get("tutorialKeyValues", [])},
    # One-way telemetry: posted, never read back.
    "/player/exception": r_ack,
    "/player/xcdReport": r_ack,
    "/player/customEvent": r_ack,
    "/player/logClickNotice": r_ack,
    "/player/completeKingGakReturnEvent": r_ack,
    "/pvp/info": r_pvp_info,
    "/pvp/matching": r_arena_matching,
    "/pvp/test-matching": r_arena_matching,
    "/pvp/fetch-log-history": r_arena_logs,
    "/pvp/fetch-log-detail": r_arena_logs,
    "/pvp/fetch-statistics-data": r_arena_statistics,
    "/pvp/win-reward": r_arena_win_reward,
    "/pvp/all-rewards": r_arena_win_reward,
    "/pvp/dormant-progress": r_ack,
    "/colosseum": r_colosseum,
    "/colosseum/test-single-play": r_colosseum_match,
    "/colosseum/test-free-match": r_colosseum_match,
    "/colosseum/match": r_colosseum_match,
    "/colosseum/match/ping": r_colosseum_match,
    "/colosseum/server-address": r_colosseum_match,
    "/colosseum/match/cancel": r_ack,
    "/colosseum/create-custom-match": r_colosseum_custom_match,
    "/colosseum/join-custom-match": r_colosseum_custom_match,
    "/colosseum/round-data": r_colosseum_round_data,
    "/colosseum/complete-round-data": r_colosseum_complete_round,
    "/colosseum/check-end": r_ack,
    "/colosseum/record-minimum-rank": r_ack,
    "/colosseum/reenter-tried": r_ack,
    "/colosseum/reenter-succeed": r_ack,
    "/colosseum/open-mission-reward": lambda b, st: {
        "rewardListResponseData": _reward_list_data([])},
    "/colosseum/fetch-players-data": r_colosseum_players,
    "/colosseum/fetch-log-history": r_colosseum_logs,
    "/colosseum/fetch-log-detail": r_colosseum_logs,
    "/colosseum/fetch-statistics-data": r_colosseum_statistics,
    "/colosseum/get-reward": r_colosseum_tier_rewards,
    "/colosseum/all-tier-rewards": r_colosseum_tier_rewards,
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
    "/clan": r_clan,
    "/clan/info": r_clan,
    "/clan/create": r_clan_create,
    "/clan/leave": r_clan_leave,
    "/clan/delete": r_clan_leave,
    "/clan/nameCheck": r_clan_name_check,
    "/clan/modify-name": _clan_modify("name"),
    "/clan/modifyIntro": _clan_modify("intro"),
    "/clan/modifyNotice": _clan_modify("notice"),
    "/clan/modifyTag": _clan_modify("tag"),
    "/clan/modifyMark": _clan_modify("markId", int),
    "/clan/modifyJoinType": _clan_modify("joinType", int),
    "/clan/changeRoleName": r_clan_role_name,
    "/clan/chat": r_clan_chat,
    "/clan/fetchChat": r_clan_fetch_chat,
    "/clan/refreshChat": r_clan_fetch_chat,
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
    "/pass": r_pass,
    "/pass/reward": r_pass,
    "/pass/all-rewards": r_pass,
    "/pass/bonusReward": r_pass,
    "/pass/buyLevel": r_pass,
    "/pass/passEventBooster": r_pass,
    "/territory": r_territory,
    "/territory/fetch": r_territory_fetch,
    "/territory/build": r_territory_build,
    "/territory/upgrade-building": r_territory_build,
    "/territory/upgrade-building-immediately": r_territory_upgrade_now,
    "/territory/remove-building": r_territory_remove,
    "/territory/store-building": r_territory_store,
    "/territory/unstore-building": r_territory_unstore,
    "/territory/replace-building": r_territory_replace,
    "/territory/refresh-building": r_territory_fetch,
    "/territory/collect-labor": r_territory_collect_labor,
    "/territory/recover-labor": r_territory_collect_labor,
    "/territory/assign-units": r_territory_assign,
    "/territory/swap-assigned-units": r_territory_assign,
    "/territory/level-sync/assign": r_territory_fetch,
    "/territory/level-sync/reset-timer": r_territory_fetch,
    "/territory/attendance-check": r_territory_fetch,
    "/territory/alchemy-new": r_territory_fetch,
    "/territory/restaurant/claim": r_territory_fetch,
    "/territory/fetch-stat-buffs": r_territory_stat_buffs,
    "/territory/equip-skin": r_territory_equip_skin,
    "/territory/hunting/start": r_territory_hunting_start,
    "/territory/hunting/end": r_territory_hunting_end,
    "/territory/hunting/stop": r_territory_hunting_stop,
    "/territory/hunting/fetch": r_territory_fetch,
    "/territory/hunting/complete-hunting-immediately": r_territory_hunting_end,
    "/territory/trade-shop/buy": r_territory_trade_buy,
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
    "/decoration": r_decoration,
    "/decoration/map-skin/equip": r_map_skin_equip,
    "/decoration/map-skin/buy": r_map_skin_buy,
    "/decoration/map-skin/favorite": r_map_skin_favorite,
    "/decoration/login-skin/equip": r_login_skin_equip,
    "/decoration/advisor/contract": r_advisor_contract,
    "/decoration/advisor/extend": r_advisor_extend,
    "/decoration/advisor/equip": r_advisor_equip,
    "/decoration/advisor/timeout": r_advisor_timeout,
    "/flag/inventory": r_flag_inventory,
    "/flag/equipedFlag": lambda b, st: dict(_deco(st)["flag"]),
    "/flag/set": r_flag_set,
    "/nameTag/inventory": r_nametag_inventory,
    "/nameTag/set": r_nametag_set,
    "/player/get-login-scene-illust-data": r_login_scene_illust,
    "/card": r_card,
    "/dimension-unit/upgrade": r_dimension_upgrade,
    "/dimension-unit/overcome": r_dimension_overcome,
    # The v171 client uses both spellings of the battle-start route.
    "/game": r_game_start,
    "/game/revive": r_game_revive,
    "/babel": r_babel,
    "/ranking/ranking": r_ranking,
    "/ranking/pvp-ranking": r_pvp_ranking,
    "/ranking/pvp-hall-of-fame": r_pvp_ranking,
    "/ranking/pvp-league-ranking": r_pvp_ranking,
    "/ranking/colosseum-ranking": r_colosseum_ranking,
    "/ranking/colosseum-hall-of-fame": r_colosseum_ranking,
    "/ranking/colosseum-league-ranking": r_colosseum_ranking,
    "/ranking/roguelike-ranking": r_roguelike_ranking,
    "/ranking/roguelike-building-ranking": r_roguelike_ranking,
    "/ranking/dimension-rift-ranking": r_roguelike_ranking,
    "/ranking/challenge-mode-ranking": r_challenge_ranking,
    "/ranking/clan-point-ranking": r_clan_point_ranking,
    "/statistics/unit": r_unit_statistics,
    "/player/dailyAttendanceEvents": r_daily_attendance_events,
    "/player/surprise-attendance-event": r_surprise_attendance,
    "/player/surprise-attendance-event-daily-attendance-reward": r_surprise_attendance_reward,
}

# Pure-literal routes (no st/body dependency) load straight from JSON; wrap each
# in a lambda returning the same shared dict (build_model only reads from it via
# .update(), never mutates it, so no copy is needed).
OVERRIDES = {path: (lambda b, st, r=resp: r) for path, resp in STATIC_OVERRIDES.items()}
OVERRIDES.update(DYNAMIC_OVERRIDES)

SERVER_START_TIME = time.time()

app = FastAPI(title="KGC private server", version=SERVER_VERSION)
_STATE_GATE = asyncio.Lock()

ADMIN_TOKEN = os.environ.get("KGC_ADMIN_TOKEN")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}

@app.middleware("http")
async def guard_admin(request: Request, call_next):
    """The 26 /admin routes can rewrite or delete any player's save.

    serve_public.sh binds 0.0.0.0 so remote players can reach the game API - which
    exposes these too. Require KGC_ADMIN_TOKEN when it is set; with no token
    configured, allow loopback only. Note a reverse proxy or tunnel makes every
    request look like loopback, which is why serve_public.sh refuses to start
    without a token.
    """
    if request.url.path.startswith("/admin"):
        if ADMIN_TOKEN:
            sent = request.headers.get("x-admin-token") or request.query_params.get("admin_token") or ""
            if not secrets.compare_digest(sent, ADMIN_TOKEN):
                return JSONResponse({"error": "admin token required"}, status_code=403)
        elif (request.client.host if request.client else None) not in _LOOPBACK:
            return JSONResponse(
                {"error": "admin API is loopback-only; set KGC_ADMIN_TOKEN to allow remote access"},
                status_code=403)
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
    try:
        # asyncio.Lock first: flock blocks the thread, so a second request in THIS
        # process waiting on it would freeze the event loop and never let the holder
        # finish. Serialize in-process, then contend with the other process.
        async with _STATE_GATE:
            with playerdb.write_lock():
                return await call_next(request)
    finally:
        CURRENT_UID.reset(token)

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

async def respond(path: str, request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    raw = await request.body()
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
    overlay = OVERRIDES[path](body, st) if path in OVERRIDES else None
    if overlay is None and path not in ROUTE_MODELS:
        # Every route the v171 client can call is now mapped (route_models.json plus
        # data/route_models_extra.json), so reaching here means either a route the
        # string-table scan missed or a client newer than this server.
        admin_log(f"[UNKNOWN PATH] {request.method} {path}")
    payload = build_model(info["response"], overlay)
    admin_log(f"[{host}] {request.method} {path} -> {info.get('response')}")
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

def make_handler(path):
    async def h(request: Request):
        return await respond(path, request)
    return h

# Direct route handlers - must be registered BEFORE route_models to bypass build_model
@app.get("/accessory")
async def accessory_inventory_direct(request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    admin_log(f"[{host}] DIRECT GET /accessory -> AccessoryInventoryResponseModel")
    payload = {
        "code": 200, "msg": None, "success": True,
        "accessories": get_st_accessories(st)
    }
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

@app.post("/accessory")
async def accessory_equip_direct(request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    raw = await request.body()
    body = {}
    if raw:
        try:
            body = aes_decrypt(raw)
        except Exception:
            try:
                body = json.loads(raw)
            except Exception:
                pass
    admin_log(f"[{host}] DIRECT POST /accessory -> AccessoryResultResponseModel")
    accs = get_st_accessories(st)
    target_ids = body.get("targetIds", [])
    unit_id = body.get("unitId", 0)
    if target_ids and unit_id:
        for a in accs:
            if a["unitId"] == unit_id:
                a["unitId"] = 0
            if a["id"] in target_ids:
                a["unitId"] = unit_id
        save_state(st)
    payload = {
        "code": 200, "msg": None, "success": True,
        "accessories": accs,
        "deletedAccessories": [],
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "inventories": [],
        "addedExpItems": 0
    }
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

@app.get("/rift-weapon")
@app.post("/rift-weapon")
async def rift_weapon_inventory_direct(request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    admin_log(f"[{host}] DIRECT /rift-weapon -> RiftWeaponInventoryResponseModel")
    payload = r_rift_weapon({}, st)
    payload["code"] = 200
    payload["success"] = True
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

@app.get("/invasion/record")
@app.post("/invasion/record")
async def invasion_record_direct(request: Request):
    host = request.headers.get("host", "?")
    admin_log(f"  [{host}] DIRECT /invasion/record -> InvasionRecordsResponseModel")
    
    unlocked = RCFG["player"]["invasionUnlockedDifficulty"]
    themes = [t for a, b in RCFG["player"]["invasionThemeRanges"] for t in range(a, b)] + _PREREQ_THEMES
    records = []
    for t in themes:
        for d in range(1, unlocked + 1):
            records.append({"theme": t, "difficulty": d, "unlockedDifficulty": unlocked})
            
    payload = {
        "code": 200, "msg": None, "success": True,
        "difficultyRecords": records
    }
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

# Inbox (Post) - GET /post lists mail (PostResponseModel.posts), POST /post/receive claims
# (PostReceiveRequestModel{postId,receiveAll} -> PostReceiveResponseModel.rewardListResponseData).
# Mail lives in state so it persists and disappears once claimed. Reward grant is applied to
# player currency on claim so the send->receive->grant flow is real, not cosmetic.
@app.post("/admin/sendmail")
async def admin_send_mail(request: Request):
    st = load_state()
    body = await request.json()
    if "posts" not in st:
        st["posts"] = []
    next_id = max((p["id"] for p in st["posts"]), default=0) + 1
    title = body.get("title", "")
    text = body.get("text", "")
    for f in (title, text):
        if f.startswith("@raw:"):
            f = f[5:]
    st["posts"].append({
        "id": next_id,
        "type": body.get("type", "Normal"),
        "title": title,
        "text": text,
        "rewardType": body.get("rewardType", ""),
        "rewardId": body.get("rewardId", 0),
        "rewardAmount": body.get("rewardAmount", 0),
        "untilAt": now_iso(body.get("untilDays", 30)),
    })
    save_state(st)
    return {"code": 200, "success": True, "postId": next_id}

def _default_posts():
    return [{
        "id": 1, "type": "Normal",
        "title": "NOwL Private Server",
        "text": "Chào mừng đến private server! Thư test custom title/text. Nhận 1000 Vàng nhé.",
        "rewardType": "Gold", "rewardId": 0, "rewardAmount": 1000,
        "untilAt": now_iso(30),
    }]

def get_st_posts(st):
    if "posts" not in st:
        st["posts"] = _default_posts()
    return st["posts"]

def _grant_reward(st, rt, rid, amt):
    """Apply a claimed mail reward to player state. Currencies, inventory items, and hero
    souls/cards persist here; the client re-fetches /player, /player/getInventory and /card/all
    after a claim so the granted state appears. Complex owned-content (Artifact/Treasure/
    Accessory) is intentionally NOT auto-granted into state - it can trip client panel
    invariants (see AGENTS.md ArtifactOptionUI crash); gift those as an Item reward box
    (InventoryItems.xml Type=RewardBoxInventory/InstantRewardBox) which the player opens."""
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

def _ensure_raw_prefix(s: str) -> str:
    return s if s.startswith("@raw:") else "@raw:" + s

def _process_posts(posts: list) -> list:
    out = []
    for p in posts:
        p = dict(p)
        if isinstance(p.get("title"), str):
            p["title"] = _ensure_raw_prefix(p["title"])
        if isinstance(p.get("text"), str):
            p["text"] = _ensure_raw_prefix(p["text"])
        out.append(p)
    return out

@app.get("/post")
async def post_list_direct(request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    admin_log(f"[{host}] DIRECT GET /post -> PostResponseModel")
    payload = {"code": 200, "msg": None, "success": True, "posts": _process_posts(get_st_posts(st))}
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

@app.post("/post/receive")
async def post_receive_direct(request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    raw = await request.body()
    body = {}
    if raw:
        try:
            body = aes_decrypt(raw)
        except Exception:
            try:
                body = json.loads(raw)
            except Exception:
                pass
    posts = get_st_posts(st)
    post_id = body.get("postId", 0)
    receive_all = body.get("receiveAll", False)
    claimed = [p for p in posts if receive_all or p["id"] == post_id]
    reward_list = []
    for p in claimed:
        amt = p.get("rewardAmount", 0)
        rt = p.get("rewardType", "")
        rid = p.get("rewardId", 0)
        _grant_reward(st, rt, rid, amt)
        if amt or rid:
            reward_list.append({"type": rt, "id": rid, "count": amt})
    st["posts"] = [p for p in posts if p not in claimed]
    save_state(st)
    admin_log(f"[{host}] DIRECT POST /post/receive claimed={len(claimed)} -> PostReceiveResponseModel")
    payload = {
        "code": 200, "msg": None, "success": True,
        "rewardListResponseData": {
            "rewardList": reward_list,
            "artifactResult": None, "treasureResult": None, "accessoryResult": None,
        },
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0), "playerHeart": st.get("heart", 0),
    }
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

# Direct PvP handler - must be registered BEFORE route_models to take priority
@app.get("/pvp/info")
@app.post("/pvp/info")
async def pvp_info_direct(request: Request):
    # The request body is never read - the response depends only on saved state.
    # pvpInfoDirect stays the base because it carries the fields that were tuned
    # against the live client (deckRecord, retry counts, ban lists); r_pvp_info then
    # overlays the parts that actually move, so a win shows up here too.
    host = request.headers.get("host", "?")
    payload = {"code": 200, "msg": None, "success": True}
    payload.update(RCFG["pvpInfoDirect"])
    payload.update(r_pvp_info({}, load_state()))
    admin_log(f"[{host}] PVP DIRECT /pvp/info -> seasonUntilAtDates={len(payload['seasonUntilAtDates'])}")
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

# ── Admin Panel ─────────────────────────────────────────────────────────
# The UI lives in dashboard.py (:8081) - a Vue app served from webui/. This route used
# to render admin.html, but that file has not existed for a long time, so /admin was
# quietly serving a blank page. The /admin/api/* routes below are still live: the
# dashboard proxies them for the server-side views, and creates players through them so
# the "new save" shape stays defined in exactly one place.
DASHBOARD_URL = os.environ.get("KGC_DASHBOARD_URL", "http://127.0.0.1:8081")

# ── Multi-player helpers ──
def _list_players():
    result = []
    for uid, data, updated in playerdb.all_players():
        if data is None:
            result.append({"id": uid, "name": f"[invalid] {uid}", "error": True})
            continue
        result.append({
            "id": uid,
            "name": data.get("name", "Unknown"),
            "uid": data.get("uid", ""),
            "level": data.get("level", 1),
            "gold": data.get("gold", 0),
            "cash": data.get("cash", 0),
            "castleName": data.get("castleName", ""),
            "cards": len(data.get("cards", {})),
            "updatedAt": datetime.datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M"),
        })
    return result

def _load_player_by_id(pid):
    return playerdb.load(pid)

def _save_player_by_id(pid, data):
    playerdb.save(pid, data)

def _delete_player_by_id(pid):
    playerdb.delete(pid)

def _switch_active(pid):
    """Point the game client at player pid."""
    if playerdb.load(pid) is None:
        return False
    playerdb.set_active(pid)
    return True

def _load_or_create_active():
    return load_state()

@app.get("/admin")
async def admin_page():
    return HTMLResponse(
        f'<!doctype html><meta charset="utf-8"><title>KGC admin</title>'
        f'<body style="font:15px system-ui;background:#0b0f17;color:#e6ecf7;padding:40px">'
        f'<h1 style="font-size:18px">The admin UI moved</h1>'
        f'<p>It is now the dashboard at <a style="color:#7aa8ff" href="{DASHBOARD_URL}">{DASHBOARD_URL}</a> '
        f'(<code>python3 server/dashboard.py</code>).</p>'
        f'<p style="color:#6d7c99">This server still serves the <code>/admin/api/*</code> endpoints '
        f'the dashboard calls.</p>')

@app.get("/admin/api/info")
async def admin_info():
    players = _list_players()
    active = playerdb.active()
    return {
        "version": SERVER_VERSION, "patchFolder": PATCH_FOLDER,
        "routes": len(ROUTE_MODELS) + len(OVERRIDES),
        "players": players,
        "playerCount": len(players),
        "activePlayerId": active,
    }

# ── Player CRUD ──
@app.get("/admin/api/players")
async def admin_list_players():
    return {"players": _list_players()}

@app.post("/admin/api/players/create")
async def admin_create_player(body: dict):
    name = body.get("name", "NewPlayer")
    uid = body.get("uid", "player-" + secrets.token_hex(4))
    st = copy.deepcopy(DEFAULT_PLAYER)   # deep: a shallow copy shares nested dicts with the template
    st["name"] = name
    st["uid"] = uid
    st["accountCreatedAt"] = now_iso(0)
    st["lastHeartTime"] = now_iso(0)
    st["tomorrow"] = now_iso(1)
    st["nextWeek"] = now_iso(7)
    _save_player_by_id(uid, st)
    return {"ok": True, "uid": uid}

@app.post("/admin/api/players/delete")
async def admin_delete_player(body: dict):
    pid = body.get("uid", "")
    _delete_player_by_id(pid)
    # playerdb.active() falls back to the first remaining row on its own.
    return {"ok": True}

@app.post("/admin/api/players/switch")
async def admin_switch_player(body: dict):
    pid = body.get("uid", "")
    if _switch_active(pid):
        return {"ok": True}
    return {"ok": False, "error": "Player not found"}

@app.get("/admin/api/players/{pid}")
async def admin_get_player_by_id(pid: str):
    data = _load_player_by_id(pid)
    if not data:
        return {"error": "not found"}
    return data

@app.post("/admin/api/players/{pid}/save")
async def admin_save_player_by_id(pid: str, body: dict):
    # body may contain partial updates or full state
    existing = _load_player_by_id(pid) or {}
    existing.update(body)
    _save_player_by_id(pid, existing)
    return {"ok": True}

@app.post("/admin/api/players/{pid}/reset")
async def admin_reset_player_by_id(pid: str):
    st = copy.deepcopy(DEFAULT_PLAYER)
    st["uid"] = pid
    _save_player_by_id(pid, st)
    return {"ok": True}

# ── Legacy single-player endpoints (target active) ──
@app.get("/admin/api/player")
async def admin_get_active_player():
    st = _load_or_create_active()
    fields = {
        "accountId": st.get("accountId", 1),
        "uid": st.get("uid", ""),
        "name": st.get("name", ""),
        "castleName": st.get("castleName", ""),
        "level": st.get("level", 1),
        "exp": st.get("exp", 0),
        "gold": st.get("gold", 0),
        "cash": st.get("cash", 0),
        "paidCash": st.get("paidCash", 0),
        "heart": st.get("heart", 0),
        "bestClearedStage": st.get("bestClearedStage", 1),
        "bestClearedTheme": st.get("bestClearedTheme", 1),
        "bestClearedHardStage": st.get("bestClearedHardStage", 1),
        "bestClearedHardTheme": st.get("bestClearedHardTheme", 1),
        "currentDeckPreset": st.get("currentDeckPreset", 0),
        "playedCount": st.get("playedCount", 0),
        "winCount": st.get("winCount", 0),
        "hasFreeRename": st.get("hasFreeRename", True),
        "buildingPoints": st.get("buildingPoints", 25),
        "accountCreatedAt": st.get("accountCreatedAt", ""),
        "lastHeartTime": st.get("lastHeartTime", ""),
        "tomorrow": st.get("tomorrow", ""),
        "nextWeek": st.get("nextWeek", ""),
        "eventFlag": st.get("eventFlag", 0),
        "cards": st.get("cards", {}),
        "decks": st.get("decks", []),
        "inventory": st.get("inventory", {"itemIds": [], "counts": []}),
        "equippedArtifacts": st.get("equippedArtifacts", []),
        "buildingPresets": st.get("buildingPresets", []),
        "altarPoints": st.get("altarPoints", []),
        "altarLevels": st.get("altarLevels", []),
        "tokens": st.get("tokens", []),
        "missions": st.get("missions", []),
        "tutorialKeyValues": st.get("tutorialKeyValues", []),
    }
    return fields

SKIP_KEYS = {"cards", "inventory", "decks", "equippedArtifacts", "buildingPresets",
              "altarPoints", "altarLevels", "tokens"}

@app.post("/admin/api/player/save")
async def admin_save_active_player(body: dict):
    st = _load_or_create_active()
    for k in ("name", "castleName", "level", "exp", "bestClearedStage", "bestClearedTheme",
              "bestClearedHardStage", "bestClearedHardTheme", "playedCount", "winCount",
              "hasFreeRename", "currentDeckPreset", "gold", "cash", "paidCash", "heart",
              "buildingPoints"):
        if k in body:
            st[k] = body[k]
    for k in ("tomorrow", "nextWeek", "accountCreatedAt", "lastHeartTime"):
        if k in body:
            st[k] = body[k]
    for k in ("inventory", "tokens", "buildingPresets", "altarPoints", "altarLevels",
              "missions", "tutorialKeyValues", "eventFlag"):
        if k in body:
            st[k] = body[k]
    save_state(st)
    return {"ok": True}

@app.post("/admin/api/player/reset")
async def admin_reset_active_player():
    st = copy.deepcopy(DEFAULT_PLAYER)
    st["uid"] = playerdb.active() or st.get("uid", "dev-0001")   # reset the data, keep the identity
    save_state(st)
    return {"ok": True}

@app.post("/admin/api/heroes/save")
async def admin_save_heroes(body: dict):
    st = _load_or_create_active()
    if "cards" in body:
        st["cards"] = body["cards"]
    save_state(st)
    return {"ok": True}

@app.post("/admin/api/heroes/give-all")
async def admin_give_all_heroes():
    st = _load_or_create_active()
    template = {
        "level": 30, "exp": 0, "potentialTier": 1,
        "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
        "randomSkinApply": False, "soul": 999
    }
    cards = st.setdefault("cards", {})
    for hid in ALL_HERO_IDS:
        sid = str(hid)
        if sid not in cards:
            cards[sid] = {"unitId": hid, **template}
    save_state(st)
    return {"ok": True, "count": len(cards)}

@app.post("/admin/api/decks/save")
async def admin_save_decks(body: dict):
    st = _load_or_create_active()
    if "decks" in body:
        st["decks"] = body["decks"]
    save_state(st)
    return {"ok": True}

@app.post("/admin/api/artifacts/give-all")
async def admin_give_all_artifacts():
    return {"ok": True, "count": len(DEFAULT_ARTIFACTS)}

@app.post("/admin/api/treasures/give-all")
async def admin_give_all_treasures():
    return {"ok": True, "count": len(DEFAULT_TREASURES)}

# One crystal per weapon, each pointed at a different altar so the set actually covers
# distinct options instead of six copies of "Rift Crystal of Hero".
DEFAULT_RIFT_CRYSTALS = [make_rift_crystal(i + 1, rwid, main_idx=i)
                         for i, rwid in enumerate(ALL_RIFT_WEAPON_IDS)]

@app.post("/admin/api/rift-crystals/grant")
async def admin_grant_rift_crystals(request: Request):
    body = await request.json()
    weapon_id = body.get("weaponId", 0)
    st = _load_or_create_active()
    rift_crystals = st.setdefault("riftCrystals", [])
    max_id = max((c["id"] for c in rift_crystals), default=0)
    match = [t for t in DEFAULT_RIFT_CRYSTALS if t["weaponId"] == weapon_id]
    if not match:
        return {"ok": False, "error": f"no template for weaponId {weapon_id}"}
    new = dict(match[0])
    new["id"] = max_id + 1
    new["createdAt"] = now_iso()
    new["updatedAt"] = now_iso()
    rift_crystals.append(new)
    save_state(st)
    return {"ok": True, "crystal": new}

@app.post("/admin/api/state/reload")
async def admin_reload_state():
    _load_or_create_active()
    return {"ok": True}

CONFIG_FILE = DATA_DIR / "response_config.json"

@app.get("/admin/api/config")
async def admin_get_config():
    return json.loads(CONFIG_FILE.read_text())

@app.post("/admin/api/config/save")
async def admin_save_config(body: dict):
    CONFIG_FILE.write_text(json.dumps(body, indent=2))
    global RCFG
    RCFG = body
    return {"ok": True}

@app.get("/admin/api/logs")
async def admin_get_logs():
    return LOG_BUF[-100:]

@app.get("/admin/api/system")
async def admin_system():
    uptime = int(time.time() - SERVER_START_TIME)
    return {
        "version": SERVER_VERSION,
        "patchFolder": PATCH_FOLDER,
        "startTime": datetime.datetime.fromtimestamp(SERVER_START_TIME).strftime("%Y-%m-%d %H:%M:%S"),
        "uptime": uptime,
        "uptimeStr": f"{uptime//3600}h{(uptime%3600)//60}m{uptime%60}s",
        "routeCount": len(ROUTE_MODELS),
        "overrideCount": len(OVERRIDES),
        "playerCount": playerdb.count(),
        "cdmFiles": len(_CDN_FILES),
        "logLines": len(LOG_BUF),
    }

@app.get("/admin/api/routes")
async def admin_routes():
    items = []
    for path, model in sorted(ROUTE_MODELS.items()):
        is_overridden = path in OVERRIDES
        items.append({
            "path": path,
            "model": model.__class__.__name__ if hasattr(model, '__class__') else str(model)[:60],
            "overridden": is_overridden,
        })
    return {"routes": items, "total": len(items)}

@app.get("/admin/api/cdn")
async def admin_cdn():
    items = []
    for name, data in sorted(_CDN_FILES.items()):
        items.append({"name": name, "size": len(data)})
    return {"files": items, "total": len(items)}

@app.post("/admin/api/restart")
async def admin_restart():
    import os, sys
    os.execl(sys.executable, sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080")

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
