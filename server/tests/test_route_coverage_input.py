"""The coverage gate must inspect the deployed client, never a stale version."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


_SERVER = Path(__file__).resolve().parent.parent
_REPO = _SERVER.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))


def test_route_coverage_uses_bundled_client_version():
    from cli import route_coverage

    previous = os.environ.get("KGC_IL2CPP_SCRIPT_JSON")
    # The canonical bundled version comes from api/version.py (which reads
    # api/config.py's VERSION default) - the test must track it, not a hardcoded
    # version, so the coverage gate can never inspect a stale metadata tree again.
    expected = subprocess.check_output(
        [sys.executable, str(_REPO / "api" / "version.py")],
        text=True,
    ).strip()
    assert expected, "api/version.py must resolve a bundled version"
    assert route_coverage.CLIENT_VERSION == expected

    with tempfile.TemporaryDirectory() as temp_dir:
        script = Path(temp_dir) / "script.json"
        script.write_text(json.dumps({"ScriptString": [
            {"Value": "/pvp/info"},
            {"Value": "/asset.xml"},
        ]}))
        os.environ["KGC_IL2CPP_SCRIPT_JSON"] = str(script)
        route_coverage = importlib.reload(route_coverage)
        assert route_coverage.client_paths() == ["/pvp/info"]

    if previous is None:
        os.environ.pop("KGC_IL2CPP_SCRIPT_JSON", None)
    else:
        os.environ["KGC_IL2CPP_SCRIPT_JSON"] = previous
    importlib.reload(route_coverage)