"""Write the product's tab icons from its mark (P1, owner 2026-10-02).

    manage.py build_favicons [--source assets/brand/mark.png] [--out frontend/public/brand]
    manage.py build_favicons --derive    # first write assets/brand/mark-transparent.png

`--derive` makes the owner's mark (supplied on opaque white, with wide
margins) into a transparent, trimmed, square file beside the original, and
builds the icons from that (owner, 2026-10-02: keep the original). Only the
white connected to the image's edge becomes transparent, so white inside the
mark stays white and the gray bars stay solid; the edge pixels between the
two are made partly transparent so the curve stays smooth on a dark tab bar.

Writes `favicon.ico` (16, 32 and 48 px inside), `favicon-32.png`,
`apple-touch-icon.png` (180), `icon-192.png` and `icon-512.png`. The outputs
are committed, so a build never needs the source. Staff pages link them
(config/spa.py); clients never see them (they get their practice's mark).

The source must be a square PNG. One within 2% of square (the owner's is
467 x 469) is centered on a square canvas of its own corner color, and the
command says so. Every size is a reduction of it except the
512, which may be enlarged from a smaller source (the owner's mark is 464 px;
owner, 2026-10-02: use it as is and upscale the 512 only). Anything smaller
than 192 px is refused: it would mean enlarging the icons people actually see.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

PNG_SIZES = {"favicon-32.png": 32, "apple-touch-icon.png": 180,
             "icon-192.png": 192, "icon-512.png": 512}
ICO_SIZES = [(16, 16), (32, 32), (48, 48)]
#: How far from square a source may be and still be padded rather than refused.
SQUARE_TOLERANCE = 0.02
#: The only output that may be larger than the source.
MAY_ENLARGE = {"icon-512.png"}
MIN_SOURCE = 192


class Command(BaseCommand):
    help = "Write the product's favicon set from its square mark."

    def add_arguments(self, parser):
        parser.add_argument("--source", default=str(settings.BASE_DIR / "assets/brand/mark.png"))
        parser.add_argument("--out", default=str(settings.BASE_DIR / "frontend/public/brand"))
        parser.add_argument("--derive", action="store_true",
                            help="Write mark-transparent.png beside the source and build from it")

    def handle(self, *args, **options):
        from PIL import Image

        source = Path(options["source"])
        if not source.is_file():
            raise CommandError(f"No mark at {source}.")
        if options["derive"]:
            derived = source.with_name(f"{source.stem}-transparent.png")
            derive_transparent(source, derived)
            self.stdout.write(f"  {derived.name:<22} transparent, trimmed, square "
                              f"(from {source.name}, which is unchanged)")
            source = derived
        with Image.open(source) as opened:
            if opened.format != "PNG":
                raise CommandError(f"{source.name} is {opened.format}; use a PNG.")
            image = opened.convert("RGBA")
        width, height = image.size
        if width != height:
            if abs(width - height) > SQUARE_TOLERANCE * max(width, height):
                raise CommandError(
                    f"The mark must be square; {source.name} is {width} x {height}.")
            side = max(width, height)
            canvas = Image.new("RGBA", (side, side), image.getpixel((0, 0)))
            canvas.paste(image, ((side - width) // 2, (side - height) // 2))
            self.stdout.write(f"  {source.name} is {width} x {height}: centered on a "
                              f"{side} x {side} square of its corner color.")
            image, width, height = canvas, side, side
        if width < MIN_SOURCE:
            raise CommandError(f"The mark is {width} px; at least {MIN_SOURCE} is needed.")

        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)
        for name, size in PNG_SIZES.items():
            if size > width and name not in MAY_ENLARGE:
                raise CommandError(f"{name} would be enlarged from {width} px.")
            image.resize((size, size), Image.LANCZOS).save(out / name, "PNG", optimize=True)
            note = " (enlarged)" if size > width else ""
            self.stdout.write(f"  {name:<22} {size} x {size}{note}")
        image.save(out / "favicon.ico", sizes=ICO_SIZES)
        self.stdout.write(f"  {'favicon.ico':<22} 16, 32, 48")
        self.stdout.write(f"Done: {out} from {source.name} ({width} x {height}).")


#: A pixel this close to white, connected to the edge, is background.
WHITE_FLOOR = 235
#: Margin left around the artwork after trimming, as a share of its size.
TRIM_MARGIN = 0.04


def derive_transparent(source: Path, out: Path) -> None:
    """The mark without its white background or margins, on a square canvas."""
    from PIL import Image, ImageDraw, ImageFilter

    image = Image.open(source).convert("RGBA")
    width, height = image.size
    pixels = image.load()

    # 1. Background: the near-white region connected to the edge.
    mask = Image.new("L", image.size, 0)
    near_white = mask.load()
    for y in range(height):
        for x in range(width):
            r, g, b, _ = pixels[x, y]
            if min(r, g, b) >= WHITE_FLOOR:
                near_white[x, y] = 255
    for x in range(width):
        for y in (0, height - 1):
            if near_white[x, y] == 255:
                ImageDraw.floodfill(mask, (x, y), 128)
    for y in range(height):
        for x in (0, width - 1):
            if near_white[x, y] == 255:
                ImageDraw.floodfill(mask, (x, y), 128)
    background = mask.point(lambda v: 255 if v == 128 else 0)

    # 2. The fringe beside the background: un-mix it from white, so the
    #    anti-aliased edge keeps its shape with no white halo.
    fringe = background.filter(ImageFilter.MaxFilter(5))
    bg, ring = background.load(), fringe.load()
    for y in range(height):
        for x in range(width):
            r, g, b, _ = pixels[x, y]
            if bg[x, y]:
                pixels[x, y] = (255, 255, 255, 0)
            elif ring[x, y]:
                alpha = max(255 - r, 255 - g, 255 - b) / 255
                if alpha <= 0:
                    pixels[x, y] = (255, 255, 255, 0)
                else:
                    unmix = [round((c - 255 * (1 - alpha)) / alpha) for c in (r, g, b)]
                    pixels[x, y] = (*[max(0, min(255, c)) for c in unmix], round(alpha * 255))

    # 3. Trim to the artwork, keep a small margin, and center it on a square.
    box = image.getchannel("A").getbbox()
    if box is None:
        raise CommandError("The mark is entirely background.")
    art = image.crop(box)
    side = round(max(art.size) * (1 + 2 * TRIM_MARGIN))
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    canvas.paste(art, ((side - art.width) // 2, (side - art.height) // 2))
    canvas.save(out, "PNG", optimize=True)
