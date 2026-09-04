#!/usr/bin/env python3
"""Frieren repaint frame 0 - final version, coordinate-based pixel mapping."""
from PIL import Image

SRC = "/home/nowl/Code/kgc/server/assets/frieren/reference_frames/00_Unit_10570_02_0.png"
OUT = "/home/nowl/Code/aseprite-mcp/workspace/frame0_frieren.png"

img = Image.open(SRC).convert("RGBA")
pix = img.load()
w, h = img.size

out = Image.new("RGBA", (130, 140), (0, 0, 0, 0))
op = out.load()

# Frieren palette
HAIR = [(245,242,255), (214,213,236), (181,178,210), (143,138,181)]
SKIN = [(255,228,216), (243,201,186), (217,159,153)]
EYE = (40, 200, 207)
EYE_D = (15, 101, 112)
STAFF = [(226,112,124), (196,77,88), (138,45,56), (94,28,38)]
GOLD = [(240,203,104), (215,168,70), (170,124,47)]
ROBE = [(251,251,255), (232,231,244), (197,194,231), (143,138,181)]
MAGIC = (60, 140, 220)  # blue magic, not teal
OUTLINE = (36, 26, 49)


def luma(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b


def staff_at(x, y):
    """Narrow shaft diagonal: (48,25)→(18,65), width ~4px."""
    if y < 25 or y > 68:
        return False
    cx = 48 - 0.8 * (y - 25)
    return abs(x - cx) <= 3


for y in range(h):
    for x in range(w):
        r, g, b, a = pix[x, y]
        if a == 0:
            continue

        # Pad to 130x140 cell
        ox, oy = x + 31, y + 32

        # === Black → outline ===
        if r < 50 and g < 50 and b < 55:
            op[ox, oy] = (*OUTLINE, 255)
            continue

        # === CRYSTAL (x>=48 y<=28): cyan → ruby ===
        if x >= 48 and y <= 28 and g > 80 and b > 80 and r < 120:
            if g > 200 and b > 200:
                c = STAFF[0] if r < 50 else STAFF[1]
                op[ox, oy] = (*c, 255)
            elif g > 120:
                op[ox, oy] = (*STAFF[2], 255)
            else:
                op[ox, oy] = (*STAFF[3], 255)
            continue

        # === EARRINGS - left (x=11-13, y=28-30) + right (x=39-41, y=25-27) ===
        is_earring_l = (11 <= x <= 13 and 28 <= y <= 30)
        is_earring_r = (39 <= x <= 41 and 25 <= y <= 27)
        if (is_earring_l or is_earring_r) and g > 80 and b > 80 and r < 120:
            op[ox, oy] = (217, 29, 63, 255)  # red earring #d91d3f
            continue

        # === MAGIC (scattered cyan dots) → blue ===
        is_magic = ((10 <= x <= 14 and 28 <= y <= 32) or
                    (29 <= x <= 32 and 28 <= y <= 32) or
                    (x == 30 and y == 31))
        if is_magic and g > 80 and b > 80 and r < 120:
            op[ox, oy] = (*MAGIC, 255)
            continue

        # === HAIR (head x10-30 y3-26, not face box) ===
        in_hair = 10 <= x <= 30 and 3 <= y <= 26
        in_face = 18 <= x <= 27 and 19 <= y <= 28

        if in_hair and not in_face:
            lu = luma(r, g, b)
            if r > 220 and g > 170 and b > 110 and r - b > 80:
                op[ox, oy] = (*HAIR[0], 255)  # light
            elif 160 < r < 230 and 100 < g < 180 and 50 < b < 130:
                op[ox, oy] = (*HAIR[1], 255)  # mid
            elif 90 < r < 180 and 40 < g < 120 and 20 < b < 80:
                op[ox, oy] = (*HAIR[2], 255)  # dark
            elif r > 210 and g > 200 and b > 180:
                op[ox, oy] = (*HAIR[0], 255)  # cream → light
            elif lu > 230:
                op[ox, oy] = (*HAIR[0], 255)  # white → light
            else:
                op[ox, oy] = (*HAIR[1], 255)  # default hair
            continue

        # === FACE (face box - ALL → skin, remove forehead gem) ===
        if in_face:
            if r > 220 and g > 170 and b > 110 and r - b > 80:
                op[ox, oy] = (*HAIR[0], 255)  # gold near face → hair
            elif r > 200 and g > 160:
                op[ox, oy] = (*SKIN[0], 255)  # light skin
            elif r > 160 and g > 100:
                op[ox, oy] = (*SKIN[1], 255)  # mid skin
            else:
                op[ox, oy] = (*SKIN[2], 255)  # dark skin
            continue

        # === STAFF RING EDGE (cyan pixels near ring, x=46-47 y=16-20) ===
        if 46 <= x <= 47 and 16 <= y <= 20 and g > 80 and b > 80 and r < 120:
            op[ox, oy] = (*GOLD[1], 255)  # gold
            continue

        # === EYE REFLECTIONS (below eyes, x=18-19+24-25 y=29-30) ===
        is_eye_ref = (((18 <= x <= 19) or (24 <= x <= 25)) and 29 <= y <= 30)
        if is_eye_ref and g > 80 and b > 80 and r < 120:
            op[ox, oy] = (*EYE_D, 255)  # dark teal
            continue

        # === EYES (x=19-24, y=23-27) ===
        if 19 <= x <= 24 and 23 <= y <= 27:
            if g > 80 and b > 80 and r < 80:
                op[ox, oy] = (*EYE, 255)
            else:
                op[ox, oy] = (*EYE_D, 255)
            continue

        # === STAFF RING (x44-63 y3-33, not crystal) ===
        in_ring = 44 <= x <= 63 and 3 <= y <= 33 and not (x >= 48 and y <= 28)
        if in_ring:
            lu = luma(r, g, b)
            if r > 220 and g > 170 and b > 110:
                op[ox, oy] = (*GOLD[0], 255)
            elif 160 < r < 230 and 100 < g < 180:
                op[ox, oy] = (*GOLD[1], 255)
            elif lu > 240:
                op[ox, oy] = (255, 255, 255, 255)
            elif 90 < r < 180 and 40 < g < 120:
                op[ox, oy] = (*GOLD[2], 255)
            else:
                op[ox, oy] = (*GOLD[1], 255)
            continue

        # === STAFF SHAFT (narrow diagonal) → red ===
        if staff_at(x, y):
            lu = luma(r, g, b)
            if 90 < r < 180 and 40 < g < 120 and 20 < b < 80:
                op[ox, oy] = (*STAFF[2], 255)  # mid red
            elif 50 < r < 120 and 20 < g < 80:
                op[ox, oy] = (*STAFF[3], 255)  # dark red
            elif r > 200 and g > 150:
                op[ox, oy] = (*STAFF[1], 255)  # light red
            elif lu > 200:
                op[ox, oy] = (*STAFF[0], 255)  # bright
            else:
                op[ox, oy] = (*STAFF[2], 255)
            continue

        # === ROBE (body x8-35 y32-68) ===
        in_robe = 8 <= x <= 35 and 32 <= y <= 68
        if in_robe:
            lu = luma(r, g, b)
            # White/gray pixels
            if abs(r - g) < 30 and abs(g - b) < 30 and r > 100:
                if lu > 230:   op[ox, oy] = (*ROBE[0], 255)
                elif lu > 170: op[ox, oy] = (*ROBE[1], 255)
                elif lu > 110: op[ox, oy] = (*ROBE[2], 255)
                else:          op[ox, oy] = (*ROBE[3], 255)
            # Warm tan in robe → robe light
            elif r > 180 and g > 150 and b > 120:
                op[ox, oy] = (*ROBE[1], 255)
            # Dark → robe shadow
            elif lu < 80:
                op[ox, oy] = (*ROBE[3], 255)
            else:
                op[ox, oy] = (*ROBE[2], 255)
            continue

        # === BOOTS ===
        if 8 <= x <= 35 and 62 <= y <= 72:
            op[ox, oy] = (*OUTLINE, 255) if luma(r, g, b) < 80 else (*ROBE[3], 255)
            continue

        # === DEFAULT: keep original ===
        op[ox, oy] = (r, g, b, a)

out.save(OUT)
print(f"Saved {OUT} - {len(out.getcolors(maxcolors=100000))} colors")
