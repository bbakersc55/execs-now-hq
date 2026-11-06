# Execs NOW HQ brand files

The approved logo sheet is `source/enhq-logo-standard.jpeg`, and its reversed
version is `source/enhq-logo-reversed.jpeg` (2026-11-05). Everything below is
an exact vector rebuild of them in Montserrat ExtraBold, with the text
converted to paths, so no file needs the font installed.

`scripts/brand/build_brand.py` builds every file. It records each measurement
taken from the sheet, and running it again rewrites all of them.
`contact-sheet.png` shows every file on one page.

## Colors

| | Hex | Used for |
|---|---|---|
| Dark blue | `#0D2C54` | "Execs", the square (standard), HQ (reversed) |
| Orange | `#E87722` | "NOW", the Q's tail |
| White | `#FFFFFF` | HQ (standard), the wordmark and the square (reversed) |

These are the logo's colors. The app's own interface still uses its older
palette (`config/branding.py`, `#0A3A65` and `#F58220`). Changing that palette
is a separate decision.

## Pieces

- **The square mark** (`mark`): HQ in a square. The Q's tail is a straight
  bar at 45°, 0.284 of the square's side long and 0.079 thick. It starts just
  inside the bowl and leaves it at the lower right.
- **The two-line lockup** (`stacked`): Execs over NOW, with both lines the
  same width. The square sits at the right at the two lines' height: its top
  is on Execs' cap line and its bottom on NOW's baseline.
- **The one-line lockup** (`line`): Execs NOW, followed by the square. The HQ
  inside the square has the same cap height as the words and sits on the same
  baseline.

## Colorways

| Name | Looks like | Use it on |
|---|---|---|
| `standard` | Dark blue Execs, orange NOW, dark blue square, white HQ, orange tail | White or light backgrounds |
| `reversed` | White Execs, orange NOW, white square, dark blue HQ, orange tail | Dark blue or dark backgrounds |
| `blue` | All dark blue; HQ and the tail cut out of the square | Light backgrounds, one color |
| `white` | All white; HQ and the tail cut out of the square | Dark blue, dark or orange backgrounds, one color |

## Clear space

Leave **half the square's width** clear on every side of any piece. Keep text,
edges and other marks out of that space. For example, a lockup whose square is
40 px tall needs 20 px clear all round.

## Which file goes where

Everything is in `frontend/public/brand/`, which is served at `/static/brand/`.

| Need | File |
|---|---|
| Print, signage, a designer, anything that scales | `svg/enhq-<piece>-<colorway>.svg` (transparent; the vector master) |
| A slide, a document, a web page you don't control | `png/enhq-<piece>-<colorway>-transparent-<512\|2048>.png` (trimmed to the artwork) |
| A ready-made tile on a background, with the clear space included | `png/enhq-<piece>-<colorway>-<white\|blue\|orange>-<512\|2048>.png` |
| A browser tab | `favicon.ico` (16, 32 and 48 px inside), `favicon-16.png`, `favicon-32.png`, `favicon-48.png` |
| An iPhone home screen | `apple-touch-icon.png` (180 px) |
| An Android home screen or an installed app | `icon-192.png` and `icon-512.png`, named in `site.webmanifest` |

Use 512 px on screen and 2048 px for print or for large screens. The icons are
the standard mark, square with no rounding: the platform rounds them where it
wants to.

Each colorway's background PNGs come only on the backgrounds it is meant for:

| Colorway | Background PNGs |
|---|---|
| standard | white |
| reversed | dark blue |
| blue | white |
| white | dark blue and orange |

Any other pairing would hide part of the logo. For example, the standard dark
blue square disappears on dark blue, and an orange NOW disappears on orange.

## Where the app uses them

Each of these surfaces names the product, so it carries the product's artwork:

- **The tab icon and web manifest:** staff pages, the Practices area, and the
  sign-in page when no practice is named (`config/spa.py`).
- **The sign-in page header:** the two-line lockup, standard colorway
  (`frontend/src/components/SignedOut.tsx`). It appears only when no practice
  is named. When a sign-in page opens from a practice's emailed link, it keeps
  that practice's name.
- **The Practices area header:** the one-line lockup, reversed colorway, on
  the dark blue sidebar and the phone's top bar. When the sidebar is
  collapsed, it shows the reversed mark (`frontend/src/App.tsx`,
  `ProductLockup`).
- **Email the platform sends to practices:** invitations, receipts, failed
  charges and the feedback notice. The header is the one-line lockup,
  standard colorway, 160 px wide (`apps/platform/mail.py`,
  `apps/crm/services/email_layout.py`).

Nothing else changes. Client-facing and practice-branded surfaces (the portal,
a practice's own mail, PDFs and token pages) keep the practice's own brand
and never show these files.

## Rebuilding

```
.venv/bin/python scripts/brand/build_brand.py
```

It needs the dev requirements (`skia-pathops`, `uharfbuzz`), Node and Google
Chrome: the PNGs are Chrome's renderings of the SVGs. The font and its license
are in `source/fonts/` (SIL Open Font License).
