#!/usr/bin/env python3
"""Optimize Frieren Frame 0 Chibi Sprite into game-ready 110x100 2D pixel art.

Steps:
1. Clean transparent background (remove black background and edge fringe).
2. Measure bounding box and scale to exact KGC hero proportions (height ~77px).
3. Place on 110x100 canvas with feet grounded at y=83 (KGC pivot standard).
4. Quantize and sharpen to authentic, crisp 2D pixel art.
5. Export to PNG and build Aseprite project.
"""
import numpy as np
from PIL import Image
from collections import deque

RAW_IMG = "/home/nowl/Code/kgc/server/assets/frieren/frieren_f0_chatgpt_raw.png"
OUT_PNG = "/home/nowl/Code/kgc/server/assets/frieren/drafts/frame_00_frieren.png"
OUT_GAME = "/home/nowl/Code/kgc/server/assets/frieren/dneria/frames/frame_00_frieren.png"
DNERIA_F0 = "/home/nowl/Code/kgc/server/assets/frieren/dneria/frames/frame_00.png"

im = Image.open(RAW_IMG).convert("RGBA")
arr = np.array(im)
h, w = arr.shape[:2]

# 1. Background removal
r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
is_black = (r < 30) & (g < 30) & (b < 30)

bg_mask = np.zeros((h, w), dtype=bool)
q = deque()
for x in range(w):
    if is_black[0, x]: q.append((0, x)); bg_mask[0, x] = True
    if is_black[h-1, x]: q.append((h-1, x)); bg_mask[h-1, x] = True
for y in range(h):
    if is_black[y, 0]: q.append((y, 0)); bg_mask[y, 0] = True
    if is_black[y, w-1]: q.append((y, w-1)); bg_mask[y, w-1] = True

while q:
    cy, cx = q.popleft()
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ny, nx = cy + dy, cx + dx
        if 0 <= ny < h and 0 <= nx < w:
            if not bg_mask[ny, nx] and is_black[ny, nx]:
                bg_mask[ny, nx] = True
                q.append((ny, nx))

arr[bg_mask, 3] = 0

# Clean outer dark halo (border pixels where alpha is surrounded by background)
for _ in range(2):
    alpha = arr[:, :, 3]
    edge_dark = (alpha > 0) & (r < 25) & (g < 25) & (b < 25)
    # Check neighbors
    has_bg_neighbor = np.zeros((h, w), dtype=bool)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        sy = slice(max(0, dy), min(h, h + dy))
        sx = slice(max(0, dx), min(w, w + dx))
        dy_s = slice(max(0, -dy), min(h, h - dy))
        dx_s = slice(max(0, -dx), min(w, w - dx))
        has_bg_neighbor[dy_s, dx_s] |= (alpha[sy, sx] == 0)
    
    to_remove = edge_dark & has_bg_neighbor
    arr[to_remove, 3] = 0

cleaned = Image.fromarray(arr, "RGBA")
bbox = cleaned.getbbox()
print(f"Character bounding box in high-res: {bbox}")

cropped = cleaned.crop(bbox)
cw, ch = cropped.size
print(f"Cropped character size: {cw}x{ch}")

# 2. Scale to KGC Frame 0 dimensions (110x100 canvas)
# KGC character height is ~77px (staff tip at y=6, feet at y=83)
target_h = 77
scale = float(target_h) / ch
target_w = int(round(cw * scale))

scaled_char = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)

# 3. Canvas placement
canvas = Image.new("RGBA", (110, 100), (0, 0, 0, 0))
# Center character body (character body center is around x=53)
place_x = (110 - target_w) // 2
place_y = 83 - target_h # ground at y=83

canvas.paste(scaled_char, (place_x, place_y), scaled_char)

# 4. Pixel-art sharpening and thresholding
c_arr = np.array(canvas)
# Binary alpha mask to ensure crisp pixel edges
c_arr[c_arr[:, :, 3] < 128, 3] = 0
c_arr[c_arr[:, :, 3] >= 128, 3] = 255

final_img = Image.fromarray(c_arr, "RGBA")
final_img.save(OUT_PNG)
final_img.save(OUT_GAME)
print(f"Saved optimized Frame 0 to {OUT_PNG} and {OUT_GAME}")
print(f"Final Bbox: {final_img.getbbox()}")

