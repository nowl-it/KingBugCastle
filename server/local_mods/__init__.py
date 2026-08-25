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
  3. Treasure 30043 gate -> 172001 Vitacorde shows on the deployed v172.0.01 client
  4. Stage 101 dummy spawns       chapter I-1 walk-over clearable for testing
  5. UnitPanelData 10800/10810    Cathy/Alessia Profile tab (devs shipped none)
  6. Cathy Overcome field typo    {Overcome:...AuraDamagePer} -> ...AuraTotalDamagePer
  7. FetchComplete strings         the private-server "Ready to bug" loading text

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
# The devs did this themselves in patch 2026_07_21 - 135 bosses went -100 -> 0 - so as of
# that snapshot this mod only still bites unit 30000000, the new Story-Challenge boss they
# deliberately left immune. Keep it: it is a no-op when there is nothing left to zero, and
# a revert on their side silently restores boss CC-immunity otherwise.
def _apply_ccratio(xml_dir, warns):
    p = pathlib.Path(xml_dir) / "Units.xml"
    txt = _read(p)
    out = txt.replace("<CCRatio>-100</CCRatio>", "<CCRatio>0</CCRatio>")
    if out == txt:
        return 0
    _write(p, out)
    return 1


# ── 2–3. Treasures: un-gate to supported deployed client versions ────────────
_TREASURE_GATES = {
    30040: 170100,  # Shadowless: fallback v170 client
    30043: 172001,  # Vitacorde: deployed v172.0.01 client
}


def _apply_treasure_gates(xml_dir, warns):
    p = pathlib.Path(xml_dir) / "Treasures.xml"
    txt = _read(p)
    out = txt
    for treasure_id, target_version in _TREASURE_GATES.items():
        m = re.search(rf'<Treasure ID="{treasure_id}">.*?</Treasure>', out, re.S)
        if not m:
            warns.append(f"[Treasures.xml] {treasure_id} block not found - dev restructured? gate NOT applied")
            continue
        target = f"<MinVersion>{target_version}</MinVersion>"
        if target in m.group(0):
            continue
        block = re.sub(r"<MinVersion>\d+</MinVersion>", target, m.group(0))
        if block == m.group(0):
            warns.append(f"[Treasures.xml] {treasure_id} has no MinVersion to un-gate - dev changed it?")
            continue
        out = out[:m.start()] + block + out[m.end():]
    if out == txt:
        return 0
    _write(p, out)
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
    if "</UnitPanelDatas>" not in txt:
        warns.append("[UnitPanelDatas.xml] no </UnitPanelDatas> close - format moved?")
        return 0
    # New upstream data can contain one of the pair. Preserve it and add only the
    # missing panel: treating 10800 as proof that 10810 exists dropped Alessia
    # during the 2026_08_25 rebase.
    entries = "".join(_PANEL.format(id=unit_id) for unit_id in (10800, 10810)
                      if f'UnitPanelData ID="{unit_id}"' not in txt)
    if not entries:
        return 0
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


# ── 6. Loading complete text: preserve the private-server translation pass ────
_FETCH_COMPLETE = {
    "AR": "جاهز للحشرة! نبدأ بالإصلاح الآن!",
    "DE": "Bereit zum Bug! Fix wird jetzt gestartet!",
    "EN_US": "Ready to bug! Starting the fix now!",
    "ES_LA": "¡Listo para el bug! ¡Empezando la corrección ahora!",
    "FR": "Prêt pour le bug ! On commence la correction !",
    "JA": "バグ&lt;size=2&gt; &lt;/size&gt;-ready！&lt;size=2&gt; &lt;/size&gt;修正&lt;size=2&gt; &lt;/size&gt;を&lt;size=2&gt; &lt;/size&gt;開始&lt;size=2&gt; &lt;/size&gt;し&lt;size=2&gt; &lt;/size&gt;ます！",
    "KR": "버그 잡을 준비 완료! 수정 시작합니다!",
    "PT_BR": "Pronto pro bug! Iniciando a correção agora!",
    "RU": "Готов к багу! Начинаем исправление!",
    "TH": "พร้อมจับบั๊ก! เริ่มแก้ไขเดี๋ยวนี้!",
    "VI": "Sẵn sàng bắt bug! Bắt đầu fix ngay!",
    "ZH_CH": "准备&lt;size=2&gt; &lt;/size&gt;抓bug！&lt;size=2&gt; &lt;/size&gt;开始&lt;size=2&gt; &lt;/size&gt;修复！",
    "ZH_TW": "準備&lt;size=2&gt; &lt;/size&gt;抓bug！&lt;size=2&gt; &lt;/size&gt;開始&lt;size=2&gt; &lt;/size&gt;修復！",
}


def _apply_fetch_complete(xml_dir, warns):
    n = 0
    for p in glob.glob(str(pathlib.Path(xml_dir) / "Strings_*.xml")):
        path = pathlib.Path(p)
        value = _FETCH_COMPLETE.get(path.stem.removeprefix("Strings_"))
        if value is None:
            continue
        txt = _read(path)
        out, matches = re.subn(r'(<String Key="FetchComplete">).*?(</String>)',
                               rf'\g<1>{value}\g<2>', txt, count=1, flags=re.S)
        if not matches:
            warns.append(f"[{path.name}] FetchComplete key not found - text NOT applied")
            continue
        if out != txt:
            _write(path, out)
            n += 1
    return n


def apply(xml_dir):
    """Apply every local mod idempotently. Returns (applied_count, warnings)."""
    warns = []
    n = 0
    n += _apply_ccratio(xml_dir, warns)
    n += _apply_treasure_gates(xml_dir, warns)
    n += _apply_stage101(xml_dir, warns)
    n += _apply_panels(xml_dir, warns)
    n += _apply_overcome_typo(xml_dir, warns)
    n += _apply_fetch_complete(xml_dir, warns)
    return n, warns


def _check():
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp(prefix="local_mods_check_"))
    (d / "Units.xml").write_text(
        "<Units><Unit><CCRatio>-100</CCRatio></Unit></Units>", encoding="utf-8")
    (d / "Treasures.xml").write_text(
        '<Treasures><Treasure ID="30040"><MinVersion>171000</MinVersion></Treasure>'
        '<Treasure ID="30043"><MinVersion>173100</MinVersion></Treasure></Treasures>',
        encoding="utf-8")
    (d / "Stages.xml").write_text(
        "<Stages>\n\t<Stage ID='101' Theme='1' Inherit='1'>\n\t\t<ValueSum>2</ValueSum>\n\t</Stage>\n</Stages>",
        encoding="utf-8")
    (d / "UnitPanelDatas.xml").write_text(
        '<UnitPanelDatas>\n\t<UnitPanelData ID="10790"></UnitPanelData>\n</UnitPanelDatas>',
        encoding="utf-8")
    for loc in ("VI", "EN_US"):
        (d / f"Strings_{loc}.xml").write_text(
            '<Strings><String Key="FetchComplete">Ready to go!</String>'
            '<String Key="Overcome_10800_0">+{Overcome:Unit10800AI_AuraDamagePer}%</String></Strings>',
            encoding="utf-8")

    n, warns = apply(str(d))
    assert not warns, warns
    # 4 structural files + 2 locale typo edits + 2 FetchComplete edits = 8 writes.
    assert n == 8, f"expected 8 file writes on fresh data, got {n}"
    assert "<CCRatio>0</CCRatio>" in _read(d / "Units.xml")
    assert "<MinVersion>170100</MinVersion>" in _read(d / "Treasures.xml")
    assert "<MinVersion>172001</MinVersion>" in _read(d / "Treasures.xml")
    assert _read(d / "Stages.xml").count("99999") == 7
    assert 'UnitPanelData ID="10800"' in _read(d / "UnitPanelDatas.xml")
    assert 'UnitPanelData ID="10810"' in _read(d / "UnitPanelDatas.xml")
    assert "AuraDamagePer" not in _read(d / "Strings_VI.xml")
    assert "AuraTotalDamagePer" in _read(d / "Strings_VI.xml")
    assert _FETCH_COMPLETE["VI"] in _read(d / "Strings_VI.xml")
    assert _FETCH_COMPLETE["EN_US"] in _read(d / "Strings_EN_US.xml")

    # Partial upstream migration: Cathy may have shipped while Alessia did not.
    panels = d / "UnitPanelDatas.xml"
    _write(panels, re.sub(r'\t<UnitPanelData ID="10810">.*?</UnitPanelData>\n',
                          "", _read(panels), count=1, flags=re.S))
    n_partial, warns_partial = apply(str(d))
    assert n_partial == 1 and not warns_partial, (n_partial, warns_partial)
    assert 'UnitPanelData ID="10800"' in _read(panels)
    assert 'UnitPanelData ID="10810"' in _read(panels)

    # Idempotent: a second apply changes nothing.
    n2, warns2 = apply(str(d))
    assert n2 == 0 and not warns2, f"second apply not a no-op: {n2}, {warns2}"

    import shutil
    shutil.rmtree(d)
    print("ok: local_mods behave (7 mods, all idempotent)")


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
