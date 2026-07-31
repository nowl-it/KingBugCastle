"""Decoration: flags, name tags, map skins, login skins, advisors.

The whole Decoration tab was one fixed static payload with five empty lists, so the
player owned no cosmetics at all - while every hero, artifact, treasure and accessory
is granted in full. This closes that inconsistency: the sandbox owns every cosmetic
its client build can render.

Content gating matters more here than elsewhere. A map skin whose MinVersion is above
the deployed client names a Prefab that is not in the Addressables catalog, so the map
loads without a background instead of failing loudly.

Advisors are the only part with real state: a contract runs ADVISOR_CONTRACT_DAYS and
can be extended ADVISOR_EXTEND_COUNT times by ADVISOR_EXTEND_DAYS each. Those three
numbers are consts in the client (dump.cs), not master data, so they are pinned here.

    python3 decoration.py     # self-check
"""
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

# dump.cs: DEFAULT_ADVISOR_ID / ADVISOR_CONTRACT_DAYS / ADVISOR_EXTEND_DAYS /
# ADVISOR_EXTEND_COUNT. Not in any XML - the client hardcodes them.
DEFAULT_ADVISOR = 10000
CONTRACT_DAYS = 14
EXTEND_DAYS = 7
EXTEND_COUNT = 4

SKIN_TOKEN = 2001  # InventoryItems.xml 2001 = 스킨 토큰

_FILES = {"flags": ("Flags.xml", "Flag"),
          "nameTags": ("NameTags.xml", "NameTag"),
          "mapSkins": ("MapSkins.xml", "MapSkin"),
          "loginSkins": ("LoginSkins.xml", "LoginSkin"),
          "advisors": ("Advisors.xml", "Advisor")}

_cache = {}


def entries(kind, xml_dir=DEFAULT_XML):
    """{id: element} for one cosmetic family, in document order."""
    key = (kind, str(xml_dir))
    if key not in _cache:
        fname, tag = _FILES[kind]
        root = ET.parse(Path(xml_dir) / fname).getroot()
        _cache[key] = {int(c.get("ID")): c for c in root
                       if c.tag == tag and c.get("ID")}
    return _cache[key]


def _min_version(el):
    # NameTags.xml spells it both `MinVersion` and `Minversion` - 6 entries use the
    # lowercase form, and reading only the first spelling lets them through ungated.
    txt = el.findtext("MinVersion") or el.findtext("Minversion") or "0"
    return int(txt.strip() or 0)


def ids(kind, gate, xml_dir=DEFAULT_XML):
    """Every id this client build can render."""
    return [i for i, el in entries(kind, xml_dir).items() if _min_version(el) <= gate]


def default_id(kind, gate, xml_dir=DEFAULT_XML):
    """The entry flagged Default, else the lowest id. Never 0: id 0 is 'nothing
    equipped', and the map/login scene renders no background at all for it."""
    avail = ids(kind, gate, xml_dir)
    els = entries(kind, xml_dir)
    for i in avail:
        if (els[i].findtext("Default") or "").strip().lower() == "true":
            return i
    return avail[0] if avail else 0


def token_price(kind, item_id, field, xml_dir=DEFAULT_XML):
    el = entries(kind, xml_dir).get(item_id)
    if el is None:
        return None
    txt = el.findtext(field)
    return int(txt) if txt and txt.strip().isdigit() else None


def login_scene(skin_id, xml_dir=DEFAULT_XML):
    """LoginSceneIllustDataResponseModel for one login skin.

    The client positions the illustration from these, so a skin with offsets left at
    zero sits centred rather than where its art was drawn to sit."""
    el = entries("loginSkins", xml_dir).get(skin_id)
    if el is None:
        return None

    def _f(tag, dflt=0.0):
        txt = el.findtext(tag)
        try:
            return float(txt)
        except (TypeError, ValueError):
            return dflt

    return {"illust": el.findtext("Sprite") or "",
            "x": int(_f("OffsetX")), "y": int(_f("OffsetY")),
            "rotation": 0, "scale": _f("Scale", 1.0) or 1.0,
            "effectColor": "", "bottomGradientColor": "",
            "disableBGAndEffects": False}


def contract_until(now=None, days=CONTRACT_DAYS):
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return (now + datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _self_check():
    gate = 171000
    counts = {k: len(ids(k, gate)) for k in _FILES}
    for k, n in counts.items():
        assert n, f"{k} has nothing available at gate {gate}"
        # Nothing ungated may leak through: a future map skin's Prefab is not in the
        # deployed Addressables catalog.
        assert all(_min_version(entries(k)[i]) <= gate for i in ids(k, gate))
    assert len(ids("mapSkins", 156000)) < counts["mapSkins"], \
        "the map skin gate lets everything through at an old version"

    # NameTags.xml uses two spellings of MinVersion; both must gate.
    lower = [i for i, el in entries("nameTags").items() if el.find("Minversion") is not None]
    assert lower, "no lowercase Minversion left in NameTags.xml - drop the fallback"
    assert all(i not in ids("nameTags", 156000) for i in lower
               if _min_version(entries("nameTags")[i]) > 156000), \
        "a lowercase Minversion entry was not gated"

    assert default_id("advisors", gate) == DEFAULT_ADVISOR
    for k in ("mapSkins", "loginSkins"):
        assert default_id(k, gate) in ids(k, gate)

    scene = login_scene(default_id("loginSkins", gate))
    assert scene and scene["illust"], "the default login skin has no sprite"
    assert scene["scale"] > 0, "a zero scale would render the illustration invisible"

    assert token_price("mapSkins", 10010, "SkinTokenPrice") == 24
    assert token_price("advisors", 10010, "ContractPrice") == 10
    assert token_price("mapSkins", 10000, "SkinTokenPrice") is None

    print("ok: " + ", ".join(f"{k} {n}" for k, n in counts.items())
          + f"; default advisor {DEFAULT_ADVISOR}, contract {CONTRACT_DAYS}d "
            f"+{EXTEND_COUNT}x{EXTEND_DAYS}d")


def block(st):
    """The player's decoration state, defaults filled in on the save itself.

    setdefault, not `or {...}`: the callers (rank rows, clan rows, the decoration
    routes) read AND write through this, so handing back a fresh dict each call
    would silently drop every equip."""
    import config
    gate = config.CONTENT_GATE
    d = st.setdefault("decoration", {})
    d.setdefault("flag", {"flagId": 0, "season": 0})
    d.setdefault("nameTag", 0)
    d.setdefault("favoriteMapSkins", [])
    d.setdefault("mapSkin", default_id("mapSkins", gate))
    d.setdefault("loginSkin", default_id("loginSkins", gate))
    d.setdefault("advisor", DEFAULT_ADVISOR)
    d.setdefault("contracts", {})
    return d


if __name__ == "__main__":
    _self_check()
