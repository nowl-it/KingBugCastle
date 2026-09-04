#!/usr/bin/env python3
"""High-fidelity pixel art generator for Frieren Frame 0 (D.Neria base).

Uses the organic pixel geometry and shading gradients of the original KGC sprite
while faithfully implementing Frieren's character design from the approved illustration:
- Silver-white hair with twin low pigtails and emerald ties
- Long elf ears with dangling ruby drop earrings
- Calm turquoise/teal eyes with highlights
- White/cream capelet with black stripe and gold embroidery
- Gold neck brooch with ruby gem
- White pleated robe with gold hem
- Dark mahogany staff with golden crescent head, floating ruby, and red ribbon
"""
from PIL import Image
import numpy as np

SRC = "/home/nowl/Code/kgc/server/assets/frieren/dneria/frames/frame_00.png"
OUT_PNG = "/home/nowl/Code/kgc/server/assets/frieren/drafts/frame_00_frieren.png"
OUT_PREV = "/home/nowl/Code/kgc/server/assets/frieren/drafts/frame_00_preview.png"

src_img = Image.open(SRC).convert("RGBA")
pix = src_img.load()
w, h = src_img.size

out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
op = out.load()

# Color palettes (R, G, B, A)
def c(h):
    h = h.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)

OUTLINE = c('#201a2b')
OUTLINE_HAIR = c('#635c7a')
OUTLINE_GOLD = c('#5a3d0d')
OUTLINE_STAFF = c('#330d12')

HAIR = [c('#ffffff'), c('#f2eff8'), c('#ddd6eb'), c('#b8b0cf'), c('#877e9e')]
SKIN = [c('#fff3ec'), c('#fbe4d8'), c('#f2c2b2'), c('#d89484')]
ROBE = [c('#ffffff'), c('#f0ecf6'), c('#d5cfdf'), c('#a79fb8'), c('#766f87')]
GOLD = [c('#fff0a4'), c('#f5ca56'), c('#c79224'), c('#7a5210')]
STAFF = [c('#b84d59'), c('#802934'), c('#4d121a'), c('#2b070c')]
GEM = [c('#ff788f'), c('#e21f42'), c('#8a0f25'), c('#45040f')]
EYE_TEAL = [c('#50f5e2'), c('#1fc2b0'), c('#117d74'), c('#094440')]
HAIR_TIE = [c('#4ee6b2'), c('#22a074'), c('#125c40')]
BOOTS = [c('#6e4838'), c('#4c3024'), c('#2d1a12'), c('#1a0d08')]
STRIPE = c('#2a2336')

def luma(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b

# ----------------------------------------------------
# Step 1: Base Remapping of organic pixels from D.Neria
# ----------------------------------------------------
for y in range(h):
    for x in range(w):
        r, g, b, a = pix[x, y]
        if a == 0:
            continue
        
        lum = luma(r, g, b)
        
        # 1. Dark Outline
        if r < 45 and g < 45 and b < 45:
            if y <= 21 or (x >= 65 and y >= 22):
                op[x, y] = OUTLINE_STAFF if (x >= 63 and y <= 22) else OUTLINE
            elif y <= 35:
                op[x, y] = OUTLINE_HAIR if (x <= 48 or x >= 64) else OUTLINE
            else:
                op[x, y] = OUTLINE
            continue

        # 2. Staff Head Crescent & Gem (y <= 22, x >= 60)
        if y <= 22 and x >= 60:
            if 64 <= x <= 68 and 10 <= y <= 16:
                # Central ruby gem
                if lum > 200: op[x, y] = GEM[0]
                elif lum > 140: op[x, y] = GEM[1]
                elif lum > 80: op[x, y] = GEM[2]
                else: op[x, y] = GEM[3]
            else:
                # Golden crescent ring
                if lum > 220: op[x, y] = GOLD[0]
                elif lum > 160: op[x, y] = GOLD[1]
                elif lum > 100: op[x, y] = GOLD[2]
                else: op[x, y] = GOLD[3]
            continue

        # 3. Staff Shaft (x: 65..70, y: 22..78)
        if x >= 66 and y >= 23 and ((y <= 38) or (y >= 58 and x >= 67) or (y >= 75 and x >= 65)):
            if lum > 180: op[x, y] = STAFF[0]
            elif lum > 120: op[x, y] = STAFF[1]
            elif lum > 60: op[x, y] = STAFF[2]
            else: op[x, y] = STAFF[3]
            continue

        # 4. Hair & Head (y: 22..38, x: 44..68)
        if 22 <= y <= 38 and 44 <= x <= 68:
            # Check if in face region
            in_face = (49 <= x <= 62 and 33 <= y <= 38)
            if not in_face:
                # Silvery-white hair
                if lum > 230: op[x, y] = HAIR[0]
                elif lum > 190: op[x, y] = HAIR[1]
                elif lum > 140: op[x, y] = HAIR[2]
                elif lum > 90: op[x, y] = HAIR[3]
                else: op[x, y] = HAIR[4]
                continue
            else:
                # Face skin
                if lum > 220: op[x, y] = SKIN[0]
                elif lum > 170: op[x, y] = SKIN[1]
                elif lum > 110: op[x, y] = SKIN[2]
                else: op[x, y] = SKIN[3]
                continue

        # 5. Left Pigtail (y: 38..66, x: 35..45)
        if 38 <= y <= 66 and 35 <= x <= 45 and lum > 90:
            if lum > 220: op[x, y] = HAIR[0]
            elif lum > 170: op[x, y] = HAIR[1]
            elif lum > 120: op[x, y] = HAIR[2]
            else: op[x, y] = HAIR[3]
            continue

        # 6. Right Pigtail (y: 38..62, x: 64..72)
        if 38 <= y <= 62 and 64 <= x <= 72 and lum > 90:
            if lum > 220: op[x, y] = HAIR[1]
            elif lum > 160: op[x, y] = HAIR[2]
            elif lum > 100: op[x, y] = HAIR[3]
            else: op[x, y] = HAIR[4]
            continue

        # 7. Capelet & Upper Robe (y: 39..54)
        if 39 <= y <= 54:
            # Collar brooch area (x: 53..57, y: 42..46)
            if 53 <= x <= 57 and 42 <= y <= 46:
                if (x == 55 and y in (43, 44)):
                    op[x, y] = GEM[0] if lum > 160 else GEM[1]
                else:
                    op[x, y] = GOLD[0] if lum > 180 else GOLD[1]
                continue
            
            # Capelet bottom dark band (y: 49..50)
            if y in (49, 50) and 38 <= x <= 71 and lum < 180:
                op[x, y] = STRIPE
                continue
            
            # Capelet gold trim (y: 51..52)
            if y in (51, 52) and 39 <= x <= 70:
                op[x, y] = GOLD[0] if lum > 170 else (GOLD[1] if lum > 110 else GOLD[2])
                continue

            # White capelet fabric
            if lum > 220: op[x, y] = ROBE[0]
            elif lum > 170: op[x, y] = ROBE[1]
            elif lum > 120: op[x, y] = ROBE[2]
            elif lum > 70: op[x, y] = ROBE[3]
            else: op[x, y] = ROBE[4]
            continue

        # 8. Torso & Skirt (y: 55..75)
        if 55 <= y <= 75:
            # Waist gold belt (y: 57..58)
            if y in (57, 58) and 46 <= x <= 64:
                op[x, y] = GOLD[0] if lum > 180 else GOLD[1]
                continue
            
            # Skirt bottom gold trim (y: 72..74)
            if y >= 72 and (x <= 42 or (48 <= x <= 68)):
                if lum > 130:
                    op[x, y] = GOLD[0] if lum > 200 else GOLD[1]
                    continue

            # White skirt fabric with vertical stripe hints
            if (x in (49, 53, 57, 61)) and y <= 62 and lum < 180:
                op[x, y] = STRIPE
                continue

            if lum > 220: op[x, y] = ROBE[0]
            elif lum > 170: op[x, y] = ROBE[1]
            elif lum > 120: op[x, y] = ROBE[2]
            elif lum > 70: op[x, y] = ROBE[3]
            else: op[x, y] = ROBE[4]
            continue

        # 9. Boots (y >= 74)
        if y >= 74:
            if lum > 180: op[x, y] = BOOTS[0]
            elif lum > 120: op[x, y] = BOOTS[1]
            elif lum > 60: op[x, y] = BOOTS[2]
            else: op[x, y] = BOOTS[3]
            continue

        # Default fallback
        op[x, y] = (r, g, b, a)

# ----------------------------------------------------
# Step 2: Handcrafted Identity Features for Frieren
# ----------------------------------------------------

# A. Long Elf Ears & Ruby Drop Earrings
# Left Elf Ear (x: 41..48, y: 34..37)
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
op[44, 38] = GOLD[1] # Earring stud
op[44, 39] = GEM[0]  # Ruby highlight
op[44, 40] = GEM[1]  # Ruby core
op[44, 41] = GEM[2]  # Ruby shadow
op[44, 42] = GEM[3]  # Ruby bottom tip

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
# Left eye (x: 51..53, y: 35..37)
op[50, 34] = OUTLINE
op[51, 34] = c('#102224')
op[52, 34] = c('#102224')
op[53, 34] = c('#102224')

op[50, 35] = c('#ffffff') # eye white
op[51, 35] = EYE_TEAL[0]  # catchlight / bright
op[52, 35] = EYE_TEAL[1]  # iris
op[53, 35] = EYE_TEAL[2]  # shadow

op[50, 36] = c('#ffffff')
op[51, 36] = EYE_TEAL[1]
op[52, 36] = EYE_TEAL[2]
op[53, 36] = EYE_TEAL[3]

# Right eye (x: 57..59, y: 35..37)
op[56, 34] = c('#102224')
op[57, 34] = c('#102224')
op[58, 34] = c('#102224')
op[59, 34] = OUTLINE

op[56, 35] = c('#ffffff')
op[57, 35] = EYE_TEAL[0]
op[58, 35] = EYE_TEAL[1]
op[59, 35] = EYE_TEAL[2]

op[56, 36] = c('#ffffff')
op[57, 36] = EYE_TEAL[1]
op[58, 36] = EYE_TEAL[2]
op[59, 36] = EYE_TEAL[3]

# Nose & Calm Mouth
op[55, 38] = SKIN[2]
op[54, 40] = SKIN[3]
op[55, 40] = SKIN[3]

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

# Save PNG
out.save(OUT_PNG)
print(f"Saved refined Frame 0: {OUT_PNG}")
print(f"Bbox: {out.getbbox()}")

# Generate 4x Preview Comparison
scale = 4
fw, fh = w * scale, h * scale
dneria_4x = src_img.resize((fw, fh), Image.Resampling.NEAREST)
frieren_4x = out.resize((fw, fh), Image.Resampling.NEAREST)
overlay_4x = Image.blend(src_img, out, 0.5).resize((fw, fh), Image.Resampling.NEAREST)

comp_w = fw * 3 + 60
comp_h = fh + 60
comp_board = Image.new("RGBA", (comp_w, comp_h), (26, 26, 32, 255))

comp_board.paste(dneria_4x, (15, 30), dneria_4x)
comp_board.paste(frieren_4x, (fw + 30, 30), frieren_4x)
comp_board.paste(overlay_4x, (fw * 2 + 45, 30), overlay_4x)

comp_board.save(OUT_PREV)
comp_board.save("/home/nowl/.gemini/antigravity-ide/brain/cecd79d3-fe25-4b8e-b636-15cf7ade4faf/frame_00_review.png")
print("Updated comparison review board in artifacts.")
