#!/usr/bin/env python3
"""Apply only the two Y-axis ruby braces to a copy of the original PXO."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
SOURCE_PXO = ROOT / "Frieren KGC Sprite.pxo"
OUT_PXO = ROOT / "Frieren KGC Sprite staff head.pxo"
OUT_NATIVE = ROOT / "Frieren_KGC_Sprite_staff_head_native.png"
OUT_PREVIEW = ROOT / "Frieren_KGC_Sprite_staff_head_preview8x.png"
OUT_DETAIL = ROOT / "Frieren_KGC_Sprite_staff_head_detail24x.png"

# The two Y braces stay in their original local positions around the ruby.
# Both lean down-right with the staff guide; the X-axis brace is deferred.
# The separate X-axis support toward the crescent is intentionally deferred.
Y_AXIS_RUBY_BRACES: dict[tuple[int, int], tuple[int, int, int, int]] = {
    (8, 7): (164, 126, 61, 255),
    (9, 8): (183, 143, 76, 255),
    (5, 15): (166, 128, 66, 255),
    (6, 16): (215, 180, 98, 255),
}


def load_pxo(path: Path) -> tuple[Image.Image, dict, list[str]]:
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read("data.json"))
        raw = archive.read("image_data/frames/1/layer_1")
        names = archive.namelist()
    return Image.frombytes("RGBA", (data["size_x"], data["size_y"]), raw), data, names


def save_pxo(image: Image.Image, names: list[str]) -> None:
    temp_dir = ROOT / ".frieren_staff_head_tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    try:
        with zipfile.ZipFile(SOURCE_PXO) as archive:
            archive.extractall(temp_dir)
        (temp_dir / "image_data/frames/1/layer_1").write_bytes(image.tobytes())
        image.resize((image.width * 8, image.height * 8), Image.Resampling.NEAREST).save(
            temp_dir / "preview.png"
        )
        with zipfile.ZipFile(OUT_PXO, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                path = temp_dir / name
                if path.is_file():
                    archive.write(path, name)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def save_detail(image: Image.Image) -> None:
    left, top, right, bottom = 4, 5, 19, 20
    scale = 24
    crop = image.crop((left, top, right, bottom)).resize(
        ((right - left) * scale, (bottom - top) * scale), Image.Resampling.NEAREST
    )
    canvas = Image.new("RGBA", crop.size, (38, 38, 38, 255))
    canvas.alpha_composite(crop)
    grid = ImageDraw.Draw(canvas)
    for x in range(0, canvas.width + 1, scale):
        grid.line((x, 0, x, canvas.height), fill=(110, 110, 110, 255))
    for y in range(0, canvas.height + 1, scale):
        grid.line((0, y, canvas.width, y), fill=(110, 110, 110, 255))
    canvas.save(OUT_DETAIL)


def main() -> None:
    source, data, names = load_pxo(SOURCE_PXO)
    fixed = source.copy()
    pixels = fixed.load()
    for position, color in Y_AXIS_RUBY_BRACES.items():
        pixels[position] = color

    changed = {
        (x, y)
        for y in range(source.height)
        for x in range(source.width)
        if source.getpixel((x, y)) != fixed.getpixel((x, y))
    }
    assert changed == {(8, 7), (5, 15), (6, 16)}
    assert (data["size_x"], data["size_y"]) == fixed.size == (60, 76)
    assert all(alpha in (0, 255) for *_, alpha in fixed.getdata())

    fixed.save(OUT_NATIVE)
    fixed.resize((fixed.width * 8, fixed.height * 8), Image.Resampling.NEAREST).save(OUT_PREVIEW)
    save_detail(fixed)
    save_pxo(fixed, names)
    print(f"changed_pixels={len(changed)}")
    print("changed_coordinates=" + ",".join(f"{x}:{y}" for x, y in sorted(changed)))


if __name__ == "__main__":
    main()
