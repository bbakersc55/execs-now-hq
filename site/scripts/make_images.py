"""Builds the site's derived images. Run from the repo root:

    .venv/bin/python site/scripts/make_images.py

- the two square headshot crops for /about (800 px, JPEG and WebP), from
  docs/brand/source/Bryan.jpg; "a" is head and shoulders, "b" is tighter.
  /about shows "a" until Bryan picks (site/src/config.ts, HEADSHOT);
- the Open Graph image: the one-line lockup, reversed, on dark blue, 1200x630.
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "site" / "public"
NAVY = (0x0D, 0x2C, 0x54)

# Measured on the 4032x2268 original: the head's center is at x 1904,
# y 661 (crown 224, chin 1098). Each crop is (left, top, side).
CROPS = {"a": (1054, 49, 1700), "b": (1279, 136, 1250)}


def headshots():
    src = Image.open(ROOT / "docs/brand/source/Bryan.jpg").convert("RGB")
    for name, (left, top, side) in CROPS.items():
        im = src.crop((left, top, left + side, top + side)).resize((800, 800), Image.LANCZOS)
        im.save(OUT / "about" / f"bryan-{name}.jpg", quality=84, optimize=True, progressive=True)
        im.save(OUT / "about" / f"bryan-{name}.webp", quality=82, method=6)


def og_image():
    logo = Image.open(ROOT / "frontend/public/brand/png/enhq-line-reversed-transparent-2048.png")
    width = 760
    logo = logo.resize((width, round(logo.height * width / logo.width)), Image.LANCZOS)
    card = Image.new("RGB", (1200, 630), NAVY)
    card.paste(logo, ((1200 - logo.width) // 2, (630 - logo.height) // 2), logo)
    card.save(OUT / "og.png", optimize=True)


if __name__ == "__main__":
    headshots()
    og_image()
