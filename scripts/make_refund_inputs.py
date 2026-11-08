"""Draw the two prepared input images for the "I want a refund!" task.

- receipt.jpg: a photo-style shot of a till receipt from a fictional café,
  lying slightly rotated on a wooden table.
- food_with_bite.jpg: an illustrated cookie with a bite taken out, on a plate.
  This one is a stand-in — replace it with a real photo of bitten food for a
  more convincing exercise (same file name, or update tasks.json).

All names and numbers are made up. Run from the repo root:

    uv run python scripts/make_refund_inputs.py
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = Path("assets/input_images/refund")
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
MONO = FONT_DIR / "DejaVuSansMono.ttf"
MONO_BOLD = FONT_DIR / "DejaVuSansMono-Bold.ttf"

rng = random.Random(42)


def _wood_table(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, (150, 104, 66))
    d = ImageDraw.Draw(img)
    y = 0
    while y < h:  # planks with grain streaks
        plank_h = rng.randint(140, 220)
        base = rng.randint(-14, 14)
        for yy in range(y, min(h, y + plank_h)):
            shade = base + rng.randint(-6, 6)
            d.line([(0, yy), (w, yy)], fill=(150 + shade, 104 + shade, 66 + shade // 2))
        d.line([(0, y), (w, y)], fill=(95, 62, 38), width=3)
        y += plank_h
    return img.filter(ImageFilter.GaussianBlur(1.2))


def _add_noise(img: Image.Image, amount: int = 8) -> Image.Image:
    noise = Image.effect_noise(img.size, amount).convert("RGB")
    return Image.blend(img, noise, 0.06)


def make_receipt(path: Path) -> None:
    lines = [
        ("BYTE & BISCUIT CAFE", "bold_c"),
        ("Musterstrasse 12", "c"),
        ("8000 Zurich", "c"),
        ("Tel 044 000 00 00", "c"),
        ("", ""),
        ("Date 07.11.2026      12:34", ""),
        ("Table 7         Receipt 0815", ""),
        ("-" * 28, ""),
        ("1 Cappuccino          4.80", ""),
        ("1 Croissant           3.50", ""),
        ("1 Avocado toast      14.90", ""),
        ("1 Orange juice        5.20", ""),
        ("-" * 28, ""),
        ("TOTAL CHF            28.40", "bold"),
        ("", ""),
        ("incl. VAT 8.1%        2.13", ""),
        ("Paid by card         28.40", ""),
        ("", ""),
        ("Thank you for your visit!", "c"),
        ("No refunds without receipt", "c"),
    ]
    font = ImageFont.truetype(str(MONO), 34)
    bold = ImageFont.truetype(str(MONO_BOLD), 36)
    paper_w, line_h = 620, 50
    paper_h = 120 + line_h * len(lines) + 80
    paper = Image.new("RGB", (paper_w, paper_h), (246, 244, 236))
    d = ImageDraw.Draw(paper)
    y = 70
    for text, style in lines:
        f = bold if "bold" in style else font
        tw = d.textlength(text, font=f)
        x = (paper_w - tw) / 2 if style.endswith("c") else 40
        ink = 40 + rng.randint(0, 25)  # uneven thermal print
        d.text((x, y), text, font=f, fill=(ink, ink, ink + 5))
        y += line_h
    # torn bottom edge
    edge = [(0, paper_h)] + [
        (x, paper_h - rng.randint(0, 14)) for x in range(0, paper_w + 20, 20)
    ]
    d.polygon(edge + [(paper_w, paper_h + 20), (0, paper_h + 20)], fill=(0, 0, 0))
    mask = Image.new("L", paper.size, 255)
    ImageDraw.Draw(mask).polygon(
        edge + [(paper_w, paper_h + 20), (0, paper_h + 20)], fill=0
    )
    paper = _add_noise(paper.filter(ImageFilter.GaussianBlur(0.6)), 10)

    scene = _wood_table((1200, 1600))
    rot = paper.rotate(-4, expand=True, resample=Image.Resampling.BICUBIC)
    rot_mask = mask.rotate(-4, expand=True, resample=Image.Resampling.BICUBIC)
    shadow = Image.new("RGB", rot.size, (40, 26, 16))
    pos = ((scene.width - rot.width) // 2, (scene.height - rot.height) // 2)
    scene.paste(
        shadow,
        (pos[0] + 14, pos[1] + 18),
        rot_mask.filter(ImageFilter.GaussianBlur(12)),
    )
    scene.paste(rot, pos, rot_mask)
    _finish(scene).save(path, "JPEG", quality=88)


def make_food(path: Path) -> None:
    scene = _wood_table((1400, 1050))
    d = ImageDraw.Draw(scene)
    cx, cy = 700, 525
    # plate
    d.ellipse([cx - 460, cy - 400, cx + 460, cy + 400], fill=(70, 46, 30))  # shadow
    d.ellipse([cx - 450, cy - 420, cx + 450, cy + 380], fill=(238, 238, 234))
    d.ellipse([cx - 360, cy - 340, cx + 360, cy + 300], fill=(248, 248, 245))
    # cookie
    r = 260
    cookie = Image.new("RGBA", scene.size, (0, 0, 0, 0))
    cd = ImageDraw.Draw(cookie)
    cd.ellipse([cx - r, cy - r - 20, cx + r, cy + r - 20], fill=(196, 140, 72, 255))
    for _ in range(900):  # baked texture
        x, y = rng.randint(cx - r, cx + r), rng.randint(cy - r - 20, cy + r - 20)
        if (x - cx) ** 2 + (y - cy + 20) ** 2 < (r - 6) ** 2:
            c = rng.randint(-30, 20)
            cd.point((x, y), fill=(196 + c, 140 + c, 72 + c // 2, 255))
    for _ in range(16):  # chocolate chips
        x, y = rng.randint(cx - 200, cx + 200), rng.randint(cy - 220, cy + 180)
        if (x - cx) ** 2 + (y - cy + 20) ** 2 < (r - 40) ** 2:
            s = rng.randint(14, 26)
            cd.ellipse([x - s, y - s, x + s, y + s // 1.4], fill=(70, 38, 20, 255))
    # the bite: overlapping circles cut out of the upper right
    for bx, by, br in (
        (cx + 210, cy - 200, 95),
        (cx + 270, cy - 110, 85),
        (cx + 140, cy - 260, 80),
    ):
        cd.ellipse([bx - br, by - br, bx + br, by + br], fill=(0, 0, 0, 0))
    cookie = cookie.filter(ImageFilter.GaussianBlur(1.5))
    shadow = Image.new("RGBA", scene.size, (0, 0, 0, 0))
    shadow.paste((90, 90, 90, 110), (12, 16), cookie.split()[3])
    scene = Image.alpha_composite(
        scene.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(14))
    )
    scene = Image.alpha_composite(scene, cookie)
    # crumbs
    d = ImageDraw.Draw(scene)
    for _ in range(25):
        x, y = rng.randint(cx + 150, cx + 380), rng.randint(cy - 300, cy - 60)
        s = rng.randint(3, 9)
        d.ellipse([x - s, y - s, x + s, y + s], fill=(186, 130, 64, 255))
    _finish(scene.convert("RGB")).save(path, "JPEG", quality=88)


def _finish(img: Image.Image) -> Image.Image:
    """Mild vignette + noise so it reads more like a phone photo."""
    w, h = img.size
    vignette = Image.new("L", (w, h), 0)
    ImageDraw.Draw(vignette).ellipse([-w * 0.2, -h * 0.2, w * 1.2, h * 1.2], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(min(w, h) // 6))
    dark = Image.new("RGB", (w, h), (20, 14, 10))
    return _add_noise(Image.composite(img, dark, vignette), 12)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    make_receipt(OUT_DIR / "receipt.jpg")
    make_food(OUT_DIR / "food_with_bite.jpg")
    print(f"Wrote {OUT_DIR / 'receipt.jpg'} and {OUT_DIR / 'food_with_bite.jpg'}")


if __name__ == "__main__":
    main()
