#!/usr/bin/env python3
"""Build the Frieren skin atlas from deterministic pixel-art source.

This intentionally does not shrink the supplied illustration into a sprite.
The KGC/Farael atlas is used only to recover the runtime geometry and frame
layout. Frieren's face, hair, costume, jewelry, and staff are drawn from a
shared character spec at 4x source resolution and reduced exactly once with
nearest-neighbour sampling.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


REPO = Path(__file__).resolve().parents[2]
FRIEREN_DIR = REPO / "server/assets/frieren"
REFERENCE = FRIEREN_DIR / "Unit_10570_02_reference.png"
ILLUST_REFERENCE = REPO.parent.parent / "Downloads/Farael_Frieren/Farael_Illust.png"
OUT = FRIEREN_DIR / "generated"

COLS = 5
ROWS = 4
FRAME_COUNT = 19
CELL_W = 130
CELL_H = 140
ATLAS_W = COLS * CELL_W
ATLAS_H = ROWS * CELL_H
MASTER_SCALE = 4
MASTER_CELL_W = CELL_W * MASTER_SCALE
MASTER_CELL_H = CELL_H * MASTER_SCALE

RGBA = tuple[int, int, int, int]


def c(hex_color: str) -> RGBA:
    value = hex_color.lstrip("#")
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
        255,
    )


PAL: dict[str, RGBA] = {
    "outline": c("#322a46"),
    "outline2": c("#4d496d"),
    "skin_shadow": c("#d99f99"),
    "skin": c("#f3c9ba"),
    "skin_light": c("#ffe4d8"),
    "eye_dark": c("#0f6570"),
    "eye": c("#32c8c0"),
    "hair_deep": c("#8983b2"),
    "hair_shadow": c("#aaa6cf"),
    "hair": c("#dddaf1"),
    "hair_light": c("#f7f3ff"),
    "robe_deep": c("#57516f"),
    "robe_shadow": c("#8884ad"),
    "robe": c("#e9e7f3"),
    "robe_light": c("#fffdf6"),
    "undersuit": c("#1f2230"),
    "undersuit_hi": c("#596070"),
    "gold_dark": c("#8f6721"),
    "gold": c("#d7a846"),
    "gold_light": c("#ffe08b"),
    "boot": c("#3a261d"),
    "boot_hi": c("#6b4530"),
    "staff_dark": c("#4a1e24"),
    "staff": c("#8a2d38"),
    "staff_hi": c("#c44d58"),
    "gem_dark": c("#7b0b27"),
    "gem": c("#d91d3f"),
    "gem_light": c("#ff9a98"),
    "ribbon_dark": c("#711b26"),
    "ribbon": c("#b83242"),
    "magic_dark": c("#1967d2"),
    "magic": c("#25dce8"),
    "magic_light": c("#bfffff"),
    "white": c("#ffffff"),
}


@dataclass(frozen=True)
class Pose:
    frame: int
    direction: str
    staff: str
    action: str
    cx_bias: float = 0.5
    bob: int = 0
    body_scale: float = 1.0


POSES: dict[int, Pose] = {
    0: Pose(0, "front", "diag", "locomotion", 0.51, 0, 1.0),
    1: Pose(1, "front", "diag", "attack_windup", 0.50, -1, 1.0),
    2: Pose(2, "front", "diag", "attack_release", 0.50, 0, 1.0),
    3: Pose(3, "front", "vertical", "skill_windup", 0.48, -1, 0.98),
    4: Pose(4, "front", "vertical", "active_cast", 0.50, 0, 0.98),
    5: Pose(5, "left", "diag", "locomotion", 0.42, 0, 1.0),
    6: Pose(6, "left", "diag", "attack_windup", 0.42, -1, 1.0),
    7: Pose(7, "left", "diag", "attack_release", 0.43, 0, 1.0),
    8: Pose(8, "left", "vertical", "skill_windup", 0.45, -1, 0.98),
    9: Pose(9, "left", "vertical", "active_cast", 0.46, 0, 0.96),
    10: Pose(10, "back", "diag", "locomotion", 0.58, 0, 1.0),
    11: Pose(11, "back", "diag", "attack_windup", 0.56, -1, 1.0),
    12: Pose(12, "back", "diag", "attack_release", 0.55, 0, 1.0),
    13: Pose(13, "back", "vertical", "skill_windup", 0.54, -1, 0.98),
    14: Pose(14, "back", "vertical", "active_cast", 0.52, 0, 0.96),
    15: Pose(15, "magic", "none", "effect_a"),
    16: Pose(16, "magic", "none", "effect_b"),
    17: Pose(17, "magic", "none", "effect_c"),
    18: Pose(18, "front", "idle_vertical", "idle", 0.50, 0, 1.04),
}


def s(v: float) -> int:
    return int(round(v * MASTER_SCALE))


class Canvas:
    def __init__(self, image: Image.Image, ox: int, oy: int):
        self.draw = ImageDraw.Draw(image, "RGBA")
        self.ox = ox
        self.oy = oy

    def pt(self, x: float, y: float) -> tuple[int, int]:
        return (self.ox + s(x), self.oy + s(y))

    def poly(self, points: Iterable[tuple[float, float]], color: RGBA) -> None:
        self.draw.polygon([self.pt(x, y) for x, y in points], fill=color)

    def line(
        self,
        points: Iterable[tuple[float, float]],
        color: RGBA,
        width: float = 1.0,
    ) -> None:
        self.draw.line(
            [self.pt(x, y) for x, y in points],
            fill=color,
            width=max(1, s(width)),
        )

    def rect(self, xy: tuple[float, float, float, float], color: RGBA) -> None:
        x1, y1, x2, y2 = xy
        self.draw.rectangle(
            (self.ox + s(x1), self.oy + s(y1), self.ox + s(x2), self.oy + s(y2)),
            fill=color,
        )

    def ellipse(self, xy: tuple[float, float, float, float], color: RGBA) -> None:
        x1, y1, x2, y2 = xy
        self.draw.ellipse(
            (self.ox + s(x1), self.oy + s(y1), self.ox + s(x2), self.oy + s(y2)),
            fill=color,
        )


def source_bboxes(reference: Image.Image) -> list[dict[str, object]]:
    if reference.size != (ATLAS_W, ATLAS_H):
        raise ValueError(f"reference must be {(ATLAS_W, ATLAS_H)}, got {reference.size}")
    out: list[dict[str, object]] = []
    for index in range(20):
        row, col = divmod(index, COLS)
        cell = reference.crop(
            (col * CELL_W, row * CELL_H, (col + 1) * CELL_W, (row + 1) * CELL_H)
        )
        alpha_bbox = cell.getchannel("A").getbbox()
        character_pixels: list[tuple[int, int]] = []
        pixels = cell.load()
        for y in range(CELL_H):
            for x in range(CELL_W):
                red, green, blue, alpha = pixels[x, y]
                if not alpha:
                    continue
                if red < 18 and green < 18 and blue < 18:
                    continue
                character_pixels.append((x, y))
        if character_pixels:
            xs = [p[0] for p in character_pixels]
            ys = [p[1] for p in character_pixels]
            character_bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
        else:
            character_bbox = None
        out.append(
            {
                "frame": index,
                "alpha_bbox": alpha_bbox,
                "character_bbox": character_bbox,
                "direction": POSES[index].direction if index in POSES else "empty",
            }
        )
    return out


def lerp(
    a: tuple[float, float],
    b: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def staff_endpoints(
    bbox: tuple[int, int, int, int],
    pose: Pose,
) -> tuple[tuple[float, float], tuple[float, float]]:
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    height = y2 - y1
    if pose.staff == "diag":
        if pose.direction == "back":
            start = (x1 + width * 0.15, y2 - 4)
            end = (x2 - width * 0.08, y1 + 7)
        elif pose.direction == "left":
            start = (x1 + width * 0.08, y2 - 4)
            end = (x2 - width * 0.06, y1 + 6)
        else:
            start = (x1 + width * 0.08, y2 - 4)
            end = (x2 - width * 0.10, y1 + 6)
    elif pose.staff == "idle_vertical":
        staff_x = x2 - max(5, width * 0.12)
        start = (staff_x, y2 - 4)
        end = (staff_x, y1 + 6)
    else:
        staff_x = x1 + width * (0.58 if pose.direction != "left" else 0.62)
        start = (staff_x - 1, y2 - 4)
        end = (staff_x + 1, y1 + 5)
    if height < 70 and pose.staff != "diag":
        end = (end[0], y1 + 4)
    return start, end


def draw_staff(cv: Canvas, start: tuple[float, float], end: tuple[float, float]) -> None:
    cv.line([start, end], PAL["outline"], 4.0)
    cv.line([start, end], PAL["staff_dark"], 3.0)
    cv.line([start, end], PAL["staff"], 2.0)
    cv.line([start, end], PAL["staff_hi"], 0.85)

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = max(1.0, math.hypot(dx, dy))
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    hx, hy = end

    cv.ellipse((hx - 7, hy - 7, hx + 7, hy + 7), PAL["outline"])
    cv.ellipse((hx - 6, hy - 6, hx + 6, hy + 6), PAL["gold_dark"])
    cv.ellipse((hx - 5, hy - 5, hx + 5, hy + 5), PAL["gold"])
    cv.ellipse((hx - 3.5, hy - 3.5, hx + 3.5, hy + 3.5), PAL["gem_dark"])
    cv.ellipse((hx - 2.5, hy - 2.5, hx + 2.5, hy + 2.5), PAL["gem"])
    cv.rect((hx - 1, hy - 3, hx + 1, hy - 2), PAL["gem_light"])
    cv.line(
        [(hx - 5, hy - 4), (hx - 2, hy - 6), (hx + 2, hy - 6), (hx + 5, hy - 4)],
        PAL["gold_light"],
        1.0,
    )
    cv.poly(
        [
            (hx + px * 6 + ux * 1, hy + py * 6 + uy * 1),
            (hx + px * 11 - ux * 2, hy + py * 11 - uy * 2),
            (hx + px * 4 - ux * 5, hy + py * 4 - uy * 5),
        ],
        PAL["gold"],
    )
    cv.poly(
        [
            (hx - px * 6 + ux * 1, hy - py * 6 + uy * 1),
            (hx - px * 10 - ux * 1, hy - py * 10 - uy * 1),
            (hx - px * 4 - ux * 5, hy - py * 4 - uy * 5),
        ],
        PAL["gold_dark"],
    )
    ribbon = (hx - ux * 8, hy - uy * 8)
    cv.ellipse((ribbon[0] - 2, ribbon[1] - 2, ribbon[0] + 2, ribbon[1] + 2), PAL["ribbon_dark"])
    cv.poly(
        [
            (ribbon[0], ribbon[1]),
            (ribbon[0] + px * 8 - ux * 2, ribbon[1] + py * 8 - uy * 2),
            (ribbon[0] + px * 3 - ux * 7, ribbon[1] + py * 3 - uy * 7),
        ],
        PAL["ribbon"],
    )
    cv.poly(
        [
            (ribbon[0], ribbon[1]),
            (ribbon[0] - px * 7 - ux * 1, ribbon[1] - py * 7 - uy * 1),
            (ribbon[0] - px * 2 - ux * 7, ribbon[1] - py * 2 - uy * 7),
        ],
        PAL["ribbon_dark"],
    )


def draw_boots(cv: Canvas, cx: float, baseline: float, direction: str, action: str) -> None:
    spread = 4 if action in {"attack_release", "locomotion"} else 3
    if direction == "left":
        cv.rect((cx - 5, baseline - 5, cx - 1, baseline), PAL["outline"])
        cv.rect((cx - 2, baseline - 5, cx + 4, baseline), PAL["outline"])
        cv.rect((cx - 6, baseline - 4, cx - 2, baseline - 1), PAL["boot"])
        cv.rect((cx - 2, baseline - 4, cx + 4, baseline - 1), PAL["boot"])
        cv.rect((cx - 6, baseline - 4, cx - 4, baseline - 3), PAL["boot_hi"])
    else:
        cv.rect((cx - spread - 3, baseline - 5, cx - spread + 2, baseline), PAL["outline"])
        cv.rect((cx + spread - 2, baseline - 5, cx + spread + 3, baseline), PAL["outline"])
        cv.rect((cx - spread - 3, baseline - 4, cx - spread + 1, baseline - 1), PAL["boot"])
        cv.rect((cx + spread - 1, baseline - 4, cx + spread + 3, baseline - 1), PAL["boot"])


def draw_front_body(cv: Canvas, bbox: tuple[int, int, int, int], pose: Pose) -> None:
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    baseline = y2 - 3 + pose.bob
    body_h = min(61, max(51, (y2 - y1) * 0.75)) * pose.body_scale
    cx = x1 + width * pose.cx_bias
    head_cy = baseline - body_h + 11
    shoulder_y = head_cy + 12
    waist_y = baseline - 31
    hem_y = baseline - 7

    cv.poly(
        [
            (cx - 12, head_cy - 7),
            (cx - 23, shoulder_y + 2),
            (cx - 17, hem_y),
            (cx - 5, hem_y - 3),
            (cx, shoulder_y + 7),
            (cx + 5, hem_y - 3),
            (cx + 17, hem_y),
            (cx + 22, shoulder_y + 1),
            (cx + 11, head_cy - 7),
        ],
        PAL["outline"],
    )
    cv.poly(
        [
            (cx - 10, head_cy - 6),
            (cx - 19, shoulder_y + 3),
            (cx - 14, hem_y - 1),
            (cx - 3, hem_y - 5),
            (cx, shoulder_y + 7),
            (cx + 4, hem_y - 5),
            (cx + 15, hem_y - 1),
            (cx + 18, shoulder_y + 4),
            (cx + 9, head_cy - 6),
        ],
        PAL["hair_shadow"],
    )
    cv.poly([(cx - 7, head_cy), (cx - 13, hem_y - 8), (cx - 6, hem_y - 12), (cx - 2, shoulder_y)], PAL["hair"])
    cv.poly([(cx + 6, head_cy), (cx + 12, hem_y - 8), (cx + 5, hem_y - 12), (cx + 2, shoulder_y)], PAL["hair"])

    draw_boots(cv, cx, baseline, pose.direction, pose.action)

    cv.poly(
        [
            (cx - 14, shoulder_y - 1),
            (cx + 14, shoulder_y - 1),
            (cx + 21, hem_y),
            (cx + 8, baseline - 2),
            (cx, hem_y - 4),
            (cx - 8, baseline - 2),
            (cx - 21, hem_y),
        ],
        PAL["outline"],
    )
    cv.poly(
        [
            (cx - 12, shoulder_y),
            (cx + 12, shoulder_y),
            (cx + 18, hem_y - 1),
            (cx + 7, baseline - 5),
            (cx, hem_y - 5),
            (cx - 7, baseline - 5),
            (cx - 18, hem_y - 1),
        ],
        PAL["robe"],
    )
    cv.poly([(cx + 6, shoulder_y + 2), (cx + 16, hem_y - 2), (cx + 7, hem_y + 1), (cx + 2, waist_y)], PAL["robe_shadow"])
    cv.poly([(cx - 4, shoulder_y + 2), (cx + 4, shoulder_y + 2), (cx + 5, hem_y - 6), (cx - 5, hem_y - 6)], PAL["undersuit"])
    cv.rect((cx - 4, shoulder_y + 9, cx + 4, shoulder_y + 11), PAL["undersuit_hi"])
    cv.rect((cx - 8, waist_y - 1, cx + 9, waist_y + 3), PAL["outline"])
    cv.rect((cx - 7, waist_y, cx + 8, waist_y + 2), PAL["undersuit"])
    cv.rect((cx - 1, waist_y, cx + 3, waist_y + 2), PAL["gold"])
    cv.line([(cx - 12, shoulder_y + 2), (cx - 17, hem_y - 1)], PAL["gold_dark"], 2.0)
    cv.line([(cx + 12, shoulder_y + 2), (cx + 17, hem_y - 1)], PAL["gold"], 2.0)
    cv.line([(cx - 15, hem_y - 1), (cx - 3, baseline - 5), (cx + 4, hem_y - 5), (cx + 16, hem_y - 1)], PAL["gold"], 1.5)

    left_hand = (cx - 19, waist_y - (6 if pose.action == "attack_windup" else 1))
    right_hand = (cx + 17, waist_y - (8 if pose.action in {"attack_release", "active_cast"} else 3))
    if pose.action == "skill_windup":
        left_hand = (cx - 17, waist_y - 9)
        right_hand = (cx + 11, waist_y - 14)
    if pose.action == "idle":
        left_hand = (cx - 12, waist_y + 3)
        right_hand = (x2 - max(6, width * 0.14), waist_y - 2)
    cv.line([(cx - 11, shoulder_y + 4), left_hand], PAL["outline"], 6.0)
    cv.line([(cx + 11, shoulder_y + 4), right_hand], PAL["outline"], 6.0)
    cv.line([(cx - 11, shoulder_y + 4), left_hand], PAL["robe"], 4.0)
    cv.line([(cx + 11, shoulder_y + 4), right_hand], PAL["robe_shadow"] if pose.action == "active_cast" else PAL["robe"], 4.0)
    cv.line([(cx - 16, waist_y - 1), left_hand], PAL["gold"], 1.3)
    cv.line([(cx + 14, waist_y - 2), right_hand], PAL["gold"], 1.3)
    for hand in (left_hand, right_hand):
        cv.ellipse((hand[0] - 2, hand[1] - 2, hand[0] + 2, hand[1] + 2), PAL["outline"])
        cv.ellipse((hand[0] - 1.4, hand[1] - 1.4, hand[0] + 1.4, hand[1] + 1.4), PAL["skin"])

    draw_front_head(cv, cx, head_cy)


def draw_front_head(cv: Canvas, cx: float, cy: float) -> None:
    cv.poly([(cx - 8, cy - 1), (cx - 21, cy - 5), (cx - 10, cy + 5)], PAL["outline"])
    cv.poly([(cx + 8, cy - 1), (cx + 21, cy - 5), (cx + 10, cy + 5)], PAL["outline"])
    cv.poly([(cx - 8, cy), (cx - 18, cy - 4), (cx - 10, cy + 3)], PAL["skin"])
    cv.poly([(cx + 8, cy), (cx + 18, cy - 4), (cx + 10, cy + 3)], PAL["skin"])
    cv.line([(cx - 12, cy - 1), (cx - 16, cy - 3)], PAL["skin_shadow"], 1.0)
    cv.line([(cx + 12, cy - 1), (cx + 16, cy - 3)], PAL["skin_shadow"], 1.0)

    cv.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), PAL["outline"])
    cv.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), PAL["skin"])
    cv.rect((cx - 4, cy + 3, cx + 4, cy + 7), PAL["skin_shadow"])
    cv.rect((cx - 3, cy + 2, cx + 3, cy + 5), PAL["skin"])

    cv.poly(
        [(cx - 11, cy - 8), (cx - 3, cy - 13), (cx + 9, cy - 9), (cx + 8, cy - 3), (cx, cy - 7), (cx - 7, cy - 3)],
        PAL["outline"],
    )
    cv.poly([(cx - 10, cy - 8), (cx - 3, cy - 12), (cx + 8, cy - 8), (cx + 7, cy - 4), (cx, cy - 7), (cx - 6, cy - 3)], PAL["hair"])
    cv.poly([(cx - 2, cy - 12), (cx + 7, cy - 8), (cx + 2, cy - 7)], PAL["hair_light"])
    cv.poly([(cx - 8, cy - 4), (cx - 14, cy + 15), (cx - 7, cy + 14), (cx - 5, cy + 3)], PAL["hair_shadow"])
    cv.poly([(cx + 8, cy - 3), (cx + 14, cy + 16), (cx + 7, cy + 14), (cx + 5, cy + 3)], PAL["hair"])

    cv.rect((cx - 5, cy - 1, cx - 3, cy + 1), PAL["eye_dark"])
    cv.rect((cx + 3, cy - 1, cx + 5, cy + 1), PAL["eye_dark"])
    cv.rect((cx - 4, cy - 1, cx - 3, cy), PAL["eye"])
    cv.rect((cx + 4, cy - 1, cx + 5, cy), PAL["eye"])
    cv.rect((cx - 1, cy + 2, cx, cy + 2), PAL["skin_shadow"])
    cv.rect((cx - 2, cy + 5, cx + 2, cy + 5), PAL["outline2"])
    cv.rect((cx - 1, cy + 10, cx + 1, cy + 12), PAL["outline"])
    cv.ellipse((cx - 2, cy + 9, cx + 2, cy + 13), PAL["gem"])
    cv.rect((cx - 16, cy + 1, cx - 14, cy + 3), PAL["gold"])
    cv.rect((cx + 14, cy + 1, cx + 16, cy + 3), PAL["gold"])
    cv.rect((cx - 16, cy + 4, cx - 14, cy + 8), PAL["gem"])
    cv.rect((cx + 14, cy + 4, cx + 16, cy + 8), PAL["gem"])


def draw_left_body(cv: Canvas, bbox: tuple[int, int, int, int], pose: Pose) -> None:
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    baseline = y2 - 3 + pose.bob
    body_h = min(60, max(50, (y2 - y1) * 0.74)) * pose.body_scale
    cx = x1 + width * pose.cx_bias
    head_cy = baseline - body_h + 11
    shoulder_y = head_cy + 12
    waist_y = baseline - 30
    hem_y = baseline - 7

    cv.poly(
        [
            (cx - 5, head_cy - 7),
            (cx + 8, head_cy - 8),
            (x2 - 4, shoulder_y + 6),
            (x2 - 8, hem_y - 3),
            (cx + 4, hem_y - 8),
            (cx - 1, shoulder_y + 5),
        ],
        PAL["outline"],
    )
    cv.poly(
        [
            (cx - 4, head_cy - 6),
            (cx + 8, head_cy - 7),
            (x2 - 7, shoulder_y + 7),
            (x2 - 10, hem_y - 5),
            (cx + 5, hem_y - 10),
            (cx, shoulder_y + 5),
        ],
        PAL["hair_shadow"],
    )
    cv.poly([(cx + 2, head_cy - 3), (x2 - 9, shoulder_y + 10), (cx + 7, hem_y - 14), (cx + 3, shoulder_y + 4)], PAL["hair"])
    cv.poly([(cx + 4, head_cy - 8), (x2 - 16, shoulder_y + 7), (cx + 6, shoulder_y + 3)], PAL["hair_light"])

    draw_boots(cv, cx, baseline, pose.direction, pose.action)

    cv.poly(
        [(cx - 9, shoulder_y), (cx + 10, shoulder_y + 1), (cx + 14, hem_y), (cx + 3, baseline - 5), (cx - 10, hem_y)],
        PAL["outline"],
    )
    cv.poly(
        [(cx - 8, shoulder_y + 1), (cx + 8, shoulder_y + 2), (cx + 12, hem_y - 1), (cx + 2, baseline - 6), (cx - 8, hem_y - 1)],
        PAL["robe"],
    )
    cv.poly([(cx + 3, shoulder_y + 3), (cx + 12, hem_y - 2), (cx + 3, hem_y + 1), (cx, waist_y)], PAL["robe_shadow"])
    cv.poly([(cx - 5, shoulder_y + 3), (cx + 1, shoulder_y + 3), (cx + 3, hem_y - 8), (cx - 5, hem_y - 5)], PAL["undersuit"])
    cv.line([(cx - 8, shoulder_y + 3), (cx - 9, hem_y - 1)], PAL["gold"], 1.6)
    cv.line([(cx + 8, shoulder_y + 3), (cx + 11, hem_y - 1)], PAL["gold_dark"], 1.6)
    cv.rect((cx - 7, waist_y, cx + 8, waist_y + 2), PAL["outline"])
    cv.rect((cx - 6, waist_y, cx + 7, waist_y + 1), PAL["undersuit"])

    if pose.action in {"attack_windup", "attack_release"}:
        front_hand = (x1 + 7, waist_y - (8 if pose.action == "attack_release" else 4))
        rear_hand = (cx + 12, waist_y - 4)
    elif pose.action in {"skill_windup", "active_cast"}:
        front_hand = (cx - 10, waist_y - 10)
        rear_hand = (cx + 8, waist_y - 9)
    else:
        front_hand = (cx - 12, waist_y - 2)
        rear_hand = (cx + 10, waist_y - 4)
    cv.line([(cx - 7, shoulder_y + 4), front_hand], PAL["outline"], 6.0)
    cv.line([(cx + 7, shoulder_y + 4), rear_hand], PAL["outline"], 5.0)
    cv.line([(cx - 7, shoulder_y + 4), front_hand], PAL["robe"], 4.0)
    cv.line([(cx + 7, shoulder_y + 4), rear_hand], PAL["robe_shadow"], 3.5)
    for hand in (front_hand, rear_hand):
        cv.ellipse((hand[0] - 2, hand[1] - 2, hand[0] + 2, hand[1] + 2), PAL["outline"])
        cv.ellipse((hand[0] - 1.4, hand[1] - 1.4, hand[0] + 1.4, hand[1] + 1.4), PAL["skin"])

    draw_left_head(cv, cx - 1, head_cy)


def draw_left_head(cv: Canvas, cx: float, cy: float) -> None:
    cv.poly([(cx - 6, cy - 3), (cx - 20, cy - 6), (cx - 8, cy + 4)], PAL["outline"])
    cv.poly([(cx - 6, cy - 2), (cx - 17, cy - 5), (cx - 8, cy + 3)], PAL["skin"])
    cv.line([(cx - 11, cy - 2), (cx - 15, cy - 4)], PAL["skin_shadow"], 1.0)
    cv.ellipse((cx - 9, cy - 8, cx + 7, cy + 8), PAL["outline"])
    cv.ellipse((cx - 8, cy - 7, cx + 6, cy + 7), PAL["skin"])
    cv.poly([(cx - 10, cy - 1), (cx - 15, cy + 1), (cx - 8, cy + 3)], PAL["skin"])
    cv.rect((cx - 14, cy + 1, cx - 12, cy + 1), PAL["skin_shadow"])

    cv.poly([(cx - 10, cy - 8), (cx - 3, cy - 13), (cx + 9, cy - 8), (cx + 5, cy - 3), (cx - 4, cy - 6)], PAL["outline"])
    cv.poly([(cx - 9, cy - 8), (cx - 3, cy - 12), (cx + 8, cy - 7), (cx + 4, cy - 3), (cx - 4, cy - 6)], PAL["hair"])
    cv.poly([(cx - 6, cy - 3), (cx - 14, cy + 14), (cx - 7, cy + 13), (cx - 3, cy + 3)], PAL["hair_shadow"])
    cv.poly([(cx + 4, cy - 2), (cx + 11, cy + 15), (cx + 5, cy + 14), (cx + 2, cy + 3)], PAL["hair"])
    cv.rect((cx - 6, cy - 1, cx - 3, cy + 1), PAL["eye_dark"])
    cv.rect((cx - 5, cy - 1, cx - 4, cy), PAL["eye"])
    cv.rect((cx - 10, cy + 5, cx - 7, cy + 5), PAL["outline2"])
    cv.rect((cx - 16, cy + 2, cx - 14, cy + 4), PAL["gold"])
    cv.rect((cx - 16, cy + 5, cx - 14, cy + 9), PAL["gem"])
    cv.rect((cx - 1, cy + 10, cx + 1, cy + 12), PAL["gem"])


def draw_back_body(cv: Canvas, bbox: tuple[int, int, int, int], pose: Pose) -> None:
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    baseline = y2 - 3 + pose.bob
    body_h = min(60, max(50, (y2 - y1) * 0.73)) * pose.body_scale
    cx = x1 + width * pose.cx_bias
    head_cy = baseline - body_h + 11
    shoulder_y = head_cy + 12
    waist_y = baseline - 30
    hem_y = baseline - 7

    draw_boots(cv, cx, baseline, pose.direction, pose.action)
    cv.poly(
        [
            (cx - 10, head_cy - 8),
            (cx + 11, head_cy - 8),
            (cx + 18, shoulder_y + 5),
            (cx + 13, hem_y - 2),
            (cx + 3, hem_y + 2),
            (cx, shoulder_y + 8),
            (cx - 3, hem_y + 2),
            (cx - 14, hem_y - 2),
            (cx - 18, shoulder_y + 5),
        ],
        PAL["outline"],
    )
    cv.poly(
        [
            (cx - 9, head_cy - 7),
            (cx + 10, head_cy - 7),
            (cx + 16, shoulder_y + 6),
            (cx + 11, hem_y - 4),
            (cx + 2, hem_y),
            (cx, shoulder_y + 8),
            (cx - 2, hem_y),
            (cx - 12, hem_y - 4),
            (cx - 16, shoulder_y + 6),
        ],
        PAL["hair_shadow"],
    )
    cv.poly([(cx - 4, head_cy - 7), (cx + 7, head_cy - 6), (cx + 9, hem_y - 7), (cx + 1, hem_y - 1)], PAL["hair"])
    cv.poly([(cx - 8, head_cy - 5), (cx - 14, shoulder_y + 7), (cx - 9, hem_y - 7), (cx - 3, shoulder_y)], PAL["hair"])
    cv.poly([(cx - 2, head_cy - 12), (cx + 7, head_cy - 8), (cx + 2, head_cy - 5)], PAL["hair_light"])

    cv.poly([(cx - 14, shoulder_y), (cx + 14, shoulder_y), (cx + 20, hem_y), (cx + 8, baseline - 5), (cx, hem_y - 3), (cx - 8, baseline - 5), (cx - 20, hem_y)], PAL["outline"])
    cv.poly([(cx - 12, shoulder_y + 1), (cx + 12, shoulder_y + 1), (cx + 17, hem_y - 1), (cx + 7, baseline - 6), (cx, hem_y - 5), (cx - 7, baseline - 6), (cx - 17, hem_y - 1)], PAL["robe"])
    cv.poly([(cx + 7, shoulder_y + 3), (cx + 16, hem_y - 2), (cx + 8, hem_y + 1), (cx + 2, waist_y)], PAL["robe_shadow"])
    cv.line([(cx - 11, shoulder_y + 3), (cx - 16, hem_y - 1)], PAL["gold_dark"], 1.6)
    cv.line([(cx + 11, shoulder_y + 3), (cx + 16, hem_y - 1)], PAL["gold"], 1.6)
    cv.line([(cx - 14, hem_y - 1), (cx - 3, baseline - 5), (cx + 4, hem_y - 5), (cx + 15, hem_y - 1)], PAL["gold"], 1.3)
    cv.rect((cx - 8, waist_y, cx + 8, waist_y + 2), PAL["outline"])

    left_hand = (cx - 17, waist_y - (6 if pose.action == "attack_windup" else 1))
    right_hand = (cx + 17, waist_y - (8 if pose.action in {"attack_release", "active_cast"} else 3))
    if pose.action == "skill_windup":
        left_hand = (cx - 15, waist_y - 8)
        right_hand = (cx + 12, waist_y - 13)
    cv.line([(cx - 11, shoulder_y + 5), left_hand], PAL["outline"], 5.0)
    cv.line([(cx + 11, shoulder_y + 5), right_hand], PAL["outline"], 5.0)
    cv.line([(cx - 11, shoulder_y + 5), left_hand], PAL["robe"], 3.5)
    cv.line([(cx + 11, shoulder_y + 5), right_hand], PAL["robe_shadow"], 3.5)
    cv.ellipse((left_hand[0] - 2, left_hand[1] - 2, left_hand[0] + 2, left_hand[1] + 2), PAL["skin_shadow"])
    cv.ellipse((right_hand[0] - 2, right_hand[1] - 2, right_hand[0] + 2, right_hand[1] + 2), PAL["skin_shadow"])

    cv.ellipse((cx - 8, head_cy - 8, cx + 8, head_cy + 8), PAL["outline"])
    cv.ellipse((cx - 7, head_cy - 7, cx + 7, head_cy + 7), PAL["hair"])
    cv.poly([(cx - 8, head_cy - 3), (cx - 15, head_cy + 13), (cx - 7, head_cy + 14), (cx - 4, head_cy + 3)], PAL["hair_shadow"])
    cv.poly([(cx + 8, head_cy - 3), (cx + 15, head_cy + 13), (cx + 7, head_cy + 14), (cx + 4, head_cy + 3)], PAL["hair"])
    cv.line([(cx - 5, head_cy - 5), (cx + 4, head_cy - 8)], PAL["hair_light"], 1.2)


def draw_magic_frame(cv: Canvas, bbox: tuple[int, int, int, int], frame: int) -> None:
    x1, y1, x2, y2 = bbox
    cx = (x1 + x2) / 2
    top = y1 + 5
    bottom = y2 - 5
    width = x2 - x1
    phase = frame - 15
    offset = [-4, 0, 4][phase]

    cv.poly([(cx, y1), (x2 - 3, y1 + 25), (x2 - 9, y2 - 22), (cx, y2), (x1 + 6, y2 - 25), (x1 + 2, y1 + 28)], PAL["magic_dark"])
    cv.poly([(cx + offset, y1 + 4), (x2 - 8, y1 + 27), (x2 - 14, y2 - 26), (cx - offset, y2 - 7), (x1 + 12, y2 - 29), (x1 + 8, y1 + 31)], PAL["magic"])
    cv.poly([(cx + offset, y1 + 14), (x2 - 18, y1 + 36), (x2 - 21, y2 - 39), (cx, y2 - 17), (x1 + 21, y2 - 40), (x1 + 18, y1 + 40)], PAL["magic_light"])

    head_y = top + 23
    baseline = bottom - 7
    cv.poly([(cx - 6, head_y - 2), (cx - 20, head_y - 8), (cx - 7, head_y + 5)], PAL["white"])
    cv.poly([(cx + 6, head_y - 2), (cx + 20, head_y - 8), (cx + 7, head_y + 5)], PAL["white"])
    cv.ellipse((cx - 9, head_y - 10, cx + 9, head_y + 8), PAL["white"])
    cv.poly([(cx - 8, head_y + 5), (cx - 17, baseline - 7), (cx - 5, baseline - 2), (cx, head_y + 11), (cx + 5, baseline - 2), (cx + 17, baseline - 7), (cx + 8, head_y + 5)], PAL["white"])
    cv.poly([(cx - 14, head_y + 16), (cx + 14, head_y + 16), (cx + 22, baseline - 2), (cx + 7, baseline + 4), (cx, baseline - 3), (cx - 7, baseline + 4), (cx - 22, baseline - 2)], PAL["white"])
    staff_x = cx + width * 0.23
    cv.line([(staff_x - 3, bottom - 2), (staff_x + 3, top + 6)], PAL["white"], 2.5)
    cv.ellipse((staff_x - 5, top + 4, staff_x + 7, top + 16), PAL["white"])
    for sx, sy in ((x1 + 9, y1 + 37), (x2 - 15, y1 + 42), (x1 + 18, y2 - 31), (x2 - 22, y2 - 21)):
        cv.rect((sx - 1, sy - 4, sx + 1, sy + 4), PAL["white"])
        cv.rect((sx - 4, sy - 1, sx + 4, sy + 1), PAL["white"])


def draw_pose(board: Image.Image, constraints: list[dict[str, object]], frame: int) -> None:
    pose = POSES[frame]
    bbox = constraints[frame]["character_bbox"] if frame not in (15, 16, 17) else constraints[frame]["alpha_bbox"]
    if bbox is None:
        raise RuntimeError(f"frame {frame} has no geometry bbox")
    bbox = tuple(int(v) for v in bbox)  # type: ignore[arg-type]
    row, col = divmod(frame, COLS)
    cv = Canvas(board, col * MASTER_CELL_W, row * MASTER_CELL_H)

    if frame in (15, 16, 17):
        draw_magic_frame(cv, bbox, frame)
        return

    start, end = staff_endpoints(bbox, pose)
    draw_staff(cv, start, end)
    if pose.direction == "front":
        draw_front_body(cv, bbox, pose)
    elif pose.direction == "left":
        draw_left_body(cv, bbox, pose)
    elif pose.direction == "back":
        draw_back_body(cv, bbox, pose)
    else:
        raise ValueError(pose.direction)

    if pose.action in {"attack_release", "active_cast"}:
        hx, hy = end
        cv.rect((hx - 1, hy - 11, hx + 1, hy - 6), PAL["magic_light"])
        cv.rect((hx - 4, hy - 9, hx + 4, hy - 8), PAL["magic_light"])
        cv.rect((hx + 8, hy + 2, hx + 10, hy + 4), PAL["magic"])
        cv.rect((hx - 10, hy + 6, hx - 8, hy + 8), PAL["magic"])


def force_binary_alpha(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    alpha = image.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    image.putalpha(alpha)
    return image


def build_source_design(reference: Image.Image, constraints: list[dict[str, object]]) -> Image.Image:
    board = Image.new(
        "RGBA",
        (ATLAS_W * MASTER_SCALE, ATLAS_H * MASTER_SCALE),
        (0, 0, 0, 0),
    )
    for frame in range(FRAME_COUNT):
        draw_pose(board, constraints, frame)
    return force_binary_alpha(board)


def downsample_cell(master: Image.Image, frame: int) -> Image.Image:
    row, col = divmod(frame, COLS)
    crop = master.crop(
        (
            col * MASTER_CELL_W,
            row * MASTER_CELL_H,
            (col + 1) * MASTER_CELL_W,
            (row + 1) * MASTER_CELL_H,
        )
    )
    small = crop.resize((CELL_W, CELL_H), Image.Resampling.NEAREST).convert("RGBA")
    return force_binary_alpha(small)


def build_atlas(master: Image.Image) -> tuple[Image.Image, list[Image.Image]]:
    atlas = Image.new("RGBA", (ATLAS_W, ATLAS_H), (0, 0, 0, 0))
    frames: list[Image.Image] = []
    for frame in range(FRAME_COUNT):
        small = downsample_cell(master, frame)
        frames.append(small)
        row, col = divmod(frame, COLS)
        atlas.alpha_composite(small, (col * CELL_W, row * CELL_H))
    return force_binary_alpha(atlas), frames


def make_qa(frames: list[Image.Image], scale: int = 8) -> Image.Image:
    label_h = 18
    canvas = Image.new(
        "RGBA",
        (COLS * CELL_W * scale, ROWS * CELL_H * scale + label_h),
        (32, 34, 42, 255),
    )
    for index in range(20):
        row, col = divmod(index, COLS)
        x = col * CELL_W * scale
        y = row * CELL_H * scale + label_h
        if index < len(frames):
            scaled = frames[index].resize((CELL_W * scale, CELL_H * scale), Image.Resampling.NEAREST)
            canvas.alpha_composite(scaled, (x, y))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index in range(20):
        row, col = divmod(index, COLS)
        x = col * CELL_W * scale
        y = row * CELL_H * scale + label_h
        draw.rectangle((x, y, x + CELL_W * scale - 1, y + CELL_H * scale - 1), outline=(230, 80, 230, 255), width=2)
        draw.rectangle((x + 4, y + 4, x + 32, y + 18), fill=(0, 0, 0, 200))
        draw.text((x + 7, y + 5), f"{index:02d}", fill=(255, 255, 255, 255), font=font)
    draw.text((8, 3), "Frieren skin QA 8x - frames 5..9 are left-facing", fill=(255, 255, 255, 255), font=font)
    return canvas


def make_comparison(reference: Image.Image, atlas: Image.Image) -> Image.Image:
    scale = 3
    left = reference.resize((ATLAS_W * scale, ATLAS_H * scale), Image.Resampling.NEAREST)
    right = atlas.resize((ATLAS_W * scale, ATLAS_H * scale), Image.Resampling.NEAREST)
    gap = 24
    canvas = Image.new("RGBA", (left.width + right.width + gap, left.height + 26), (28, 30, 38, 255))
    canvas.alpha_composite(left, (0, 0))
    canvas.alpha_composite(right, (left.width + gap, 0))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((8, left.height + 6), "geometry reference only", fill=(255, 255, 255, 255), font=font)
    draw.text((left.width + gap + 8, left.height + 6), "new Frieren pixel-art skin", fill=(255, 255, 255, 255), font=font)
    return canvas


def make_portrait() -> Image.Image:
    source = Image.open(ILLUST_REFERENCE).convert("RGBA")
    side = min(source.width, source.height)
    x = (source.width - side) // 2
    y = (source.height - side) // 2
    return source.crop((x, y, x + side, y + side)).resize((1024, 1024), Image.Resampling.LANCZOS)


def write_animation_mapping(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "front": [0, 1, 2, 3, 4, 18],
                "left": [5, 6, 7, 8, 9, 5],
                "back": [10, 11, 12, 13, 14, 10],
                "tags": {
                    "Front_Base": [0, 1, 2, 3, 4],
                    "Left_Base": [5, 6, 7, 8, 9],
                    "Back_Base": [10, 11, 12, 13, 14],
                    "Magic": [15, 16, 17],
                    "Idle": [18],
                },
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    reference = Image.open(REFERENCE).convert("RGBA")
    constraints = source_bboxes(reference)
    master = build_source_design(reference, constraints)
    atlas, frames = build_atlas(master)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "frames").mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames):
        frame.save(OUT / "frames" / f"{index:02d}.png")

    master.save(FRIEREN_DIR / "Frieren_source_design.png")
    master.save(OUT / "Frieren_source_design.png")
    atlas.save(FRIEREN_DIR / "Unit_10570_03.png")
    atlas.save(OUT / "frieren_sprite_sheet_650x560.png")
    make_qa(frames).save(OUT / "frieren_QA_8x.png")
    make_comparison(reference, atlas).save(FRIEREN_DIR / "Unit_10570_03_comparison.png")
    make_portrait().save(FRIEREN_DIR / "Unit_Illust_10570_03.png")
    write_animation_mapping(OUT / "animation_mapping.json")

    for frame in range(FRAME_COUNT):
        bbox = constraints[frame]["character_bbox"] if frame not in (15, 16, 17) else constraints[frame]["alpha_bbox"]
        pose = POSES.get(frame)
        if pose and bbox:
            if frame in (15, 16, 17):
                start = end = None
            else:
                start, end = staff_endpoints(tuple(int(v) for v in bbox), pose)
            constraints[frame]["staff_start"] = start
            constraints[frame]["staff_end"] = end
    (OUT / "geometry_constraints.json").write_text(json.dumps(constraints, indent=2) + "\n")

    print(f"Wrote {FRIEREN_DIR / 'Frieren_source_design.png'}")
    print(f"Wrote {FRIEREN_DIR / 'Unit_10570_03.png'}")
    print(f"Wrote {FRIEREN_DIR / 'Unit_Illust_10570_03.png'}")
    print(f"Wrote {OUT / 'frames'}")
    print(f"Wrote {OUT / 'frieren_QA_8x.png'}")


if __name__ == "__main__":
    main()
