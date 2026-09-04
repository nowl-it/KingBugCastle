#!/usr/bin/env python3
"""Create Frame 0 of Frieren skin for D.Neria (10780) using pixel art logic & aseprite-mcp.

Matches D.Neria frame 0 silhouette, dimensions (110x100), facing angle, and ground contact.
Incorporates all character design details from the approved Frieren Illustration.
"""
import os
import sys
import numpy as np
from PIL import Image

OUT_PNG = "/home/nowl/Code/kgc/server/assets/frieren/drafts/frame_00_frieren.png"
OUT_COMPARE = "/home/nowl/Code/kgc/server/assets/frieren/drafts/frame_00_comparison.png"
DNERIA_F0 = "/home/nowl/Code/kgc/server/assets/frieren/dneria/frames/frame_00.png"
ASEPRITE_WS = "/home/nowl/Code/aseprite-mcp/workspace"

W, H = 110, 100

# Color definitions (Hex to RGBA)
def c(h):
    h = h.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)

OUTLINE = c('#221d2c')
OUTLINE_SOFT = c('#3b3449')
OUTLINE_GOLD = c('#66460f')
OUTLINE_HAIR = c('#7d7796')
OUTLINE_STAFF = c('#380e14')

SKIN_HI = c('#fff3ec')
SKIN = c('#fbe4d8')
SKIN_SH = c('#f0beae')
SKIN_DEEP = c('#d79282')

EYE_LASH = c('#121e24')
EYE_DARK = c('#0e4849')
EYE_BASE = c('#1bb8a4')
EYE_HI = c('#4df2df')
EYE_WHITE = c('#f4fafd')

HAIR_HI = c('#ffffff')
HAIR_BASE = c('#f3eff8')
HAIR_SH = c('#dcd6eb')
HAIR_DEEP = c('#b4adc8')
HAIR_TIE = c('#229670')
HAIR_TIE_HI = c('#48e0a8')

GEM_HI = c('#ff7b92')
GEM_BASE = c('#e02244')
GEM_SH = c('#850e24')
GEM_DEEP = c('#4a0512')

GOLD_HI = c('#fff1a8')
GOLD_BASE = c('#f5cb58')
GOLD_SH = c('#c49226')
GOLD_DEEP = c('#7a5210')

ROBE_HI = c('#ffffff')
ROBE_BASE = c('#efeaf5')
ROBE_SH = c('#d2cce0')
ROBE_DEEP = c('#9f97b4')
ROBE_STRIPE = c('#2d273a')
ROBE_STRIPE_SOFT = c('#453e58')

STAFF_WOOD_HI = c('#ad4754')
STAFF_WOOD = c('#7a2632')
STAFF_WOOD_SH = c('#471017')

BOOT_CUFF = c('#694635')
BOOT_BASE = c('#492e22')
BOOT_SH = c('#2c1810')
LEGGINGS = c('#231c28')

# Layer buffers (RGBA numpy arrays)
layers = {
    "staff_back": np.zeros((H, W, 4), dtype=np.uint8),
    "hair_back": np.zeros((H, W, 4), dtype=np.uint8),
    "boots_legs": np.zeros((H, W, 4), dtype=np.uint8),
    "skirt": np.zeros((H, W, 4), dtype=np.uint8),
    "torso_tunic": np.zeros((H, W, 4), dtype=np.uint8),
    "capelet": np.zeros((H, W, 4), dtype=np.uint8),
    "arms_hands": np.zeros((H, W, 4), dtype=np.uint8),
    "head_ears": np.zeros((H, W, 4), dtype=np.uint8),
    "face_eyes": np.zeros((H, W, 4), dtype=np.uint8),
    "hair_front": np.zeros((H, W, 4), dtype=np.uint8),
    "staff_front": np.zeros((H, W, 4), dtype=np.uint8),
    "effects_highlights": np.zeros((H, W, 4), dtype=np.uint8),
}

def set_px(layer_name, x, y, color):
    if 0 <= x < W and 0 <= y < H:
        layers[layer_name][y, x] = color

def rect(layer_name, x1, y1, x2, y2, color):
    for y in range(y1, y2 + 1):
        for x in range(x1, x2 + 1):
            set_px(layer_name, x, y, color)

def fill_row(layer_name, y, x1, x2, color):
    for x in range(x1, x2 + 1):
        set_px(layer_name, x, y, color)

print("Constructing pixel art for Frieren Frame 0...")

# ==========================================
# 1. STAFF (Zoltraak Staff)
# Positioned at x ~ 63..73, y ~ 6..80
# Golden crescent ring top (y: 6..23), ruby gem (y: 11..16), wooden shaft (y: 24..78)
# ==========================================

# Crescent Head Ring (Gold Wings & Ring)
# Top tip of crescent
fill_row("staff_front", 6, 64, 66, OUTLINE_GOLD)
set_px("staff_front", 65, 6, GOLD_HI)

fill_row("staff_front", 7, 62, 68, GOLD_SH)
fill_row("staff_front", 7, 64, 66, GOLD_HI)
set_px("staff_front", 62, 7, OUTLINE_GOLD)
set_px("staff_front", 68, 7, OUTLINE_GOLD)

fill_row("staff_front", 8, 62, 69, GOLD_BASE)
set_px("staff_front", 62, 8, OUTLINE_GOLD)
set_px("staff_front", 63, 8, GOLD_HI)
set_px("staff_front", 69, 8, OUTLINE_GOLD)

fill_row("staff_front", 9, 61, 71, GOLD_BASE)
set_px("staff_front", 61, 9, OUTLINE_GOLD)
set_px("staff_front", 62, 9, GOLD_HI)
set_px("staff_front", 70, 9, GOLD_SH)
set_px("staff_front", 71, 9, OUTLINE_GOLD)

# Ring outer / hollow inner
for y in range(10, 18):
    set_px("staff_front", 61, y, OUTLINE_GOLD)
    set_px("staff_front", 62, y, GOLD_HI if y <= 13 else GOLD_BASE)
    set_px("staff_front", 63, y, GOLD_BASE if y <= 13 else GOLD_SH)
    
    set_px("staff_front", 69, y, GOLD_SH if y <= 13 else GOLD_BASE)
    set_px("staff_front", 70, y, GOLD_BASE if y <= 13 else GOLD_HI)
    set_px("staff_front", 71, y, OUTLINE_GOLD)

# Floating Ruby Core Gem inside Ring (x: 65..67, y: 11..15)
fill_row("staff_front", 11, 65, 67, GEM_HI)
set_px("staff_front", 65, 11, GEM_BASE)
fill_row("staff_front", 12, 64, 68, GEM_BASE)
set_px("staff_front", 66, 12, GEM_HI)
set_px("staff_front", 64, 12, GEM_SH)
set_px("staff_front", 68, 12, GEM_SH)

fill_row("staff_front", 13, 64, 68, GEM_BASE)
set_px("staff_front", 66, 13, GEM_HI)
set_px("staff_front", 64, 13, GEM_SH)
set_px("staff_front", 68, 13, GEM_SH)

fill_row("staff_front", 14, 65, 67, GEM_SH)
set_px("staff_front", 66, 14, GEM_BASE)
fill_row("staff_front", 15, 65, 67, GEM_DEEP)

# Bottom closure of golden crescent & collar mount
fill_row("staff_front", 18, 62, 70, GOLD_SH)
fill_row("staff_front", 18, 64, 68, GOLD_BASE)
set_px("staff_front", 62, 18, OUTLINE_GOLD)
set_px("staff_front", 70, 18, OUTLINE_GOLD)

fill_row("staff_front", 19, 63, 69, GOLD_BASE)
fill_row("staff_front", 19, 65, 67, GOLD_HI)
fill_row("staff_front", 20, 64, 68, GOLD_SH)
fill_row("staff_front", 20, 65, 67, GOLD_BASE)

# Collar joint to shaft
fill_row("staff_front", 21, 65, 67, GOLD_DEEP)
fill_row("staff_front", 22, 65, 67, GOLD_BASE)
fill_row("staff_front", 23, 65, 67, GOLD_SH)

# Wooden Shaft (y: 24..78, x: 66..68)
for y in range(24, 79):
    set_px("staff_back", 65, y, OUTLINE_STAFF)
    set_px("staff_back", 66, y, STAFF_WOOD_HI)
    set_px("staff_back", 67, y, STAFF_WOOD)
    set_px("staff_back", 68, y, STAFF_WOOD_SH)
    set_px("staff_back", 69, y, OUTLINE_STAFF)

# Red Ribbon tied around shaft (y: 57..66, x: 63..68)
fill_row("staff_front", 57, 65, 69, GEM_BASE)
fill_row("staff_front", 58, 64, 68, GEM_HI)
fill_row("staff_front", 59, 63, 67, GEM_BASE)
fill_row("staff_front", 60, 63, 66, GEM_SH)
fill_row("staff_front", 61, 62, 65, GEM_BASE)
fill_row("staff_front", 62, 62, 65, GEM_HI)
fill_row("staff_front", 63, 63, 66, GEM_SH)
fill_row("staff_front", 64, 64, 66, GEM_DEEP)

# Bottom metal cap of staff (y: 77..79, x: 66..68)
fill_row("staff_back", 77, 65, 68, GOLD_BASE)
fill_row("staff_back", 78, 66, 68, GOLD_SH)
fill_row("staff_back", 79, 66, 67, OUTLINE_GOLD)


# ==========================================
# 2. LEGS, TIGHTS & BOOTS
# Left foot: x ~ 33..42, y ~ 73..80
# Right foot: x ~ 58..66, y ~ 73..82 (lowest point y=82)
# ==========================================

# Dark tights / leggings visible under skirt
fill_row("boots_legs", 71, 36, 40, LEGGINGS)
fill_row("boots_legs", 72, 36, 40, LEGGINGS)
fill_row("boots_legs", 73, 35, 41, LEGGINGS)

fill_row("boots_legs", 71, 58, 64, LEGGINGS)
fill_row("boots_legs", 72, 58, 64, LEGGINGS)
fill_row("boots_legs", 73, 58, 64, LEGGINGS)

# Left Boot (Front-left foot)
fill_row("boots_legs", 74, 34, 42, BOOT_CUFF)
fill_row("boots_legs", 75, 33, 42, BOOT_CUFF)
fill_row("boots_legs", 76, 33, 42, BOOT_BASE)
fill_row("boots_legs", 77, 33, 41, BOOT_BASE)
fill_row("boots_legs", 78, 33, 40, BOOT_SH)
fill_row("boots_legs", 79, 34, 39, OUTLINE)

# Right Boot (Back-right planted foot)
fill_row("boots_legs", 74, 58, 65, BOOT_CUFF)
fill_row("boots_legs", 75, 57, 65, BOOT_CUFF)
fill_row("boots_legs", 76, 57, 65, BOOT_BASE)
fill_row("boots_legs", 77, 57, 65, BOOT_BASE)
fill_row("boots_legs", 78, 58, 65, BOOT_SH)
fill_row("boots_legs", 79, 58, 64, BOOT_SH)
fill_row("boots_legs", 80, 58, 64, BOOT_SH)
fill_row("boots_legs", 81, 59, 63, OUTLINE)
fill_row("boots_legs", 82, 60, 62, OUTLINE)


# ==========================================
# 3. SKIRT & ROBE (y: 58..75, x: 30..77)
# White pleated fabric with gold border trim along hem
# ==========================================

for y in range(60, 76):
    # Span widens gracefully downwards
    left_x = int(42 - (y - 60) * 0.8)
    right_x = int(68 + (y - 60) * 0.55)
    
    fill_row("skirt", y, left_x, right_x, ROBE_BASE)
    set_px("skirt", left_x, y, OUTLINE)
    set_px("skirt", right_x, y, OUTLINE)
    
    # Pleat shadows (vertical drape lines)
    if y <= 73:
        set_px("skirt", left_x + 3, y, ROBE_SH)
        set_px("skirt", left_x + 8, y, ROBE_DEEP)
        set_px("skirt", left_x + 9, y, ROBE_SH)
        set_px("skirt", 52, y, ROBE_HI)
        set_px("skirt", 56, y, ROBE_SH)
        set_px("skirt", 61, y, ROBE_DEEP)
        set_px("skirt", 62, y, ROBE_SH)
        set_px("skirt", right_x - 3, y, ROBE_SH)

# Gold trim along skirt hemline (y: 72..75)
for y in (73, 74):
    left_x = int(42 - (y - 60) * 0.8) + 1
    right_x = int(68 + (y - 60) * 0.55) - 1
    for x in range(left_x, right_x + 1):
        if (x + y) % 3 == 0:
            set_px("skirt", x, y, GOLD_HI)
        else:
            set_px("skirt", x, y, GOLD_BASE)


# ==========================================
# 4. TORSO & STRIPED TUNIC (y: 48..60, x: 44..66)
# White tunic with dark vertical stripes & gold waist sash
# ==========================================

for y in range(48, 61):
    fill_row("torso_tunic", y, 46, 65, ROBE_BASE)
    set_px("torso_tunic", 46, y, OUTLINE)
    set_px("torso_tunic", 65, y, OUTLINE)
    
    # Vertical black/navy stripes
    set_px("torso_tunic", 50, y, ROBE_STRIPE)
    set_px("torso_tunic", 54, y, ROBE_STRIPE)
    set_px("torso_tunic", 58, y, ROBE_STRIPE)
    set_px("torso_tunic", 62, y, ROBE_STRIPE)

# Gold belt / sash at waist (y: 57..58)
fill_row("torso_tunic", 57, 46, 65, GOLD_SH)
fill_row("torso_tunic", 58, 46, 65, GOLD_BASE)
# Gold buckle at center (x: 54..56, y: 56..58)
fill_row("torso_tunic", 56, 53, 57, GOLD_HI)
fill_row("torso_tunic", 57, 53, 57, GOLD_BASE)
fill_row("torso_tunic", 58, 53, 57, GOLD_SH)


# ==========================================
# 5. CAPELET (SHOULDER MANTLE) (y: 42..55, x: 38..71)
# Short white capelet draped over shoulders with black band & gold trim
# ==========================================

# Shoulder curve
fill_row("capelet", 42, 42, 68, ROBE_HI)
fill_row("capelet", 43, 40, 69, ROBE_BASE)
fill_row("capelet", 44, 39, 70, ROBE_BASE)
fill_row("capelet", 45, 38, 71, ROBE_BASE)
fill_row("capelet", 46, 38, 71, ROBE_BASE)
fill_row("capelet", 47, 37, 72, ROBE_BASE)
fill_row("capelet", 48, 37, 72, ROBE_BASE)
fill_row("capelet", 49, 37, 72, ROBE_BASE)
fill_row("capelet", 50, 38, 72, ROBE_BASE)

# Outlines of capelet
for y in range(42, 51):
    xs = [x for x in range(W) if layers["capelet"][y, x, 3] > 0]
    if xs:
        set_px("capelet", min(xs), y, OUTLINE)
        set_px("capelet", max(xs), y, OUTLINE)

# Black decorative band near bottom of capelet (y: 49..50)
for y in (49, 50):
    for x in range(39, 72):
        if layers["capelet"][y, x, 3] > 0:
            set_px("capelet", x, y, ROBE_STRIPE)

# Gold trim at bottom border of capelet (y: 51..52)
fill_row("capelet", 51, 39, 71, GOLD_BASE)
fill_row("capelet", 52, 40, 70, GOLD_SH)
set_px("capelet", 54, 51, GOLD_HI)
set_px("capelet", 55, 51, GOLD_HI)

# Center Collar Brooch (Gold clasp with Ruby Gem) (y: 43..47, x: 53..57)
fill_row("capelet", 43, 53, 57, GOLD_HI)
fill_row("capelet", 44, 52, 58, GOLD_BASE)
fill_row("capelet", 45, 52, 58, GOLD_BASE)
fill_row("capelet", 46, 53, 57, GOLD_SH)
fill_row("capelet", 47, 54, 56, GOLD_DEEP)

# Ruby gem inside brooch (x: 54..56, y: 44..45)
set_px("capelet", 55, 44, GEM_HI)
fill_row("capelet", 45, 54, 56, GEM_BASE)
set_px("capelet", 55, 46, GEM_SH)


# ==========================================
# 6. ARMS & HANDS
# Right arm (draped at side): x ~ 35..43, y ~ 46..57
# Left arm (holding staff): x ~ 65..72, y ~ 46..57
# ==========================================

# Left hand gripping staff at x ~ 65..68, y ~ 53..56
fill_row("arms_hands", 52, 65, 69, ROBE_BASE)
fill_row("arms_hands", 53, 65, 68, SKIN)
fill_row("arms_hands", 54, 65, 68, SKIN_HI)
fill_row("arms_hands", 55, 65, 68, SKIN)
fill_row("arms_hands", 56, 65, 67, SKIN_SH)
set_px("arms_hands", 65, 54, OUTLINE)
set_px("arms_hands", 69, 54, OUTLINE)

# Right hand at side (x ~ 36..40, y ~ 54..57)
fill_row("arms_hands", 53, 36, 40, ROBE_BASE)
fill_row("arms_hands", 54, 36, 39, SKIN_HI)
fill_row("arms_hands", 55, 36, 39, SKIN)
fill_row("arms_hands", 56, 37, 39, SKIN_SH)
set_px("arms_hands", 35, 54, OUTLINE)
set_px("arms_hands", 40, 54, OUTLINE)


# ==========================================
# 7. HEAD, FACE, EARS & EARRINGS
# Center of head ~ (56, 30)
# Long elf ears extending sideways: Left ear (x: 42..48, y: 35..38), Right ear (x: 64..68, y: 35..38)
# Ruby teardrop earrings dangling below ears (y: 38..43)
# ==========================================

# Head skin base
for y in range(26, 43):
    fill_row("head_ears", y, 48, 64, SKIN)

# Left Elf Ear (Long pointy ear pointing outward-left)
fill_row("head_ears", 34, 43, 48, OUTLINE)
fill_row("head_ears", 35, 41, 48, SKIN_HI)
fill_row("head_ears", 36, 40, 48, SKIN)
fill_row("head_ears", 37, 41, 47, SKIN_SH)
fill_row("head_ears", 38, 43, 46, OUTLINE)
set_px("head_ears", 39, 36, SKIN_HI) # tip of left ear

# Right Elf Ear (partially behind hair)
fill_row("head_ears", 35, 64, 69, SKIN_HI)
fill_row("head_ears", 36, 64, 70, SKIN)
fill_row("head_ears", 37, 64, 69, SKIN_SH)
set_px("head_ears", 71, 36, OUTLINE)

# Ruby drop earring on Left Ear (y: 39..43, x: 43..45)
set_px("head_ears", 44, 39, GOLD_BASE) # earring stud
fill_row("head_ears", 40, 43, 45, GEM_HI)
fill_row("head_ears", 41, 43, 45, GEM_BASE)
fill_row("head_ears", 42, 43, 45, GEM_SH)
set_px("head_ears", 44, 43, GEM_DEEP)

# Ruby drop earring on Right Ear (y: 39..43, x: 67..69)
set_px("head_ears", 67, 39, GOLD_BASE)
fill_row("head_ears", 40, 66, 68, GEM_HI)
fill_row("head_ears", 41, 66, 68, GEM_BASE)
fill_row("head_ears", 42, 66, 68, GEM_SH)
set_px("head_ears", 67, 43, GEM_DEEP)


# ==========================================
# 8. FACE & EYES (Frieren's calm, wise expression)
# Left eye: x ~ 50..53, y ~ 34..37
# Right eye: x ~ 57..60, y ~ 34..37
# Mouth: x ~ 54..55, y ~ 41
# ==========================================

# Eye whites
fill_row("face_eyes", 35, 50, 53, EYE_WHITE)
fill_row("face_eyes", 36, 50, 53, EYE_WHITE)
fill_row("face_eyes", 35, 57, 60, EYE_WHITE)
fill_row("face_eyes", 36, 57, 60, EYE_WHITE)

# Upper dark eyelash line
fill_row("face_eyes", 34, 49, 54, EYE_LASH)
fill_row("face_eyes", 34, 56, 61, EYE_LASH)

# Iris & Pupils (Emerald turquoise #1bb8a4, #4df2df)
set_px("face_eyes", 51, 35, EYE_DARK)
set_px("face_eyes", 52, 35, EYE_BASE)
set_px("face_eyes", 51, 36, EYE_BASE)
set_px("face_eyes", 52, 36, EYE_HI)
set_px("face_eyes", 50, 35, EYE_HI) # Catchlight

set_px("face_eyes", 58, 35, EYE_DARK)
set_px("face_eyes", 59, 35, EYE_BASE)
set_px("face_eyes", 58, 36, EYE_BASE)
set_px("face_eyes", 59, 36, EYE_HI)
set_px("face_eyes", 57, 35, EYE_HI) # Catchlight

# Subtle soft eyebrows (silvery lavender)
fill_row("face_eyes", 32, 50, 53, HAIR_DEEP)
fill_row("face_eyes", 32, 57, 60, HAIR_DEEP)

# Cute small nose & calm mouth
set_px("face_eyes", 55, 38, SKIN_SH)
set_px("face_eyes", 54, 41, SKIN_DEEP)
set_px("face_eyes", 55, 41, SKIN_DEEP)


# ==========================================
# 9. HAIR (FRONT BANGS & TWIN PIGTAILS)
# Silvery white with soft lavender shading
# Twin pigtails falling down left & right sides
# ==========================================

# Hair Dome / Forehead / Crown (y: 22..34, x: 46..67)
fill_row("hair_front", 22, 52, 63, OUTLINE_HAIR)
fill_row("hair_front", 23, 50, 65, HAIR_HI)
fill_row("hair_front", 24, 48, 66, HAIR_HI)
fill_row("hair_front", 25, 47, 67, HAIR_BASE)
fill_row("hair_front", 26, 46, 68, HAIR_BASE)
fill_row("hair_front", 27, 46, 68, HAIR_BASE)
fill_row("hair_front", 28, 45, 68, HAIR_BASE)

# Crown shading & outline
set_px("hair_front", 51, 23, OUTLINE_HAIR)
set_px("hair_front", 64, 23, OUTLINE_HAIR)

# Front Bangs framing the face (y: 28..35)
# Center parting
fill_row("hair_front", 29, 46, 49, HAIR_HI)
fill_row("hair_front", 29, 54, 56, HAIR_HI)
fill_row("hair_front", 29, 62, 67, HAIR_BASE)

fill_row("hair_front", 30, 46, 49, HAIR_BASE)
fill_row("hair_front", 30, 54, 56, HAIR_BASE)
fill_row("hair_front", 30, 63, 67, HAIR_BASE)

# Bang tips
fill_row("hair_front", 31, 47, 49, HAIR_SH)
fill_row("hair_front", 31, 54, 55, HAIR_SH)
fill_row("hair_front", 31, 63, 66, HAIR_SH)

fill_row("hair_front", 32, 47, 48, HAIR_DEEP)
set_px("hair_front", 54, 32, HAIR_DEEP)
fill_row("hair_front", 32, 64, 65, HAIR_DEEP)

# Left Side Bang (framing ear & cheek)
for y in range(33, 42):
    fill_row("hair_front", y, 45, 47, HAIR_BASE)
    set_px("hair_front", 45, y, OUTLINE_HAIR)
    set_px("hair_front", 47, y, HAIR_SH)

# Right Side Bang
for y in range(33, 42):
    fill_row("hair_front", y, 63, 65, HAIR_BASE)
    set_px("hair_front", 65, y, OUTLINE_HAIR)
    set_px("hair_front", 63, y, HAIR_SH)

# Emerald Hair Ties (Left: x ~ 43..45, y ~ 37..39; Right: x ~ 65..67, y ~ 37..39)
fill_row("hair_front", 37, 43, 45, HAIR_TIE_HI)
fill_row("hair_front", 38, 43, 45, HAIR_TIE)
fill_row("hair_front", 39, 43, 45, HAIR_TIE)

fill_row("hair_front", 37, 65, 67, HAIR_TIE_HI)
fill_row("hair_front", 38, 65, 67, HAIR_TIE)
fill_row("hair_front", 39, 65, 67, HAIR_TIE)

# Twin Low Pigtails (Draping down to y ~ 65)
# Left Pigtail (y: 40..66, x: 36..44)
for y in range(40, 67):
    # gentle sway outwards then taper
    cur_x = int(41 - np.sin((y - 40) / 26.0 * 3.14) * 4)
    fill_row("hair_front", y, cur_x - 2, cur_x + 2, HAIR_BASE)
    set_px("hair_front", cur_x - 2, y, OUTLINE_HAIR)
    set_px("hair_front", cur_x - 1, y, HAIR_HI)
    set_px("hair_front", cur_x + 1, y, HAIR_SH)
    set_px("hair_front", cur_x + 2, y, OUTLINE_HAIR)

# Right Pigtail (y: 40..64, x: 65..72)
for y in range(40, 65):
    cur_x = int(67 + np.sin((y - 40) / 24.0 * 3.14) * 3)
    fill_row("hair_back", y, cur_x - 2, cur_x + 2, HAIR_BASE)
    set_px("hair_back", cur_x - 2, y, OUTLINE_HAIR)
    set_px("hair_back", cur_x, y, HAIR_HI)
    set_px("hair_back", cur_x + 1, y, HAIR_SH)
    set_px("hair_back", cur_x + 2, y, OUTLINE_HAIR)


# ==========================================
# 10. COMPOSITE ALL LAYERS
# ==========================================
comp = np.zeros((H, W, 4), dtype=np.uint8)

layer_order = [
    "staff_back",
    "hair_back",
    "boots_legs",
    "skirt",
    "torso_tunic",
    "capelet",
    "arms_hands",
    "head_ears",
    "face_eyes",
    "hair_front",
    "staff_front",
    "effects_highlights"
]

for l_name in layer_order:
    buf = layers[l_name]
    mask = buf[:, :, 3] > 0
    comp[mask] = buf[mask]

out_img = Image.fromarray(comp, "RGBA")
out_img.save(OUT_PNG)
print(f"Saved generated Frame 0 to: {OUT_PNG}")
print(f"Bbox: {out_img.getbbox()}")

# Create Side-by-Side Comparison with D.Neria Frame 0
dneria_img = Image.open(DNERIA_F0).convert("RGBA")
comp_img = Image.new("RGBA", (W * 3 + 40, H + 20), (30, 30, 36, 255))
comp_img.paste(dneria_img, (10, 10), dneria_img)
comp_img.paste(out_img, (W + 20, 10), out_img)

# Also create an overlay image (50% opacity)
overlay = Image.blend(dneria_img, out_img, 0.5)
comp_img.paste(overlay, (W * 2 + 30, 10), overlay)

comp_img.save(OUT_COMPARE)
print(f"Saved side-by-side comparison to: {OUT_COMPARE}")

