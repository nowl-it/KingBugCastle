#!/usr/bin/env python3
"""Repaint original KGC frame 0 (Unit_10570_02) into Frieren, region-based.

Preserves the original pixel art geometry exactly; recolors by material zone
(hair/staff/robe/skin) and hand-places identity pixels (eyes, collar, ribbon).
Usage: python3 server/cli/repaint_frieren_frame0.py [frame_index]
"""
import sys
from PIL import Image

SRC = "/home/nowl/Code/kgc/server/assets/frieren/Unit_10570_02_reference.png"
OUT = "/home/nowl/Code/kgc/server/assets/frieren/drafts/frame0_frieren.png"

CELL = 130
FRAME = int(sys.argv[1]) if len(sys.argv) > 1 else 0
cx, cy = (FRAME % 5) * CELL, (FRAME // 5) * CELL

src = Image.open(SRC).convert("RGBA").crop((cx, cy, cx + CELL, cy + CELL))
pix = src.load()
out = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
op = out.load()

HAIR = ["#8f8ab5", "#b5b2d2", "#d6d5ec", "#f5f2ff"]
SKIN = ["#d99f99", "#f3c9ba", "#ffe4d8", "#fff0ea"]
ROBE = ["#8f8ab5", "#c9c6e2", "#e8e7f4", "#fbfaff"]
GOLD = ["#aa7c2f", "#d7a846", "#f0cb68"]
STAFF = ["#5e1c26", "#8a2d38", "#c44d58", "#e2707c"]
CYAN = ["#0f6570", "#174c63", "#28c8cf", "#7ff0ea"]
BOOT = ["#241a31", "#382b37", "#5a5580"]
OUTL = "#241a31"


def ramp(hexes, t):
    i = max(0, min(len(hexes) - 1, int(round(t * (len(hexes) - 1)))))
    c = hexes[i]
    return (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16), 255)


def red(hexc):
    return (int(hexc[1:3], 16), int(hexc[3:5], 16), int(hexc[5:7], 16), 255)


# ---- geometry (from pixel dump of the real sprite) ----
IN_HEAD = lambda x, y: 81 <= x <= 90 and 40 <= y <= 57   # head blob
IN_FACE = lambda x, y: 84 <= x <= 90 and 48 <= y <= 56   # face (wins over all)
IN_ORB = lambda x, y: 91 <= x <= 102 and 40 <= y <= 56   # staff head
IN_ROBE = lambda x, y: 45 <= x <= 84 and 52 <= y <= 97
IN_BOT = lambda x, y: 44 <= x <= 80 and 90 <= y <= 108
IN_SHAFT_U = lambda x, y: 82 <= x <= 101 and 55 <= y <= 72


def IN_CORRIDOR(x, y):
    if y >= 99:
        return True
    if 62 <= x <= 76 and 66 <= y <= 98:  # main diagonal across the robe
        return True
    if 82 <= x <= 101 and 55 <= y <= 72:  # upper shaft
        return True
    return False


def classify(x, y, r, g, b):
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    if g > 165 and b > 165 and r < 210:
        return "cyan"
    if r < 48 and g < 48 and b < 55:
        return "black"
    if r > 228 and g > 228 and b > 228:
        return "bright"
    if r - g >= 24 and r >= 95:
        if g - b >= 25:
            return "wood"        # yellow-brown (staff, gold, tan skin)
        if r >= 175:
            return "skin"        # pink-brown (flesh)
        return "brown"
    if r > 190 and g > 160 and b > 140 and luma > 140:
        return "beige"
    return "gray"


# ---- pass 1: recolor ----
for y in range(CELL):
    for x in range(CELL):
        r, g, b, a = pix[x, y]
        if not a:
            continue
        kind = classify(x, y, r, g, b)
        luma = 0.299 * r + 0.587 * g + 0.114 * b

        if kind == "cyan":
            op[x, y] = ramp(CYAN, min(1.0, luma / 225))
        elif kind == "black":
            if IN_ORB(x, y):
                op[x, y] = ramp(STAFF, 0.2)     # ring shading
            else:
                op[x, y] = red(OUTL)
        elif IN_FACE(x, y):
            # face wins: all tan/wood/bright/beige skin tones -> pale skin
            if luma > 235:
                op[x, y] = ramp(SKIN, 1.0)      # eye whites stay light
            else:
                op[x, y] = ramp(SKIN, 0.85 if luma > 200 else 0.5)
        elif kind == "bright":
            if IN_ORB(x, y):
                op[x, y] = ramp(GOLD, 0.9)
            elif IN_HEAD(x, y):
                op[x, y] = ramp(HAIR, 1.0)
            else:
                op[x, y] = ramp(ROBE, 1.0)
        elif kind == "skin":
            op[x, y] = ramp(SKIN, 0.7)
        elif kind == "wood":
            if IN_ORB(x, y):
                op[x, y] = ramp(GOLD, 0.5)
            elif IN_HEAD(x, y):
                op[x, y] = ramp(HAIR, 0.35)
            elif IN_CORRIDOR(x, y):
                op[x, y] = ramp(STAFF, 0.6 if luma > 150 else 0.3)
            elif IN_ROBE(x, y):
                op[x, y] = ramp(GOLD, 0.5)
            elif IN_BOT(x, y):
                op[x, y] = ramp(BOOT, 0.55)
            else:
                op[x, y] = ramp(STAFF, 0.5)
        elif kind == "brown":
            if IN_CORRIDOR(x, y):
                op[x, y] = ramp(STAFF, 0.5)
            elif IN_BOT(x, y):
                op[x, y] = ramp(BOOT, 0.5)
            else:
                op[x, y] = ramp(GOLD, 0.4)
        elif kind == "beige":
            if IN_FACE(x, y):
                op[x, y] = ramp(SKIN, 0.75)
            elif IN_HEAD(x, y):
                op[x, y] = ramp(HAIR, 0.6)
            elif IN_ORB(x, y):
                op[x, y] = ramp(GOLD, 0.6)
            elif IN_CORRIDOR(x, y):
                op[x, y] = ramp(STAFF, 0.7)
            else:
                op[x, y] = ramp(ROBE, 0.65)
        else:  # gray
            if IN_FACE(x, y):
                op[x, y] = ramp(SKIN, 0.5)
            elif IN_HEAD(x, y) and luma > 140:
                op[x, y] = ramp(HAIR, 0.55)
            elif IN_ORB(x, y):
                op[x, y] = ramp(GOLD, 0.35)
            elif IN_CORRIDOR(x, y):
                op[x, y] = ramp(STAFF, 0.35)
            else:
                op[x, y] = ramp(ROBE, 0.45 if luma > 160 else 0.25)

# ---- pass 2: identity pixels ----
# gold collar band at neck (row 57, x85-90)
for x in range(85, 91):
    if op[x, 57][3]:
        op[x, 57] = ramp(GOLD, 0.7)
# teal eyes: overwrite the original eye-white pixels
for px, py in ((87, 49), (88, 49), (87, 50), (88, 50)):
    op[px, py] = ramp(CYAN, 0.9)
# red earrings at head sides (below hair, on the face edge)
for ex, ey in ((84, 51), (90, 51)):
    if op[ex, ey][3]:
        op[ex, ey] = red("#d91d3f")
# red ribbon on lower staff shaft
for rx, ry in ((63, 93), (64, 94), (65, 95)):
    if op[rx, ry][3]:
        op[rx, ry] = ramp(("#711b26", "#b83242"), 0.7)

out.save(OUT)
print(f"saved {OUT}")
print(f"bbox: {out.getbbox()}  target (45,38,109,109)")
print(f"colors: {len(out.getcolors(maxcolors=100000))}")