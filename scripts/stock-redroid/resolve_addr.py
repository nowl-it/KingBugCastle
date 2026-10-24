#!/usr/bin/env python3
"""Resolve a guest address (e.g. the FORTIFY mutex) against a /proc/<pid>/maps snapshot.

usage: resolve_addr.py maps_FILE 0xADDR [0xADDR...]

Prints the mapping that contains each address plus, for mappings backed by an APK, the offset
*inside the zip entry* - libs are mapped straight out of split_config.*.apk, so
`file_offset = mapping_offset + (addr - mapping_start)` and the zip data_offset can be looked up
with `unzip -lv` to name the .so.
"""
import sys

def load(path):
    out = []
    for line in open(path):
        f = line.split()
        if len(f) < 5:
            continue
        lo, hi = (int(x, 16) for x in f[0].split('-'))
        off = int(f[2], 16)
        name = f[5] if len(f) > 5 else ''
        out.append((lo, hi, off, name))
    return out

def main():
    maps = load(sys.argv[1])
    for arg in sys.argv[2:]:
        a = int(arg, 16)
        hit = [m for m in maps if m[0] <= a < m[1]]
        if not hit:
            print(f"{arg}: no mapping (unmapped)")
            continue
        lo, hi, off, name = hit[0]
        print(f"{arg}: {lo:#x}-{hi:#x} file_off={off:#x} delta={a - lo:#x} "
              f"file_pos={off + (a - lo):#x} {name or '[anon]'}")

if __name__ == '__main__':
    main()
