#!/usr/bin/env python3
"""In data Bảo Cụ (Legacy) từ 1 snapshot CDN: tên, sub-name, mô tả, hero gợi ý, skill + buff.

Nguồn (không suy diễn gì thêm):
  Treasures.xml          -> Rarity/Role/LimitedEdition/BuffDataStartID/RecommendedUnitIds/MinVersion
  TreasureBuffDatas.xml  -> <BuffData ID=...> + <Comment> thiết kế (KR) + BuffOptions
  Skills.xml             -> skill thật mà BuffData tham chiếu (AddCustomBuffFromSkill / SkillCoefficient)
  Strings_<loc>.xml      -> TreasureName_/TreasureSubName_/TreasureDesc_/TreasureSkillName_
                            + BuffDataName_/BuffDataDesc_ + UnitName_

Dùng:
  scripts/treasure_peek.py <snapshot_dir>                     # cả bảng, 1 dòng / bảo cụ
  scripts/treasure_peek.py <snapshot_dir> --id 30044          # chi tiết đầy đủ
  scripts/treasure_peek.py <snapshot_dir> --new-vs <old_dir>  # chỉ bảo cụ mới/đổi (dùng cho watcher)
  scripts/treasure_peek.py <snapshot_dir> --check             # self-test
"""
import argparse
import os
import re
import sys

LOCALES = ("KR", "EN_US", "VI")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _text(x):
    """XML fragment -> 1 dòng text gọn."""
    x = re.sub(r"<[^>]+>", " ", x)
    x = x.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return re.sub(r"\s+", " ", x).strip()


def load_strings(snap, loc):
    p = os.path.join(snap, f"Strings_{loc}.xml")
    if not os.path.exists(p):
        return {}
    s = _read(p)
    out = {}
    for m in re.finditer(r'<String Key="([^"]+)"[^>]*>(.*?)</String>', s, re.S):
        out[m.group(1)] = _text(m.group(2))
    return out


def parse_treasures(snap):
    s = _read(os.path.join(snap, "Treasures.xml"))
    rows = {}
    for m in re.finditer(r'<Treasure ID="(\d+)"(.*?)</Treasure>', s, re.S):
        tid, body = int(m.group(1)), m.group(2)

        def field(tag, default=""):
            f = re.search(r"<%s>(.*?)</%s>" % (tag, tag), body, re.S)
            return _text(f.group(1)) if f else default

        rows[tid] = {
            "comment": field("Comment"),
            "rarity": field("Rarity"),
            "role": field("Role"),
            "limited": field("LimitedEdition").lower() == "true",
            "buff_start": int(field("BuffDataStartID") or 0),
            "units": [int(x) for x in re.findall(r"\d+", field("RecommendedUnitIds"))],
            "min_version": field("MinVersion"),
        }
    return rows


def parse_buffdatas(snap):
    """{buff_id: {'comment': str, 'options': int, 'skills': [id...]}}"""
    s = _read(os.path.join(snap, "TreasureBuffDatas.xml"))
    out = {}
    for m in re.finditer(r'<BuffData ID="(\d+)"(.*?)</BuffData>', s, re.S):
        bid, body = int(m.group(1)), m.group(2)
        c = re.search(r"<Comment>(.*?)</Comment>", body, re.S)
        out[bid] = {
            "comment": _text(c.group(1)) if c else "",
            "options": len(re.findall(r"<BuffOptions>", body)),
            "skills": sorted({int(x) for x in re.findall(r'(?:SkillID|SkillCoefficient ID)="(\d+)"', body)}),
        }
    return out


def buff_range(treasure, buffdatas, width=6):
    """BuffDataStartID + 6 dòng liên tiếp (đúng quy ước data: 3300430..3300435)."""
    start = treasure["buff_start"]
    return [i for i in range(start, start + width) if i in buffdatas]


def fmt_treasure(tid, t, strings, buffdatas, locales, full):
    L = []
    lim = " · LIMITED" if t["limited"] else ""
    units = ", ".join(
        f"{u} ({strings['KR'].get(f'UnitName_{u}', '?')})" for u in t["units"]
    ) or "-"
    L.append(f"=== {tid} · {strings['VI'].get(f'TreasureName_{tid}', '?')} "
             f"/ {strings['EN_US'].get(f'TreasureName_{tid}', '?')} "
             f"/ {strings['KR'].get(f'TreasureName_{tid}', '?')}"
             f"  [{t['rarity']} · {t['role']}{lim}]")
    if not full:
        sub = strings["VI"].get(f"TreasureSubName_{tid}", "")
        skill = strings["VI"].get(f"TreasureSkillName_{tid}", "")
        L.append(f"    VI: {sub} · skill: {skill} | hero gợi ý: {units} | "
                 f"buff {t['buff_start']} ({len(buff_range(t, buffdatas))} dòng) | minVersion {t['min_version']}")
        return L

    L.append(f"    hero gợi ý: {units}   minVersion: {t['min_version']}")
    for loc in locales:
        s = strings[loc]
        L.append(f"    [{loc}] name={s.get(f'TreasureName_{tid}', '-')} | "
                 f"sub={s.get(f'TreasureSubName_{tid}', '-')} | "
                 f"skill={s.get(f'TreasureSkillName_{tid}', '-')}")
        if s.get(f"TreasureDesc_{tid}"):
            L.append(f"          flavor: {s[f'TreasureDesc_{tid}']}")
    ids = buff_range(t, buffdatas)
    L.append(f"    BuffData {ids[0]}..{ids[-1]} ({len(ids)} dòng):")
    for bid in ids:
        b = buffdatas[bid]
        L.append(f"      [{bid}] {strings['VI'].get(f'BuffDataName_{bid}') or strings['KR'].get(f'BuffDataName_{bid}', '')}")
        vi = strings["VI"].get(f"TreasureSkillDesc_{bid}") or strings["VI"].get(f"BuffDataDesc_{bid}")
        if vi:
            L.append(f"          VI: {vi[:300]}")
        if b["comment"]:
            L.append(f"          KR(design): {b['comment'][:300]}")
        if b["skills"]:
            L.append(f"          skill refs: {b['skills']} · BuffOptions: {b['options']}")
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--id", type=int, action="append", default=[])
    ap.add_argument("--new-vs", metavar="OLD_SNAPSHOT")
    ap.add_argument("--locale", default=",".join(LOCALES))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--ntfy", action="store_true", help="chỉ in phần mới, cực gọn (cho watcher)")
    a = ap.parse_args()

    snap = a.snapshot
    treasures = parse_treasures(snap)
    buffdatas = parse_buffdatas(snap)
    locales = [x.strip() for x in a.locale.split(",") if x.strip()]
    strings = {loc: load_strings(snap, loc) for loc in set(locales) | {"KR", "VI", "EN_US"}}

    if a.check:
        t43 = treasures[30043]
        assert t43["buff_start"] == 3300430, t43
        assert t43["units"] == [10060], t43
        assert buff_range(t43, buffdatas) == [3300430 + i for i in range(6)]
        assert strings["VI"]["TreasureName_30043"] == "Vitacorde"
        assert strings["VI"]["TreasureSkillName_30043"]
        assert treasures[50000]["limited"] and treasures[50000]["buff_start"] == 3500000
        assert all(buff_range(t, buffdatas) for t in treasures.values()), "treasure thiếu BuffData"
        print(f"[check] OK — {len(treasures)} treasure, {len(buffdatas)} BuffData, "
              f"max treasure {max(treasures)}", file=sys.stderr)
        return

    if a.new_vs:
        old = parse_treasures(a.new_vs)
        new_ids = [tid for tid, t in sorted(treasures.items())
                   if tid not in old or old[tid]["buff_start"] != t["buff_start"]]
        if not new_ids:
            if not a.ntfy:
                print(f"Không có Bảo Cụ mới/đổi so với {os.path.basename(a.new_vs)} "
                      f"({len(treasures)} vẫn vậy, max id {max(treasures)})")
            return
        print(f"Bảo Cụ MỚI/ĐỔI vs {os.path.basename(a.new_vs)}: {new_ids}")
        for tid in new_ids:
            print("\n".join(fmt_treasure(tid, treasures[tid], strings, buffdatas, locales, full=not a.ntfy)))
        return

    ids = a.id or sorted(treasures)
    for tid in ids:
        t = treasures.get(tid)
        if not t:
            print(f"=== {tid}: KHÔNG có trong {os.path.basename(snap)}")
            continue
        print("\n".join(fmt_treasure(tid, t, strings, buffdatas, locales, full=True)))
        print()


if __name__ == "__main__":
    main()
