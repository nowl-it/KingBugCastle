"""The master-data MinVersion cutoff tracks serverVersion instead of a literal.

The gate was three separate `> 170100` literals. When the build moved to 171.0.00
they stayed behind, so the server advertised v171 to the client while filtering
every v171 hero, artifact and treasure out of its own listings as "unreleased" -
a silent content regression that looks exactly like the content not existing.
"""
import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server


def check_parses_versions():
    cases = {
        "170.1.00": 170100,
        "171.0.00": 171000,
        "171.1.00": 171100,
        "169.2.03": 169203,
        "171": 171000,          # short forms pad, they must not crash or truncate
        "171.0": 171000,
    }
    for v, want in cases.items():
        got = server._content_gate(v)
        assert got == want, f"_content_gate({v!r}) = {got}, want {want}"
    print(f"ok: {len(cases)} version strings parse to their build code")


def check_tracks_server_version():
    assert server.CONTENT_GATE == server._content_gate(server.SERVER_VERSION), \
        "CONTENT_GATE drifted from serverVersion"
    assert not [n for n in dir(server) if n == "CONTENT_GATE"] == [], "CONTENT_GATE missing"
    print(f"ok: serverVersion {server.SERVER_VERSION} -> gate {server.CONTENT_GATE}")


def check_env_override():
    """Deploying the v170 client needs the gate pinned back, or v171-gated content
    is sent to a client that cannot render it."""
    old = os.environ.get("KGC_CONTENT_GATE")
    os.environ["KGC_CONTENT_GATE"] = "170100"
    try:
        assert server._content_gate("171.0.00") == 170100, "KGC_CONTENT_GATE ignored"
    finally:
        os.environ.pop("KGC_CONTENT_GATE", None)
        if old is not None:
            os.environ["KGC_CONTENT_GATE"] = old
    print("ok: KGC_CONTENT_GATE overrides the derived gate")


def check_gate_actually_filters():
    """A gate that filters nothing would pass the checks above and still be broken."""
    import re
    txt = (server.XML_DIR / "Treasures.xml").read_text(encoding="utf-8")
    gated = [int(m) for m in re.findall(r"<MinVersion>(\d+)</MinVersion>", txt)]
    future = [v for v in gated if v > server.CONTENT_GATE]
    past = [v for v in gated if v <= server.CONTENT_GATE]
    assert past, "no treasure is below the gate - the gate is too low to be real"
    assert future, ("no master-data entry is above the gate, so nothing proves the "
                    "filter runs; if the devs really shipped everything, relax this")
    ids = server.ALL_TREASURE_IDS if hasattr(server, "ALL_TREASURE_IDS") else None
    print(f"ok: gate {server.CONTENT_GATE} splits Treasures.xml into "
          f"{len(past)} released / {len(future)} unreleased"
          + (f", {len(ids)} listed" if ids else ""))


def check_no_literal_gates_left():
    """Compare against a 6-digit build code anywhere in code (not prose) and the gate
    can drift again. Walked as an AST so the docstrings that explain the gate - which
    necessarily quote 170100 - do not read as violations."""
    import ast
    tree = ast.parse(Path(server.__file__).read_text())
    stray = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for side in [node.left, *node.comparators]:
            if isinstance(side, ast.Constant) and isinstance(side.value, int) \
                    and 100000 <= side.value <= 999999:
                stray.append((node.lineno, side.value))
    assert not stray, f"a hardcoded version gate came back at {stray}"
    print("ok: no hardcoded 6-digit version comparison remains in server.py")


if __name__ == "__main__":
    check_parses_versions()
    check_tracks_server_version()
    check_env_override()
    check_gate_actually_filters()
    check_no_literal_gates_left()
    print("\nall content gate checks passed")
