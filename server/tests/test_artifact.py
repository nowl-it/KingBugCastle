"""Sanity check for make_artifact's root-cause fix: targets.Count must equal
opt_count exactly (Normal=1..KingGod=4), or ArtifactOptionUI.Init crashes on
the client (KeyNotFoundException on "None" / ArgumentOutOfRangeException)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import server

OPT_COUNT = {"Normal": 1, "King": 2, "God": 3, "KingGod": 4}

for aid, level in server.ARTIFACT_LEVELS.items():
    art = server.make_artifact(1, aid)
    n = OPT_COUNT[level]
    assert len(art["options"]["targets"]) == n, f"{aid} ({level}): targets.Count={len(art['options']['targets'])}, want {n}"
    assert len(art["options"]["types"]) == 4
    assert len(art["options"]["lvs"]) == 4
    assert len(art["data"]["options"]) == 4
    assert art["options"]["types"][:n] == ["AtkSpeedPer"] * n
    assert art["options"]["types"][n:] == ["None"] * (4 - n)

print(f"ok: {len(server.ARTIFACT_LEVELS)} artifacts checked")
