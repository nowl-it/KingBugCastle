#!/usr/bin/env python3
"""Repaint D.Neria Frame 0 (110x100) into Frieren, pixel-by-pixel.

Preserves 100% of the original KGC 2D pixel-art geometry, outline thickness,
pixel clusters, and stance while transforming every region into Frieren based
on the approved Illustration.
"""
from PIL import Image

SRC = "/home/nowl/Code/kgc/server/assets/frieren/dneria/frames/frame_00.png"
OUT_PNG = "/home/nowl/Code/kgc/server/assets/frieren/drafts/frame_00_frieren.png"

src = Image.open(SRC).convert("RGBA")
pix = src.load()
w, h = src.size

out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
op = out.load()

# Frieren Palette (RGBA)
def c(hex_code):
    h = hex_code.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)

OUTLINE = c('#201a29')        # Standard KGC dark outline
OUTLINE_SOFT = c('#3b334a')   # Soft inner outline
OUTLINE_HAIR = c('#665e7d')   # Hair outline
OUTLINE_GOLD = c('#593b0b')   # Gold outline
OUTLINE_STAFF = c('#360b10')  # Staff outline

HAIR = [c('#ffffff'), c('#f3eff8'), c('#ddd6eb'), c('#b7afce'), c('#857b9c')]
SKIN = [c('#fff3ec'), c('#fbe4d8'), c('#f2c2b2'), c('#d89484')]
ROBE = [c('#ffffff'), c('#f0edf6'), c('#d5d0e2'), c('#a79fb8'), c('#766f87')]
GOLD = [c('#fff0a4'), c('#f5ca56'), c('#c79224'), c('#7a5210')]
STAFF = [c('#b84d59'), c('#802934'), c('#4d121a'), c('#2b070c')]
GEM = [c('#ff788f'), c('#e21f42'), c('#8a0f25'), c('#45040f')]
EYE_TEAL = [c('#50f5e2'), c('#1fc2b0'), c('#117d74'), c('#094440')]
HAIR_TIE = [c('#4ee6b2'), c('#22a074'), c('#125c40')]
BOOTS = [c('#6e4838'), c('#4c3024'), c('#2d1a12'), c('#1a0d08')]
STRIPE = c('#2b2438')

def luma(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b

# Pass 1: Pixel-by-pixel region classification & re-shading
for y in range(h):
    for x in range(w):
        r, g, b, a = pix[x, y]
        if a == 0:
            continue

        lum = luma(r, g, b)

        # 1. Outline pixels
        if r == 0 and g == 0 and b == 0:
            if y <= 21:
                op[x, y] = OUTLINE_STAFF if x >= 62 else OUTLINE
            elif 22 <= y <= 35:
                op[x, y] = OUTLINE_HAIR if (x <= 48 or x >= 64) else OUTLINE
            elif y >= 74 and (x <= 42 or x >= 57):
                op[x, y] = BOOTS[3]
            else:
                op[x, y] = OUTLINE
            continue

        # 2. Staff Head Crescent & Gem (y <= 22, x >= 60)
        if y <= 22 and x >= 60:
            if 64 <= x <= 68 and 10 <= y <= 16:
                # Central Ruby Gem
                if lum > 190: op[x, y] = GEM[0]
                elif lum > 130: op[x, y] = GEM[1]
                elif lum > 70: op[x, y] = GEM[2]
                else: op[x, y] = GEM[3]
            else:
                # Golden Crescent Ring
                if lum > 210: op[x, y] = GOLD[0]
                elif lum > 150: op[x, y] = GOLD[1]
                elif lum > 90: op[x, y] = GOLD[2]
                else: op[x, y] = GOLD[3]
            continue

        # 3. Head & Hair Crown (y: 22..35, x: 44..68)
        if 22 <= y <= 35 and 44 <= x <= 68:
            # Silver-white hair
            if lum > 230: op[x, y] = HAIR[0]
            elif lum > 190: op[x, y] = HAIR[1]
            elif lum > 140: op[x, y] = HAIR[2]
            elif lum > 90: op[x, y] = HAIR[3]
            else: op[x, y] = HAIR[4]
            continue

        # 4. Face Region (y: 36..41, x: 49..62)
        if 36 <= y <= 41 and 49 <= x <= 62:
            if lum > 220: op[x, y] = SKIN[0]
            elif lum > 170: op[x, y] = SKIN[1]
            elif lum > 110: op[x, y] = SKIN[2]
            else: op[x, y] = SKIN[3]
            continue

        # 5. Left Hair / Pigtail (x <= 45, y: 36..65)
        if x <= 45 and 36 <= y <= 65:
            if lum > 210: op[x, y] = HAIR[0]
            elif lum > 160: op[x, y] = HAIR[1]
            elif lum > 110: op[x, y] = HAIR[2]
            elif lum > 60: op[x, y] = HAIR[3]
            else: op[x, y] = HAIR[4]
            continue

        # 6. Right Hair / Pigtail (x >= 64, y: 36..62)
        if x >= 64 and 36 <= y <= 62 and not (66 <= x <= 69 and y >= 58):
            if lum > 210: op[x, y] = HAIR[1]
            elif lum > 160: op[x, y] = HAIR[2]
            elif lum > 110: op[x, y] = HAIR[3]
            else: op[x, y] = HAIR[4]
            continue

        # 7. Staff Shaft (x: 66..69, y: 23..78)
        if 66 <= x <= 69 and y >= 23 and (y <= 38 or y >= 58):
            if lum > 180: op[x, y] = STAFF[0]
            elif lum > 120: op[x, y] = STAFF[1]
            elif lum > 60: op[x, y] = STAFF[2]
            else: op[x, y] = STAFF[3]
            continue

        # 8. Capelet (y: 42..54, x: 38..71)
        if 42 <= y <= 54:
            # Collar Brooch (x: 53..57, y: 43..46)
            if 53 <= x <= 57 and 43 <= y <= 46:
                if x == 55 and y in (44, 45):
                    op[x, y] = GEM[0] if lum > 160 else GEM[1]
                else:
                    op[x, y] = GOLD[0] if lum > 180 else GOLD[1]
                continue

            # Capelet dark stripe (y: 49..50)
            if y in (49, 50) and 40 <= x <= 70 and lum < 150:
                op[x, y] = STRIPE
                continue

            # Capelet gold border (y: 51..52)
            if y in (51, 52) and 39 <= x <= 70:
                op[x, y] = GOLD[0] if lum > 160 else (GOLD[1] if lum > 100 else GOLD[2])
                continue

            # Capelet white fabric
            if lum > 220: op[x, y] = ROBE[0]
            elif lum > 170: op[x, y] = ROBE[1]
            elif lum > 120: op[x, y] = ROBE[2]
            elif lum > 70: op[x, y] = ROBE[3]
            else: op[x, y] = ROBE[4]
            continue

        # 9. Torso & Waist (y: 55..62)
        if 55 <= y <= 62:
            # Waist gold belt (y: 57..58)
            if y in (57, 58) and 46 <= x <= 64:
                op[x, y] = GOLD[0] if lum > 180 else GOLD[1]
                continue

            # Tunic pinstripes
            if (x in (49, 53, 57, 61)) and lum < 160:
                op[x, y] = STRIPE
                continue

            if lum > 220: op[x, y] = ROBE[0]
            elif lum > 170: op[x, y] = ROBE[1]
            elif lum > 120: op[x, y] = ROBE[2]
            elif lum > 70: op[x, y] = ROBE[3]
            else: op[x, y] = ROBE[4]
            continue

        # 10. Skirt / Robe Lower (y: 63..75)
        if 63 <= y <= 75:
            # Skirt bottom gold embroidery (y: 72..75)
            if y >= 72 and (x <= 42 or (48 <= x <= 68)):
                if lum > 110:
                    op[x, y] = GOLD[0] if lum > 180 else GOLD[1]
                    continue

            # Skirt white fabric
            if lum > 220: op[x, y] = ROBE[0]
            elif lum > 170: op[x, y] = ROBE[1]
            elif lum > 120: op[x, y] = ROBE[2]
            elif lum > 70: op[x, y] = ROBE[3]
            else: op[x, y] = ROBE[4]
            continue

        # 11. Boots (y >= 74)
        if y >= 74:
            if lum > 170: op[x, y] = BOOTS[0]
            elif lum > 110: op[x, y] = BOOTS[1]
            elif lum > 50: op[x, y] = BOOTS[2]
            else: op[x, y] = BOOTS[3]
            continue

        # Default fallback: keep original
        op[x, y] = (r, g, b, a)


# ----------------------------------------------------
# Pass 2: Precise Handcrafted Frieren Identity Pixels
# ----------------------------------------------------

# A. Long Elf Ears & Ruby Drop Earrings
# Left Elf Ear (pointing outwards to the left at x: 41..48, y: 35..37)
op[41, 35] = OUTLINE
op[42, 35] = SKIN[0]
op[43, 35] = SKIN[0]
op[44, 35] = SKIN[0]
op[41, 36] = SKIN[0]
op[42, 36] = SKIN[1]
op[43, 36] = SKIN[1]
op[44, 36] = SKIN[2]
op[41, 37] = OUTLINE
op[42, 37] = OUTLINE

# Left Ruby Earring (x: 44, y: 38..42)
op[44, 38] = GOLD[1] # gold stud
op[44, 39] = GEM[0]  # bright ruby
op[44, 40] = GEM[1]  # core ruby
op[44, 41] = GEM[2]  # shadow ruby
op[44, 42] = GEM[3]  # tip

# Right Ruby Earring (x: 67, y: 38..42)
op[67, 38] = GOLD[1]
op[67, 39] = GEM[0]
op[67, 40] = GEM[1]
op[67, 41] = GEM[2]
op[67, 42] = GEM[3]

# B. Emerald Hair Ties (Left: x: 44..45, y: 37..38; Right: x: 65..66, y: 37..38)
op[44, 37] = HAIR_TIE[0]
op[45, 37] = HAIR_TIE[1]
op[44, 38] = HAIR_TIE[1]
op[45, 38] = HAIR_TIE[2]

op[65, 37] = HAIR_TIE[0]
op[66, 37] = HAIR_TIE[1]
op[65, 38] = HAIR_TIE[1]
op[66, 38] = HAIR_TIE[2]

# C. Eyes (Turquoise/Teal with catchlights & dark eyelashes)
# Left eye (x: 51..53, y: 38..40)
op[50, 37] = OUTLINE
op[51, 37] = c('#102224')
op[52, 37] = c('#102224')
op[53, 37] = c('#102224')

op[50, 38] = c('#ffffff') # eye white
op[51, 38] = EYE_TEAL[0]  # catchlight
op[52, 38] = EYE_TEAL[1]  # iris
op[53, 38] = EYE_TEAL[2]  # shadow

op[50, 39] = c('#ffffff')
op[51, 39] = EYE_TEAL[1]
op[52, 39] = EYE_TEAL[2]
op[53, 39] = EYE_TEAL[3]

# Right eye (x: 57..59, y: 38..40)
op[56, 37] = c('#102224')
op[57, 37] = c('#102224')
op[58, 37] = c('#102224')
op[59, 37] = OUTLINE

op[56, 38] = c('#ffffff')
op[57, 38] = EYE_TEAL[0]
op[58, 38] = EYE_TEAL[1]
op[59, 38] = EYE_TEAL[2]

op[56, 39] = c('#ffffff')
op[57, 39] = EYE_TEAL[1]
op[58, 39] = EYE_TEAL[2]
op[59, 39] = EYE_TEAL[3]

# D. Red Ribbon tied near staff grip (x: 64..67, y: 58..64)
op[65, 58] = GEM[1]
op[66, 58] = GEM[0]
op[64, 59] = GEM[0]
op[65, 59] = GEM[1]
op[66, 59] = GEM[2]
op[64, 60] = GEM[1]
op[65, 60] = GEM[2]
op[63, 61] = GEM[0]
op[64, 61] = GEM[1]
op[63, 62] = GEM[1]
op[64, 62] = GEM[2]
op[63, 63] = GEM[2]
op[63, 64] = GEM[3]

out.save(OUT_PNG)
print(f"Saved authentic pixel-recolored Frame 0: {OUT_PNG}")
print(f"Bbox: {out.getbbox()}")
