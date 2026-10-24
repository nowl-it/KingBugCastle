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

The mods (all real fixes EXCEPT the buff numbers of mod 9, which are test values):
  1. CCRatio -100 -> 0            enemies become crowd-control-able
  2. Treasure 30040 gate -> 170100  Shadowless shows on a fallback v170 client
  3. Treasure 30043 gate -> 172001 Vitacorde shows on the deployed v172.0.01 client
  4. Stage 101 dummy spawns       chapter I-1 walk-over clearable for testing
  5. UnitPanelData 10800/10810    Cathy/Alessia Profile tab (devs shipped none)
  6. Cathy Overcome field typo    {Overcome:...AuraDamagePer} -> ...AuraTotalDamagePer
  7. FetchComplete strings         the private-server "Ready to bug" loading text
  8. Cor Orbis 50002 strings (EN/VI)  leaked 2026-09-08, purged by the 2026-09-10
                                  republish.
  9. Cor Orbis 50002 rows         the Treasure + BuffData 3500020..3500025 rows those
                                  strings describe. The official design was never
                                  shipped, so the BUFF NUMBERS ARE TEST VALUES (see
                                  the ponytail note on _CORORBIS_BUFFS). The desc-param
                                  constants are NOT guesses: they are forced to match
                                   the placeholder count of the leaked strings. Art uses
                                   the default TreasureIcon_50002 / TreasureIllust_50002
                                   names (missing in every build) so the client shows
                                   its placeholder - never another treasure's art.

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


# ── 2-3. Treasures: un-gate to supported deployed client versions ────────────
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


# ── 8. Cor Orbis (Treasure 50002) strings: leaked 2026-09-08, purged 2026-09-10 ──
# Text only. A rendering treasure still needs a <Treasure ID="50002"> row and
# BuffData 3500020..25, neither of which was ever leaked - do not invent them here.
# 18 keys are VERBATIM operator-supplied data (the 2026-09-08 leak block). The
# operator asked for the two placeholders back in-game style, so TreasureSubName/
# TreasureDesc are ours again: "Breath of the Living" + the mana poem. Everything
# else must stay byte-exact. SpecialPackage_1690..1692 and AdsSummonRestrictionAlert
# are NOT written (live keys the operator dropped). _apply_cororbis OVERWRITES a
# differing value so this stays true after every refresh.
_CORORBIS = {
    "EN_US": {
        "TreasureName_50002": "Cor Orbis",
        "TreasureSubName_50002": "Breath of the Living",
        "TreasureDesc_50002": (
            "From root and fang it drinks the wandering mana,\n"
            "hoards it in silence,\n"
            "then pours it all back in a single flood"),
        "TreasureSkillName_50002": "MP Combination",
        "BuffDataName_3500021": "Assimilation I",
        "BuffDataName_3500022": "MP Barrier I",
        "BuffDataName_3500023": "MP Resonance",
        "BuffDataName_3500024": "MP Barrier II",
        "BuffDataName_3500025": "Assimilation II",
        "SpecialShop_TreasurePickUp50002": "Cor Orbis Pickup Special Shop",
        "BuffDataDesc_3500021": "For every {1}% Spell CRIT Damage above {0}%, "
                                "the enhanced skill's Final Damage increase is multiplied by {2}",
        "BuffDataDesc_3500022": "Damage Taken {0}% until the 3rd skill use",
        "BuffDataDesc_3500023": "Upon using an enhanced skill, additionally uses the same skill "
                                "on 2 random targets for {0}% Damage",
        "BuffDataDesc_3500024": "Damage Taken {0}% until the 3rd skill use",
        "BuffDataDesc_3500025": "For every {1}% Spell CRIT Damage above {0}%, "
                                "the enhanced skill's Final Damage increase is multiplied by {2}",
        "TreasureSkillDesc_3500020": (
            "After Battle starts, the highest-Tier Hero equipped with Cor Orbis gains "
            "+{0}% Max MP and -{1}% Final Damage Dealt until using a skill 3 times.\n"
            "The last skill is enhanced, increasing Final Damage by +{2}%"),
        "TreasureSkillDesc_3500021": (
            "After Battle starts, the highest-Tier Hero equipped with Cor Orbis gains "
            "+{0}% Max MP and -{1}% Final Damage Dealt until using a skill 3 times.\n"
            "The last skill is enhanced, increasing Final Damage by +{2}%.\n"
            "For every {4}% Spell CRIT Damage above {3}%, the enhanced skill's Final Damage "
            "increase is multiplied by {5}"),
        "TreasureSkillDesc_3500022": (
            "After Battle starts, the highest-Tier Hero equipped with Cor Orbis gains "
            "+{0}% Max MP and -{1}% Final Damage Dealt until using a skill 3 times.\n"
            "The last skill is enhanced, increasing Final Damage by +{2}%.\n"
            "For every {4}% Spell CRIT Damage above {3}%, the enhanced skill's Final Damage "
            "increase is multiplied by {5}\n"
            "Damage Taken {6}% until using a skill 3 times"),
        "TreasureSkillDesc_3500023": (
            "After Battle starts, the highest-Tier Hero equipped with Cor Orbis gains "
            "+{0}% Max MP and -{1}% Final Damage Dealt until using a skill 3 times.\n"
            "The last skill is enhanced, increasing Final Damage by +{2}%.\n"
            "For every {4}% Spell CRIT Damage above {3}%, the enhanced skill's Final Damage "
            "increase is multiplied by {5}\n"
            "Damage Taken {6}% until using a skill 3 times\n"
            "Upon using an enhanced skill, additionally uses the same skill on 2 random "
            "targets for {7}% Damage"),
    },
    "VI": {
        "TreasureName_50002": "Cor Orbis",
        "TreasureSubName_50002": "Hơi Thở Của Sinh Mệnh",
        "TreasureDesc_50002": (
            "Từ rễ cây đến nanh thú, nó hút lấy Mana lang thang,\n"
            "giữ yên trong lặng,\n"
            "rồi đổ trào trả lại tất cả"),
        "TreasureSkillName_50002": "Hợp Nhất Mana",
        "BuffDataName_3500021": "Đồng Hóa I",
        "BuffDataName_3500022": "Kết Giới Mana I",
        "BuffDataName_3500023": "Cộng Hưởng Mana",
        "BuffDataName_3500024": "Kết Giới Mana II",
        "BuffDataName_3500025": "Đồng Hóa II",
        "SpecialShop_TreasurePickUp50002": "Cửa Hàng Đặc Biệt Pickup Cor Orbis",
        "BuffDataDesc_3500021": "Cứ mỗi {1}% Sát thương chí mạng phép vượt quá {0}%, "
                                "mức tăng ST tổng của kỹ năng cường hóa được nhân {2} lần",
        "BuffDataDesc_3500022": "ST phải nhận {0}% đến lần dùng kỹ năng thứ 3",
        "BuffDataDesc_3500023": "Khi dùng kỹ năng cường hóa, dùng thêm cùng kỹ năng "
                                "lên 2 mục tiêu ngẫu nhiên với ST {0}%",
        "BuffDataDesc_3500024": "ST phải nhận {0}% đến lần dùng kỹ năng thứ 3",
        "BuffDataDesc_3500025": "Cứ mỗi {1}% Sát thương chí mạng phép vượt quá {0}%, "
                                "mức tăng ST tổng của kỹ năng cường hóa được nhân {2} lần",
        "TreasureSkillDesc_3500020": (
            "Sau khi Chiến Đấu bắt đầu, Anh Hùng có cấp ★ cao nhất trong số các Anh Hùng gắn "
            "Cor Orbis nhận +{0}% Mana tối đa và -{1}% ST gây ra tổng đến lần dùng kỹ năng thứ 3\n"
            "Kỹ năng cuối được cường hóa, tăng ST tổng +{2}%"),
        "TreasureSkillDesc_3500021": (
            "Sau khi Chiến Đấu bắt đầu, Anh Hùng có cấp ★ cao nhất trong số các Anh Hùng gắn "
            "Cor Orbis nhận +{0}% Mana tối đa và -{1}% ST gây ra tổng đến lần dùng kỹ năng thứ 3\n"
            "Kỹ năng cuối được cường hóa, tăng ST tổng +{2}%\n"
            "Cứ mỗi {4}% Sát thương chí mạng phép vượt quá {3}%, mức tăng ST tổng của kỹ năng "
            "cường hóa được nhân {5} lần"),
        "TreasureSkillDesc_3500022": (
            "Sau khi Chiến Đấu bắt đầu, Anh Hùng có cấp ★ cao nhất trong số các Anh Hùng gắn "
            "Cor Orbis nhận +{0}% Mana tối đa và -{1}% ST gây ra tổng đến lần dùng kỹ năng thứ 3\n"
            "Kỹ năng cuối được cường hóa, tăng ST tổng +{2}%\n"
            "Cứ mỗi {4}% Sát thương chí mạng phép vượt quá {3}%, mức tăng ST tổng của kỹ năng "
            "cường hóa được nhân {5} lần\n"
            "ST phải nhận {6}% đến lần dùng kỹ năng thứ 3"),
        "TreasureSkillDesc_3500023": (
            "Sau khi Chiến Đấu bắt đầu, Anh Hùng có cấp ★ cao nhất trong số các Anh Hùng gắn "
            "Cor Orbis nhận +{0}% Mana tối đa và -{1}% ST gây ra tổng đến lần dùng kỹ năng thứ 3\n"
            "Kỹ năng cuối được cường hóa, tăng ST tổng +{2}%\n"
            "Cứ mỗi {4}% Sát thương chí mạng phép vượt quá {3}%, mức tăng ST tổng của kỹ năng "
            "cường hóa được nhân {5} lần\n"
            "ST phải nhận {6}% đến lần dùng kỹ năng thứ 3\n"
            "Khi dùng kỹ năng cường hóa, dùng thêm cùng kỹ năng lên 2 mục tiêu ngẫu nhiên "
            "với ST {7}%"),
    },
}


def _apply_cororbis(xml_dir, warns):
    n = 0
    for loc, entries in _CORORBIS.items():
        p = pathlib.Path(xml_dir) / f"Strings_{loc}.xml"
        if not p.exists():
            warns.append(f"[Strings_{loc}.xml] locale not present - Cor Orbis text NOT applied")
            continue
        txt = _read(p)
        if "</Strings>" not in txt:
            warns.append(f"[Strings_{loc}.xml] no </Strings> close - format moved?")
            continue
        changed = False
        for k, v in entries.items():
            m = re.search(rf'<String Key="{re.escape(k)}">(.*?)</String>', txt, re.S)
            if m is None:
                txt = txt.replace("</Strings>",
                                  f'  <String Key="{k}">{v}</String>\n</Strings>', 1)
                changed = True
            elif m.group(1) != v:
                txt = txt[:m.start(1)] + v + txt[m.end(1):]
                changed = True
        if not changed:
            continue
        _write(p, txt)
        n += 1
    return n


# ── 9. Cor Orbis 50002 rows (Treasures + TreasureBuffDatas) ──────────────────
# ponytail: the FixedValue/MCritic/TakeDamage numbers below are TEST VALUES - the
# official Cor Orbis buff table never shipped, so nobody knows them. The
# DescParams/TotalDescParams constants are NOT guesses: each row carries exactly
# as many <Const> as the leaked string for that row has {N} placeholders, in
# index order, so every placeholder renders a real number instead of blank.
# Two desc/effect gaps are deliberate (no generic machinery can express them):
#   * "until using a skill 3 times"  -> buffs are applied at BattleStart, permanent
#   * BuffDataDesc_3500023 splash    -> implemented as a Mana refund on skill cast
_TREASURE_50002 = """    <Treasure ID="50002">
        <Comment>Cor Orbis (local row - not shipped by the devs)</Comment>
        <Rarity>Special</Rarity>
        <LimitedEdition>true</LimitedEdition>

        <Role>Mystic</Role>
        <BuffDataStartID>3500020</BuffDataStartID>
        <Color>8381EE</Color>
        <SubNameColor>FEEEAA</SubNameColor>
        <CardIllustOffsetX>0</CardIllustOffsetX>
        <CardIllustOffsetY>0</CardIllustOffsetY>
        <MinVersion>170000</MinVersion>
    </Treasure>
"""

# Every DescParams/TotalDescParams list below is sized to the placeholder count of
# the leaked string it feeds, in {N} index order - so no placeholder renders blank.
_CORORBIS_BUFFS = """    <BuffData ID="3500020">
        <Comment>Cor Orbis TEST VALUES - battle start: +Max MP, -Final Damage Dealt</Comment>

        <DescParams>
        </DescParams>

        <TotalDescParams>
            <Const>30</Const>
            <Const>20</Const>
            <Const>40</Const>
        </TotalDescParams>

        <BuffOptions>
            <Conditions>
                <MeIsBestTierUnit />
                <BattleStart />
            </Conditions>

            <Targets>
                <Self />
            </Targets>

            <RangeInfo>
                <RangeType>Self</RangeType>
            </RangeInfo>

            <BuffContents>
                <AddStat StatType="MaxMana" StatValueType="TotalPerValue" MaxOverlapCount="1" />
            </BuffContents>

            <Values>
                <FixedValue>30</FixedValue>
            </Values>
        </BuffOptions>

        <BuffOptions>
            <Conditions>
                <MeIsBestTierUnit />
                <BattleStart />
            </Conditions>

            <Targets>
                <Self />
            </Targets>

            <RangeInfo>
                <RangeType>Self</RangeType>
            </RangeInfo>

            <BuffContents>
                <AddStat StatType="Damage" StatValueType="TotalPerValue" MaxOverlapCount="1" />
            </BuffContents>

            <Values>
                <FixedValue>-20</FixedValue>
            </Values>
        </BuffOptions>
    </BuffData>

    <BuffData ID="3500021" Inherit="3500020">
        <Comment>Assimilation I (TEST VALUES)</Comment>

        <DescParams>
            <Const>20</Const>
            <Const>10</Const>
            <Const>2</Const>
        </DescParams>

        <TotalDescParams>
            <Const>30</Const>
            <Const>20</Const>
            <Const>40</Const>
            <Const>20</Const>
            <Const>10</Const>
            <Const>2</Const>
        </TotalDescParams>

        <BuffOptions>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>

        <BuffOptions>
            <Conditions>
                <MeIsBestTierUnit />
                <BattleStart />
            </Conditions>

            <Targets>
                <Self />
            </Targets>

            <RangeInfo>
                <RangeType>Self</RangeType>
            </RangeInfo>

            <BuffContents>
                <AddStat StatType="MCriticalDamageMul" StatValueType="BaseValue" MaxOverlapCount="1" />
            </BuffContents>

            <Values>
                <FixedValue>50</FixedValue>
            </Values>
        </BuffOptions>
    </BuffData>

    <BuffData ID="3500022" Inherit="3500021">
        <Comment>MP Barrier I (TEST VALUES)</Comment>

        <DescParams>
            <Const>-30</Const>
        </DescParams>

        <TotalDescParams>
            <Const>30</Const>
            <Const>20</Const>
            <Const>40</Const>
            <Const>20</Const>
            <Const>10</Const>
            <Const>2</Const>
            <Const>-30</Const>
        </TotalDescParams>

        <BuffOptions>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>

        <BuffOptions>
            <Conditions>
                <MeIsBestTierUnit />
                <BattleStart />
            </Conditions>

            <Targets>
                <Self />
            </Targets>

            <RangeInfo>
                <RangeType>Self</RangeType>
            </RangeInfo>

            <BuffContents>
                <AddStat StatType="TakeDamage" StatValueType="TotalPerValue" MaxOverlapCount="1" />
            </BuffContents>

            <Values>
                <FixedValue>-30</FixedValue>
            </Values>
        </BuffOptions>
    </BuffData>

    <BuffData ID="3500023" Inherit="3500022">
        <Comment>MP Resonance (TEST VALUES - mana refund stands in for the leaked splash effect)</Comment>

        <DescParams>
            <Const>250</Const>
        </DescParams>

        <TotalDescParams>
            <Const>30</Const>
            <Const>20</Const>
            <Const>40</Const>
            <Const>20</Const>
            <Const>10</Const>
            <Const>2</Const>
            <Const>-30</Const>
            <Const>250</Const>
        </TotalDescParams>

        <BuffOptions>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>

        <BuffOptions>
            <Conditions>
                <MeIsBestTierUnit />
                <AfterCastSkill />
            </Conditions>

            <CoolTime>3</CoolTime>

            <Targets>
                <Self />
            </Targets>

            <RangeInfo>
                <RangeType>Self</RangeType>
            </RangeInfo>

            <BuffContents>
                <HealManaPer />
            </BuffContents>

            <Values>
                <FixedValue>30</FixedValue>
            </Values>
        </BuffOptions>
    </BuffData>

    <BuffData ID="3500024" Inherit="3500023">
        <Comment>MP Barrier II (TEST VALUES - overrides option 4 in place)</Comment>

        <DescParams>
            <Const>-40</Const>
        </DescParams>

        <TotalDescParams>
            <Const>30</Const>
            <Const>20</Const>
            <Const>40</Const>
            <Const>20</Const>
            <Const>10</Const>
            <Const>2</Const>
            <Const>-30</Const>
            <Const>250</Const>
        </TotalDescParams>

        <BuffOptions>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>

        <BuffOptions>
            <Values>
                <FixedValue>-40</FixedValue>
            </Values>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>
    </BuffData>

    <BuffData ID="3500025" Inherit="3500024">
        <Comment>Assimilation II (TEST VALUES - overrides option 3 in place)</Comment>

        <DescParams>
            <Const>20</Const>
            <Const>10</Const>
            <Const>3</Const>
        </DescParams>

        <TotalDescParams>
            <Const>30</Const>
            <Const>20</Const>
            <Const>40</Const>
            <Const>20</Const>
            <Const>10</Const>
            <Const>2</Const>
            <Const>-30</Const>
            <Const>250</Const>
        </TotalDescParams>

        <BuffOptions>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>

        <BuffOptions>
            <Values>
                <FixedValue>100</FixedValue>
            </Values>
        </BuffOptions>

        <BuffOptions>
            <Values>
                <FixedValue>-40</FixedValue>
            </Values>
        </BuffOptions>
        <BuffOptions>
        </BuffOptions>
    </BuffData>

"""


def _apply_cororbis_rows(xml_dir, warns):
    n = 0
    p = pathlib.Path(xml_dir) / "Treasures.xml"
    if not p.exists():
        warns.append("[Treasures.xml] missing - Cor Orbis row NOT applied")
    else:
        txt = _read(p)
        if '<Treasure ID="50002">' not in txt:
            if "</Treasures>" not in txt:
                warns.append("[Treasures.xml] no </Treasures> close - Cor Orbis row NOT applied")
            else:
                _write(p, txt.replace("</Treasures>", _TREASURE_50002 + "</Treasures>", 1))
                n += 1
        else:
            # Strip the borrowed-50000 art tags from an already-present row so the
            # defaults (TreasureIcon_50002 / TreasureIllust_50002 -> placeholder) win.
            def _no_art(m):
                return re.sub(r"\s*<(IconName|IllustName|IllustBGName|CardIllustName|SkillIcon)>"
                              r"[^<]*</\1>", "", m.group(0))
            new = re.sub(r'<Treasure ID="50002">.*?</Treasure>', _no_art, txt,
                         count=1, flags=re.S)
            if new != txt:
                _write(p, new)
                n += 1

    p = pathlib.Path(xml_dir) / "TreasureBuffDatas.xml"
    if not p.exists():
        warns.append("[TreasureBuffDatas.xml] missing - Cor Orbis buff rows NOT applied")
    else:
        txt = _read(p)
        if '<BuffData ID="3500020">' not in txt:
            if "</BuffDatas>" not in txt:
                warns.append("[TreasureBuffDatas.xml] no </BuffDatas> close - buff rows NOT applied")
            else:
                _write(p, txt.replace("</BuffDatas>", _CORORBIS_BUFFS + "</BuffDatas>", 1))
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
    n += _apply_cororbis(xml_dir, warns)
    n += _apply_cororbis_rows(xml_dir, warns)
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
    (d / "TreasureBuffDatas.xml").write_text(
        "<BuffDatas>\n    <BuffData ID=\"3500010\">\n    </BuffData>\n</BuffDatas>",
        encoding="utf-8")
    for loc in ("VI", "EN_US"):
        (d / f"Strings_{loc}.xml").write_text(
            '<Strings><String Key="FetchComplete">Ready to go!</String>'
            '<String Key="Overcome_10800_0">+{Overcome:Unit10800AI_AuraDamagePer}%</String></Strings>',
            encoding="utf-8")

    n, warns = apply(str(d))
    assert not warns, warns
    # Units + Treasures(gates) + Stages + UnitPanelDatas (4) + 2 locale typo edits
    # + 2 FetchComplete edits + 2 Cor Orbis locale edits + 2 Cor Orbis row edits
    # (Treasures + TreasureBuffDatas) = 12 writes.
    assert n == 12, f"expected 12 file writes on fresh data, got {n}"
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
    assert _CORORBIS["VI"]["TreasureSubName_50002"] in _read(d / "Strings_VI.xml")
    assert _CORORBIS["EN_US"]["TreasureSkillDesc_3500023"] in _read(d / "Strings_EN_US.xml")
    # The dropped package keys must never be written.
    assert "SpecialPackage_1690" not in _read(d / "Strings_EN_US.xml")
    # Mod 9: the Cor Orbis rows exist and are complete.
    assert '<Treasure ID="50002">' in _read(d / "Treasures.xml")
    assert "<MinVersion>170000</MinVersion>" in _read(d / "Treasures.xml")
    # No art override: defaults are TreasureIcon_50002 / TreasureIllust_50002,
    # which do not exist in any build, so the client shows its placeholder.
    row = re.search(r'<Treasure ID="50002">.*?</Treasure>',
                    _read(d / "Treasures.xml"), re.S).group(0)
    assert "50000" not in row, "Cor Orbis must not borrow 50000 art"
    assert "<IconName>" not in row
    buffs = _read(d / "TreasureBuffDatas.xml")
    for i in range(3500020, 3500026):
        assert f'<BuffData ID="{i}"' in buffs, i

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
    print("ok: local_mods behave (9 mods, all idempotent)")


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
