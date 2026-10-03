"""Write the product's tab icons from its mark (P1, owner 2026-10-02).

    manage.py build_favicons [--source assets/brand/mark.png] [--out frontend/public/brand]

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

    def handle(self, *args, **options):
        from PIL import Image

        source = Path(options["source"])
        if not source.is_file():
            raise CommandError(f"No mark at {source}.")
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
