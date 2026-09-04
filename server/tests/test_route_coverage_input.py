"""The coverage gate must inspect the deployed client, never a stale version."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile


_SERVER = Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))


def test_route_coverage_uses_configured_v172_metadata():
    from cli import route_coverage

    previous = os.environ.get("KGC_IL2CPP_SCRIPT_JSON")
    with tempfile.TemporaryDirectory() as temp_dir:
        script = Path(temp_dir) / "script.json"
        script.write_text(json.dumps({"ScriptString": [
            {"Value": "/pvp/info"},
            {"Value": "/asset.xml"},
        ]}))
        os.environ["KGC_IL2CPP_SCRIPT_JSON"] = str(script)
        route_coverage = importlib.reload(route_coverage)
        assert route_coverage.CLIENT_VERSION == "172.0.01"
        assert route_coverage.client_paths() == ["/pvp/info"]

    if previous is None:
        os.environ.pop("KGC_IL2CPP_SCRIPT_JSON", None)
    else:
        os.environ["KGC_IL2CPP_SCRIPT_JSON"] = previous
    importlib.reload(route_coverage)
