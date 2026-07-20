#!/usr/bin/env python3
"""Local master-data mods for the private server - the SINGLE source of truth.

Applied idempotently on top of a FRESH CDN pull. Two callers share this:
  * ../refresh_master_data.py - new patch (new CDN folder): normalize changed files
    into xml_live, then replay these mods.
  * ../rebase_xml_live.py     - republish (devs rewrote the SAME folder in place):
    wipe xml_live from the fresh pristine clone, then replay these mods.

Keeping mods here - not baked into server/xml_live - means a data refresh can
overwrite xml_live wholesale and replay these, instead of hand-merging every patch.

Every op is idempotent (safe to run repeatedly) and appends a WARN it cannot
silently resolve - a missing anchor means the devs restructured the block we patch,
the one thing that needs a human. Everything else is mechanical.

The mods (all real fixes, no fabricated numbers):
  1. CCRatio -100 -> 0            enemies become crowd-control-able
  2. Treasure 30040 gate -> 170100  Shadowless shows on a fallback v170 client
  3. Stage 101 dummy spawns       chapter I-1 walk-over clearable for testing
  4. UnitPanelData 10800/10810    Cathy/Alessia Profile tab (devs shipped none)
  5. Cathy Overcome field typo    {Overcome:...AuraDamagePer} -> ...AuraTotalDamagePer

CRITICAL: Strings files must stay comment-free (Localizer breaks on <!-- -->).
None of these write a comment into a Strings file.

Dropped 2026-07-20: the old hand-written Cathy (10800/10810) strings + skill redirect
tags (strings_VI.txt / strings_EN_US.txt and Cathy _INSERTS). The 2026_07_14 republish
shipped official text for those keys, and ours had named 10810 "Ophelia" when it is
Alessia (Cathy's vampire form). Pristine wins - see docs/cdn-master-data.md.

`python3 -m server.local_mods <xml_dir>` (or run apply() from a caller) applies them;
`python3 server/local_mods/__init__.py --check` runs the self-test.
"""
import glob
import pathlib
import re

HERE = pathlib.Path(__file__).parent


def _read(p):
    return pathlib.Path(p).read_text(encoding="utf-8")


def _write(p, s):
    pathlib.Path(p).write_text(s, encoding="utf-8")


# ── 1. CCRatio -100 (crowd-control immune) -> 0 ───────────────────────────────
def _apply_ccratio(xml_dir, warns):
    p = pathlib.Path(xml_dir) / "Units.xml"
    txt = _read(p)
    out = txt.replace("<CCRatio>-100</CCRatio>", "<CCRatio>0</CCRatio>")
    if out == txt:
        return 0
    _write(p, out)
    return 1


# ── 2. Shadowless 30040: un-gate to the deployed client's version ─────────────
def _apply_treasure_gate(xml_dir, warns):
    p = pathlib.Path(xml_dir) / "Treasures.xml"
    txt = _read(p)
    m = re.search(r'<Treasure ID="30040">.*?</Treasure>', txt, re.S)
    if not m:
        warns.append("[Treasures.xml] 30040 block not found - dev restructured? gate NOT applied")
        return 0
    if "<MinVersion>170100</MinVersion>" in m.group(0):
        return 0  # already applied
    block = re.sub(r"<MinVersion>\d+</MinVersion>", "<MinVersion>170100</MinVersion>", m.group(0))
    if block == m.group(0):
        warns.append("[Treasures.xml] 30040 has no MinVersion to un-gate - dev changed it?")
        return 0
    _write(p, txt[:m.start()] + block + txt[m.end():])
    return 1


# ── 3. Stage 101 dummy (chapter I-1 all training dummies) ─────────────────────
_STAGE101 = (
    "\t<Stage ID='101' Theme='1' Inherit='1'>\n"
    "\t\t<ValueSum>0</ValueSum>\n"
    "\t\t<SpawnData Y='1'>\n"
    "\t\t\t<Spawn ID='99999' Pos='1' Level='1'/>\n"
    "\t\t\t<Spawn ID='99999' Pos='2' Level='1'/>\n"
    "\t\t\t<Spawn ID='99999' Pos='3' Level='1'/>\n"
    "\t\t\t<Spawn ID='99999' Pos='4' Level='1'/>\n"
    "\t\t\t<Spawn ID='99999' Pos='5' Level='1'/>\n"
    "\t\t</SpawnData>\n"
    "\t\t<SpawnData Y='2'>\n"
    "\t\t\t<Spawn ID='99999' Pos='2' Level='1'/>\n"
    "\t\t\t<Spawn ID='99999' Pos='4' Level='1'/>\n"
    "\t\t</SpawnData>\n"
    "\t</Stage>"
)


def _apply_stage101(xml_dir, warns):
    p = pathlib.Path(xml_dir) / "Stages.xml"
    txt = _read(p)
    m = re.search(r"\t<Stage ID='101' Theme='1' Inherit='1'>.*?</Stage>", txt, re.S)
    if not m:
        warns.append("[Stages.xml] stage 101 block not found - dummy NOT applied")
        return 0
    if "99999" in m.group(0):
        return 0  # already dummied
    _write(p, txt[:m.start()] + _STAGE101 + txt[m.end():])
    return 1


# ── 4. Cathy 10800 / Alessia 10810 Profile panel (devs shipped no entry) ──────
_PANEL = """\t<UnitPanelData ID="{id}">
\t\t<Type>Profile</Type>
\t\t<ProfileData>
\t\t\t<RealName/>
\t\t\t<Constellation/>
\t\t\t<Hobby/>
\t\t\t<Talent/>
\t\t\t<Likes/>
\t\t\t<Hates/>
\t\t\t<Note/>
\t\t</ProfileData>
\t\t<RecommendedStats>
\t\t\t<AtkPer/>
\t\t\t<AttackSpeed/>
\t\t\t<BaseCriticalProb/>
\t\t\t<BaseCriticalDamageMul/>
\t\t</RecommendedStats>
\t</UnitPanelData>
"""


def _apply_panels(xml_dir, warns):
    p = pathlib.Path(xml_dir) / "UnitPanelDatas.xml"
    txt = _read(p)
    if 'UnitPanelData ID="10800"' in txt:
        return 0  # already applied
    if "</UnitPanelDatas>" not in txt:
        warns.append("[UnitPanelDatas.xml] no </UnitPanelDatas> close - format moved?")
        return 0
    entries = _PANEL.format(id=10800) + _PANEL.format(id=10810)
    _write(p, txt.replace("</UnitPanelDatas>", entries + "</UnitPanelDatas>", 1))
    return 1


# ── 5. Cathy Overcome field-name typo (real value 10/20 in Units.xml) ─────────
def _apply_overcome_typo(xml_dir, warns):
    n = 0
    for p in glob.glob(str(pathlib.Path(xml_dir) / "Strings_*.xml")):
        txt = _read(p)
        out = txt.replace("Unit10800AI_AuraDamagePer", "Unit10800AI_AuraTotalDamagePer")
        if out != txt:
            _write(p, out)
            n += 1
    return n


def apply(xml_dir):
    """Apply every local mod idempotently. Returns (applied_count, warnings)."""
    warns = []
    n = 0
    n += _apply_ccratio(xml_dir, warns)
    n += _apply_treasure_gate(xml_dir, warns)
    n += _apply_stage101(xml_dir, warns)
    n += _apply_panels(xml_dir, warns)
    n += _apply_overcome_typo(xml_dir, warns)
    return n, warns


def _check():
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp(prefix="local_mods_check_"))
    (d / "Units.xml").write_text(
        "<Units><Unit><CCRatio>-100</CCRatio></Unit></Units>", encoding="utf-8")
    (d / "Treasures.xml").write_text(
        '<Treasures><Treasure ID="30040"><MinVersion>171000</MinVersion></Treasure></Treasures>',
        encoding="utf-8")
    (d / "Stages.xml").write_text(
        "<Stages>\n\t<Stage ID='101' Theme='1' Inherit='1'>\n\t\t<ValueSum>2</ValueSum>\n\t</Stage>\n</Stages>",
        encoding="utf-8")
    (d / "UnitPanelDatas.xml").write_text(
        '<UnitPanelDatas>\n\t<UnitPanelData ID="10790"></UnitPanelData>\n</UnitPanelDatas>',
        encoding="utf-8")
    for loc in ("VI", "EN_US"):
        (d / f"Strings_{loc}.xml").write_text(
            '<Strings><String Key="Overcome_10800_0">+{Overcome:Unit10800AI_AuraDamagePer}%</String></Strings>',
            encoding="utf-8")

    n, warns = apply(str(d))
    assert not warns, warns
    # 4 structural files + 2 locale Strings files = 6 file writes here (12+ in real data).
    assert n == 6, f"expected 6 file writes on fresh data, got {n}"
    assert "<CCRatio>0</CCRatio>" in _read(d / "Units.xml")
    assert "<MinVersion>170100</MinVersion>" in _read(d / "Treasures.xml")
    assert _read(d / "Stages.xml").count("99999") == 7
    assert 'UnitPanelData ID="10800"' in _read(d / "UnitPanelDatas.xml")
    assert 'UnitPanelData ID="10810"' in _read(d / "UnitPanelDatas.xml")
    assert "AuraDamagePer" not in _read(d / "Strings_VI.xml")
    assert "AuraTotalDamagePer" in _read(d / "Strings_VI.xml")

    # Idempotent: a second apply changes nothing.
    n2, warns2 = apply(str(d))
    assert n2 == 0 and not warns2, f"second apply not a no-op: {n2}, {warns2}"

    import shutil
    shutil.rmtree(d)
    print("ok: local_mods behave (5 mods, all idempotent)")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        _check()
    else:
        xd = sys.argv[1] if len(sys.argv) > 1 else str(HERE.parent / "xml_live")
        cnt, w = apply(xd)
        print(f"[local_mods] applied {cnt} mod(s) to {xd}")
        for line in w:
            print("  WARN " + line)
