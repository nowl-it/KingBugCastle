#!/usr/bin/env python3
"""Craft Frieren Frame 0 from scratch as authentic 2D pixel art in Aseprite.

Designed specifically for Frieren's character anatomy & silhouette:
- Petite elf mage body proportions matching KGC hero scale (110x100 canvas, height ~76px)
- Stance: Idle standing pose facing 3/4 left, feet grounded at y=82
- Silver-white hair with twin low pigtails, emerald hair ties, front bangs
- Long elf ears with red dangling ruby earrings
- Calm turquoise/teal anime eyes
- White capelet with gold/black trim and ruby neck brooch
- Pleated white skirt with gold hemline & belt
- Slender Zoltraak staff with golden crescent head, floating ruby, and red ribbon
"""
import numpy as np
from PIL import Image

OUT_PNG = "/home/nowl/Code/kgc/server/assets/frieren/drafts/frame_00_frieren.png"
W, H = 110, 100

def c(hex_code):
    h = hex_code.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)

# High-quality KGC Pixel Palette
OUTLINE = c('#1e1b26')          # Main crisp dark outline
OUTLINE_SOFT = c('#363044')     # Internal dark outline
OUTLINE_HAIR = c('#5d5675')     # Hair edge tone
OUTLINE_STAFF = c('#380e14')    # Staff wood edge
OUTLINE_GOLD = c('#5e3e0c')     # Gold edge

# Hair (Silvery-white with lavender tint)
HAIR_0 = c('#ffffff')           # Specular highlight
HAIR_1 = c('#f4f1fa')           # Base white
HAIR_2 = c('#ddd6ec')           # Soft midtone
HAIR_3 = c('#b5acd0')           # Shadow
HAIR_4 = c('#7e749c')           # Deep shadow

# Skin (Porcelain pale skin)
SKIN_0 = c('#fff3ec')           # Highlight
SKIN_1 = c('#fae2d5')           # Base
SKIN_2 = c('#f0beae')           # Shadow
SKIN_3 = c('#d59080')           # Deep / crease
SKIN_BLUSH = c('#f7b8b0')       # Soft cheek blush

# Eyes (Turquoise / Teal)
EYE_WHITE = c('#f5fbfa')
EYE_HI = c('#4dfbe6')
EYE_BASE = c('#18c2b0')
EYE_MID = c('#118579')
EYE_DARK = c('#0c4943')
EYE_LASH = c('#141c22')

# Robe & Capelet (Ivory White with soft purple shading)
ROBE_0 = c('#ffffff')
ROBE_1 = c('#f0edf7')
ROBE_2 = c('#d5d0e4')
ROBE_3 = c('#a39bb9')
ROBE_4 = c('#6e6584')
STRIPE = c('#2c263b')

# Gold Trims & Brooch
GOLD_0 = c('#fff3aa')
GOLD_1 = c('#f5cc56')
GOLD_2 = c('#c89325')
GOLD_3 = c('#7d5410')

# Rubies (Staff gem, brooch, earrings)
GEM_0 = c('#ff7892')
GEM_1 = c('#e51f44')
GEM_2 = c('#8a0e24')
GEM_3 = c('#490513')

# Emerald Hair Ties
TIE_0 = c('#4ef0b5')
TIE_1 = c('#20a575')
TIE_2 = c('#105e42')

# Staff Wood
WOOD_0 = c('#a8424f')
WOOD_1 = c('#762430')
WOOD_2 = c('#450f16')

# Boots & Belt
BOOT_0 = c('#694636')
BOOT_1 = c('#492d21')
BOOT_2 = c('#2c1810')
LEGGINGS = c('#211b28')

# Canvas grid buffer
canvas = np.zeros((H, W, 4), dtype=np.uint8)

def p(x, y, color):
    if 0 <= x < W and 0 <= y < H:
        canvas[y, x] = color

def r(x1, y1, x2, y2, color):
    for y in range(y1, y2 + 1):
        for x in range(x1, x2 + 1):
            p(x, y, color)

def row(y, x1, x2, color):
    for x in range(x1, x2 + 1):
        p(x, y, color)

print("Drawing authentic Frieren pixel art from scratch...")

# =========================================================================
# 1. STAFF (Zoltraak Staff - held at right side, x ~ 65..72, y ~ 7..80)
# =========================================================================

# Staff Golden Crescent Head (Top at y: 7..23, x: 62..72)
# Top tip
p(66, 7, OUTLINE_GOLD)
p(67, 7, OUTLINE_GOLD)
row(8, 65, 68, GOLD_1)
p(65, 8, OUTLINE_GOLD); p(68, 8, OUTLINE_GOLD); p(66, 8, GOLD_0)

row(9, 64, 70, GOLD_1)
p(64, 9, OUTLINE_GOLD); p(70, 9, OUTLINE_GOLD); p(65, 9, GOLD_0)

# Golden crescent arch
for y in range(10, 18):
    p(63, y, OUTLINE_GOLD)
    p(64, y, GOLD_0 if y <= 13 else GOLD_1)
    p(65, y, GOLD_1 if y <= 13 else GOLD_2)
    
    p(69, y, GOLD_2 if y <= 13 else GOLD_1)
    p(70, y, GOLD_1 if y <= 13 else GOLD_0)
    p(71, y, OUTLINE_GOLD)

# Ruby core gem inside crescent (x: 66..68, y: 12..16)
p(67, 12, GEM_0)
row(13, 66, 68, GEM_1); p(67, 13, GEM_0)
row(14, 66, 68, GEM_1); p(68, 14, GEM_2)
row(15, 66, 68, GEM_2); p(66, 15, GEM_1)
p(67, 16, GEM_3)

# Bottom crescent base and mount
row(18, 64, 70, GOLD_2)
p(64, 18, OUTLINE_GOLD); p(70, 18, OUTLINE_GOLD); row(18, 66, 68, GOLD_1)
row(19, 65, 69, GOLD_1); p(65, 19, OUTLINE_GOLD); p(69, 19, OUTLINE_GOLD)
row(20, 66, 68, GOLD_0)
row(21, 66, 68, GOLD_2)
row(22, 66, 68, GOLD_3)

# Wooden Shaft (y: 23..78, x: 67..68)
for y in range(23, 79):
    p(66, y, OUTLINE_STAFF)
    p(67, y, WOOD_0 if y % 2 == 0 else WOOD_1)
    p(68, y, WOOD_1 if y % 2 == 0 else WOOD_2)
    p(69, y, OUTLINE_STAFF)

# Red Ribbon tied on staff (y: 56..65, x: 63..68)
p(67, 56, GEM_0); p(68, 56, GEM_1)
row(57, 65, 68, GEM_1); p(66, 57, GEM_0)
row(58, 64, 67, GEM_1); p(65, 58, GEM_0)
row(59, 64, 66, GEM_2); p(64, 59, GEM_1)
row(60, 63, 65, GEM_1); p(63, 60, GEM_0)
row(61, 63, 65, GEM_2)
row(62, 62, 64, GEM_1); p(62, 62, GEM_0)
row(63, 62, 64, GEM_2)
p(63, 64, GEM_3)

# Bottom brass tip of staff (y: 78..80)
row(78, 66, 68, GOLD_1)
row(79, 66, 68, GOLD_2)
p(67, 80, OUTLINE_GOLD)


# =========================================================================
# 2. LEGS & BOOTS (Grounded at y = 82)
# =========================================================================

# Dark tights under skirt
row(71, 46, 50, LEGGINGS)
row(72, 46, 50, LEGGINGS)
row(73, 46, 50, LEGGINGS)

row(71, 56, 60, LEGGINGS)
row(72, 56, 60, LEGGINGS)
row(73, 56, 60, LEGGINGS)

# Left Boot (Front-left foot, x: 44..51, y: 74..80)
row(74, 45, 51, BOOT_0); p(44, 74, OUTLINE); p(52, 74, OUTLINE) # Cuff
row(75, 44, 51, BOOT_0); p(43, 75, OUTLINE); p(52, 75, OUTLINE)
row(76, 44, 50, BOOT_1); p(44, 76, BOOT_0)
row(77, 44, 50, BOOT_1)
row(78, 43, 50, BOOT_2); p(44, 78, BOOT_1)
row(79, 43, 49, BOOT_2)
row(80, 44, 48, OUTLINE)

# Right Boot (Back-right planted foot, x: 55..62, y: 75..82)
row(74, 55, 61, BOOT_0); p(54, 74, OUTLINE); p(62, 74, OUTLINE) # Cuff
row(75, 55, 61, BOOT_0); p(54, 75, OUTLINE); p(62, 75, OUTLINE)
row(76, 55, 61, BOOT_1)
row(77, 56, 61, BOOT_1)
row(78, 56, 62, BOOT_2); p(57, 78, BOOT_1)
row(79, 56, 62, BOOT_2)
row(80, 57, 62, BOOT_2)
row(81, 57, 61, OUTLINE)
row(82, 58, 60, OUTLINE) # Planted at ground y=82


# =========================================================================
# 3. SKIRT & ROBE (Pleated white A-line skirt with gold hem, y: 58..75)
# =========================================================================

for y in range(58, 76):
    left_x = int(48 - (y - 58) * 0.75)
    right_x = int(58 + (y - 58) * 0.65)
    
    # Fill white skirt fabric
    row(y, left_x, right_x, ROBE_1)
    p(left_x, y, OUTLINE)
    p(right_x, y, OUTLINE)
    
    # Pleat folds and volume shadows
    p(left_x + 2, y, ROBE_0)
    p(left_x + 4, y, ROBE_2)
    p(left_x + 5, y, ROBE_3)
    p(52, y, ROBE_0)
    p(54, y, ROBE_2)
    p(56, y, ROBE_3)
    p(right_x - 3, y, ROBE_2)
    p(right_x - 1, y, ROBE_0)

# Gold embroidered hemline on bottom skirt (y: 73..75)
for y in (73, 74):
    left_x = int(48 - (y - 58) * 0.75) + 1
    right_x = int(58 + (y - 58) * 0.65) - 1
    for x in range(left_x, right_x + 1):
        if (x + y) % 2 == 0:
            p(x, y, GOLD_0)
        else:
            p(x, y, GOLD_1)

row(75, 36, 69, OUTLINE)


# =========================================================================
# 4. TUNIC & TORSO (y: 47..58, x: 46..60)
# =========================================================================

for y in range(47, 58):
    row(y, 47, 59, ROBE_1)
    p(46, y, OUTLINE)
    p(60, y, OUTLINE)
    
    # Black pinstripes on tunic
    p(49, y, STRIPE)
    p(53, y, STRIPE)
    p(57, y, STRIPE)

# Black belt with gold buckle (y: 56..57)
row(56, 47, 59, STRIPE)
row(57, 47, 59, STRIPE)
# Gold buckle at center (x: 51..54, y: 55..57)
row(55, 51, 54, GOLD_0)
row(56, 51, 54, GOLD_1); p(52, 56, STRIPE); p(53, 56, STRIPE)
row(57, 51, 54, GOLD_2)


# =========================================================================
# 5. CAPELET (SHOULDER MANTLE, y: 40..52, x: 40..66)
# =========================================================================

# Capelet shape
for y in range(40, 51):
    left_x = int(49 - (y - 40) * 0.8)
    right_x = int(57 + (y - 40) * 0.8)
    row(y, left_x, right_x, ROBE_1)
    p(left_x, y, OUTLINE)
    p(right_x, y, OUTLINE)
    # Shading on sides
    p(left_x + 1, y, ROBE_0)
    p(right_x - 1, y, ROBE_2)

# Black accent stripe near bottom edge of capelet (y: 48..49)
for y in (48, 49):
    left_x = int(49 - (y - 40) * 0.8) + 1
    right_x = int(57 + (y - 40) * 0.8) - 1
    row(y, left_x, right_x, STRIPE)

# Gold embroidered trim at capelet hem (y: 50..51)
row(50, 41, 65, GOLD_1); p(53, 50, GOLD_0); p(54, 50, GOLD_0)
row(51, 41, 65, GOLD_2)
row(52, 42, 64, OUTLINE)

# Center Neck Brooch (Gold clasp with Ruby Gem, x: 51..55, y: 41..44)
row(41, 52, 54, GOLD_0)
row(42, 51, 55, GOLD_1); p(53, 42, GEM_0)
row(43, 51, 55, GOLD_1); p(53, 43, GEM_1)
row(44, 52, 54, GOLD_2); p(53, 44, GEM_2)


# =========================================================================
# 6. ARMS & HANDS
# Right arm resting at side (x: 41..46, y: 47..56)
# Left arm holding staff (x: 60..67, y: 47..56)
# =========================================================================

# Right sleeve & hand
for y in range(47, 53):
    row(y, 42, 46, ROBE_1); p(41, y, OUTLINE)
# Gold sleeve cuff
row(53, 42, 46, GOLD_1)
# Hand
row(54, 43, 46, SKIN_1); p(42, 54, OUTLINE)
row(55, 43, 45, SKIN_2)
p(44, 56, OUTLINE)

# Left sleeve & hand gripping staff
for y in range(47, 52):
    row(y, 60, 64, ROBE_1); p(65, y, OUTLINE)
# Gold sleeve cuff
row(52, 60, 65, GOLD_1)
# Hand gripping staff at x=66..68
row(53, 64, 68, SKIN_0)
row(54, 64, 68, SKIN_1); p(69, 54, OUTLINE)
row(55, 65, 68, SKIN_2)


# =========================================================================
# 7. HEAD, FACE, EARS & EARRINGS (Head center ~ (53, 29))
# =========================================================================

# Face Base Skin (y: 25..39, x: 46..60)
for y in range(25, 40):
    row(y, 47, 59, SKIN_1)
    p(46, y, OUTLINE)
    p(60, y, OUTLINE)

# Chin taper (y: 38..40)
row(38, 48, 58, SKIN_1)
row(39, 49, 57, SKIN_2)
row(40, 51, 55, SKIN_3); p(53, 40, OUTLINE)

# Left Long Elf Ear (Pointing outwards-left, x: 38..46, y: 29..33)
p(38, 30, OUTLINE)
row(30, 39, 46, SKIN_0); p(38, 30, OUTLINE)
row(31, 38, 46, SKIN_1); p(37, 31, OUTLINE)
row(32, 39, 46, SKIN_2); p(38, 32, OUTLINE)
p(40, 33, OUTLINE); p(41, 33, OUTLINE)

# Left Ruby Teardrop Earring (y: 34..39, x: 42)
p(42, 34, GOLD_1) # Gold stud
p(42, 35, GEM_0)  # Top ruby
p(42, 36, GEM_1)  # Core ruby
p(42, 37, GEM_1)
p(42, 38, GEM_2)  # Shadow
p(42, 39, GEM_3)  # Tip

# Right Long Elf Ear (Pointing outwards-right, x: 60..67, y: 29..33)
p(67, 30, OUTLINE)
row(30, 60, 66, SKIN_0)
row(31, 60, 67, SKIN_1); p(68, 31, OUTLINE)
row(32, 60, 66, SKIN_2); p(67, 32, OUTLINE)
p(64, 33, OUTLINE); p(65, 33, OUTLINE)

# Right Ruby Teardrop Earring (y: 34..39, x: 63)
p(63, 34, GOLD_1)
p(63, 35, GEM_0)
p(63, 36, GEM_1)
p(63, 37, GEM_1)
p(63, 38, GEM_2)
p(63, 39, GEM_3)

# Cheeks blush
p(48, 35, SKIN_BLUSH); p(49, 35, SKIN_BLUSH)
p(57, 35, SKIN_BLUSH); p(58, 35, SKIN_BLUSH)

# Nose & Calm Mouth
p(53, 36, SKIN_3)
row(38, 52, 54, SKIN_3); p(53, 38, c('#c06060'))


# =========================================================================
# 8. EYES (Turquoise/Teal with catchlights & dark anime eyelashes)
# Left eye: x ~ 48..51, y ~ 31..34
# Right eye: x ~ 55..58, y ~ 31..34
# =========================================================================

# Left Eye
row(31, 48, 51, EYE_LASH) # Upper eyelash
p(47, 32, EYE_LASH)
p(48, 32, EYE_WHITE); p(49, 32, EYE_HI); p(50, 32, EYE_BASE); p(51, 32, EYE_MID)
p(48, 33, EYE_WHITE); p(49, 33, EYE_BASE); p(50, 33, EYE_DARK); p(51, 33, EYE_MID)
row(34, 48, 51, EYE_LASH) # Lower eyelash

# Right Eye
row(31, 55, 58, EYE_LASH) # Upper eyelash
p(59, 32, EYE_LASH)
p(55, 32, EYE_WHITE); p(56, 32, EYE_HI); p(57, 32, EYE_BASE); p(58, 32, EYE_MID)
p(55, 33, EYE_WHITE); p(56, 33, EYE_BASE); p(57, 33, EYE_DARK); p(58, 33, EYE_MID)
row(34, 55, 58, EYE_LASH) # Lower eyelash

# Eyebrows (Lavender silver)
row(29, 48, 51, HAIR_3)
row(29, 55, 58, HAIR_3)


# =========================================================================
# 9. HAIR (Crown, Bangs & Twin Low Pigtails)
# =========================================================================

# Hair Crown (Dome top, y: 19..28, x: 44..62)
row(19, 49, 57, OUTLINE_HAIR)
row(20, 46, 60, HAIR_0)
row(21, 45, 61, HAIR_0)
row(22, 44, 62, HAIR_1)
row(23, 44, 62, HAIR_1)
row(24, 44, 62, HAIR_1)
p(44, 21, OUTLINE_HAIR); p(62, 21, OUTLINE_HAIR)
p(43, 23, OUTLINE_HAIR); p(63, 23, OUTLINE_HAIR)

# Front Bangs parting over forehead (y: 25..31)
# Center Parting (Frieren's iconic forehead part)
row(25, 45, 49, HAIR_0); row(25, 52, 54, HAIR_0); row(25, 57, 61, HAIR_1)
row(26, 45, 49, HAIR_1); row(26, 52, 54, HAIR_1); row(26, 57, 61, HAIR_1)
row(27, 45, 48, HAIR_1); p(53, 27, HAIR_1); row(27, 58, 61, HAIR_2)
row(28, 45, 47, HAIR_2); p(53, 28, HAIR_2); row(28, 59, 61, HAIR_2)

# Side bangs framing cheeks
for y in range(29, 38):
    p(44, y, OUTLINE_HAIR); p(45, y, HAIR_1); p(46, y, HAIR_2)
    p(60, y, HAIR_2); p(61, y, HAIR_1); p(62, y, OUTLINE_HAIR)

# Emerald Hair Ties (Left: x: 40..42, y: 31..33; Right: x: 64..66, y: 31..33)
row(31, 40, 42, TIE_0)
row(32, 39, 42, TIE_1); p(39, 32, OUTLINE)
row(33, 40, 42, TIE_2)

row(31, 64, 66, TIE_0)
row(32, 64, 67, TIE_1); p(67, 32, OUTLINE)
row(33, 64, 66, TIE_2)

# Twin Low Pigtails
# Left Pigtail (y: 34..66, x: 33..42)
for y in range(34, 67):
    cur_x = int(38 - np.sin((y - 34) / 32.0 * 3.14) * 5)
    row(y, cur_x - 2, cur_x + 2, HAIR_1)
    p(cur_x - 3, y, OUTLINE_HAIR)
    p(cur_x - 2, y, HAIR_0)
    p(cur_x + 1, y, HAIR_2)
    p(cur_x + 2, y, HAIR_3)
    p(cur_x + 3, y, OUTLINE_HAIR)

# Right Pigtail (y: 34..65, x: 64..72)
for y in range(34, 66):
    cur_x = int(66 + np.sin((y - 34) / 31.0 * 3.14) * 4)
    row(y, cur_x - 2, cur_x + 2, HAIR_1)
    p(cur_x - 3, y, OUTLINE_HAIR)
    p(cur_x, y, HAIR_0)
    p(cur_x + 1, y, HAIR_2)
    p(cur_x + 2, y, HAIR_3)
    p(cur_x + 3, y, OUTLINE_HAIR)


# Save image
out_img = Image.fromarray(canvas, "RGBA")
out_img.save(OUT_PNG)
print(f"Saved authentic handcrafted Frieren Frame 0 to: {OUT_PNG}")
print(f"Bbox: {out_img.getbbox()}")
