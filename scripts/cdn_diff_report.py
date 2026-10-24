#!/usr/bin/env python3
"""So sánh 2 thư mục xml đã extract từ CDN bundle, in báo cáo người-đọc-được.

check_cdn_update.sh dùng khi phát hiện republish / patch mới: bundle tải về được
extract ra thư mục tạm (scripts/extract_xml.py — đặt tên file giống hệt snapshot
local), rồi script này so với snapshot local → liệt kê file added/removed/changed
kèm ID/Key master data bị thêm/bỏ. "Rõ hơn" thay vì chỉ báo etag đổi.

Usage: cdn_diff_report.py <OLD_DIR> <NEW_DIR> [--max-detail N] [--samples N]
Exit: 0 = giống hệt, 1 = có khác biệt, 2 = lỗi (thiếu thư mục,...).
"""
import argparse
import os
import re
import sys

ID_RE = re.compile(rb'\bID="([^"]+)"')
KEY_RE = re.compile(rb'\bKey="([^"]+)"')


def load(d):
    out = {}
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                out[name] = f.read()
    return out


def _ids(blob):
    return set(m.decode("utf-8", "replace") for m in ID_RE.findall(blob))


def _keys(blob):
    return set(m.decode("utf-8", "replace") for m in KEY_RE.findall(blob))


def _sample(vals, n):
    vals = sorted(vals)
    if not vals:
        return "—"
    head = ", ".join(vals[:n])
    return head + (" … (+%d)" % (len(vals) - n) if len(vals) > n else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--max-detail", type=int, default=20)
    ap.add_argument("--samples", type=int, default=10)
    a = ap.parse_args()
    for d in (a.old, a.new):
        if not os.path.isdir(d):
            print("thư mục không tồn tại: %s" % d, file=sys.stderr)
            return 2
    old, new = load(a.old), load(a.new)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    if not (added or removed or changed):
        print("files: giống hệt (%d files)" % len(new))
        return 0
    print(
        "files: +%d mới, -%d bị xoá, ~%d đổi nội dung"
        % (len(added), len(removed), len(changed))
    )
    for n in added:
        print("  + %s" % n)
    for n in removed:
        print("  - %s" % n)
    for n in changed[: a.max_detail]:
        o, x = old[n], new[n]
        di = _ids(x) - _ids(o)   # ID mới
        dk = _ids(o) - _ids(x)   # ID bị xoá
        pk = _keys(x) - _keys(o) # Key mới (Strings,...)
        qk = _keys(o) - _keys(x) # Key bị xoá
        delta = []
        if di:
            delta.append("+%d ID" % len(di))
        if dk:
            delta.append("-%d ID" % len(dk))
        if pk:
            delta.append("+%d Key" % len(pk))
        if qk:
            delta.append("-%d Key" % len(qk))
        if not delta:
            delta.append("%d→%d B" % (len(o), len(x)))
        print("  ~ %s  (%s)" % (n, ", ".join(delta)))
        if di:
            print("      ID  mới : %s" % _sample(di, a.samples))
        if dk:
            print("      ID  mất : %s" % _sample(dk, a.samples))
        if pk:
            print("      Key mới : %s" % _sample(pk, a.samples))
        if qk:
            print("      Key mất : %s" % _sample(qk, a.samples))
    if len(changed) > a.max_detail:
        print(
            "  … +%d file đổi nữa (chạy lại với --max-detail lớn hơn)"
            % (len(changed) - a.max_detail)
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
