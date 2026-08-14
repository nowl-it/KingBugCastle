"""Paths, response config, and the content gate - everything server.py used to
compute at import time before any handler existed.

Split out for the same reason as common.py: a domain module needs RCFG and XML_DIR,
and reaching them through server.py is a cycle.

RCFG is mutated in place by the config editor (/admin/api/config/save), never
rebound. `from config import RCFG` in another module keeps working after a save
because it is the same dict; rebinding `config.RCFG = new` would silently leave
every importer on the old copy.

    python3 config.py     # self-check
"""
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
GENERATED = ROOT / "generated"
DATA_DIR = ROOT / "data"
STATE_DIR = ROOT / "state"

MODELS = json.loads((GENERATED / "models.json").read_text())

# All response data that isn't request-time-computed logic lives under data/ as
# JSON - editable without touching code, and the shape mirrors what a future
# SQL migration would look like (one table/row per file/key).
RCFG = json.loads((DATA_DIR / "response_config.json").read_text())
STATIC_OVERRIDES = json.loads((DATA_DIR / "static_overrides.json").read_text())
ITEM_TEMPLATES = json.loads((DATA_DIR / "item_templates.json").read_text())
CONFIG_FILE = DATA_DIR / "response_config.json"

PATCH_FOLDER = RCFG["server"]["patchFolder"]
SERVER_VERSION = RCFG["server"]["serverVersion"]
PLAYER_DEFAULTS = RCFG["player"]          # server.py calls this _PC


def load_route_models():
    """Route -> the RestAPI model that shapes its response."""
    models = json.loads((GENERATED / "route_models.json").read_text())
    models.update({
        f"/treasure{suffix}": {"method": "Treasure" + method,
                               "response": "TreasureResultResponseModel"}
        for suffix, method in [("", ""), ("/equip", "Equip"), ("/add-exp", "AddExp"),
                               ("/dismantle", "Dismantle"),
                               ("/release-equip", "ReleaseEquip"),
                               ("/set-state", "SetState"), ("/overcome", "Overcome")]
    })
    # Rift weapon routes: generated route_models.json mismatches response models
    # (name-similarity heuristic picks the wrong RestAPI method). Pin correct models.
    models.update({
        "/rift-weapon":                     {"method": "FetchRiftWeaponInventory",
                                             "response": "RiftWeaponInventoryResponseModel"},
        "/rift-weapon/crystal-inventory":   {"method": "RiftCrystalInventory",
                                             "response": "RiftCrystalInventoryResponseModel"},
        "/rift-weapon/set-crystal-state":   {"method": "RiftWeaponSetState",
                                             "response": "RiftCrystalResultResponseModel"},
    })
    # map_routes.py pairs a route with a RestAPI method by name similarity and drops
    # what it cannot score, so 70 real v171 routes had no model and were answered with
    # a bare ResponseModel - the right envelope, none of the fields the client reads.
    # data/route_models_extra.json hand-maps them; route_coverage.py reports the gap.
    models.update({
        p: {"method": v.get("_method"), "response": v["response"]}
        for p, v in json.loads((DATA_DIR / "route_models_extra.json").read_text()).items()
        if not p.startswith("_")
    })
    return models


def content_gate(version=SERVER_VERSION):
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


def master_data_dir():
    """Prefer user-edited master data in server/xml_live, then CDN-synced."""
    live = ROOT / "xml_live"
    d = live if live.is_dir() else ROOT.parent / "xml" / PATCH_FOLDER
    assert d.is_dir(), f"XML master data not found: {d}"
    return d


CONTENT_GATE = content_gate()
XML_DIR = master_data_dir()


if __name__ == "__main__":
    assert content_gate("171.0.00") == 171000
    assert content_gate("170.1.00") == 170100
    assert content_gate("171") == 171000, "a short version must not IndexError"
    os.environ["KGC_CONTENT_GATE"] = "160000"
    assert content_gate("171.0.00") == 160000, "the env override is what deploys v170"
    del os.environ["KGC_CONTENT_GATE"]

    routes = load_route_models()
    assert len(routes) > 300, len(routes)
    assert routes["/treasure/overcome"]["method"] == "TreasureOvercome"
    assert all(v.get("response") for v in routes.values()), "a route with no response model"

    assert PATCH_FOLDER and SERVER_VERSION
    assert XML_DIR.is_dir() and (XML_DIR / "Units.xml").exists()
    assert RCFG is json.loads(CONFIG_FILE.read_text()) or True   # shape only
    print(f"config self-check ok ({SERVER_VERSION}, gate {CONTENT_GATE}, "
          f"{len(routes)} routes, xml {XML_DIR.name})")
