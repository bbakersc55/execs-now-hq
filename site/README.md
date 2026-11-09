# The Execs NOW HQ marketing site

Astro with Tailwind, static output, served by `server.mjs` (Node, no
dependencies) on the Railway service **enhq-site** in the production project:
deploys from `main`, root directory `site/`, watch paths `site/**`.
Canonical address `https://www.execsnowhq.com`.

```
cd site
npm ci
npm run dev              # http://localhost:5300, the pages only (no /api/lead)
npm run build            # dist/
npm run check            # links, assets, meta tags, GA switch, vocabulary
PORT=4390 npm start      # dist/ as Railway serves it, with /api/lead
```

## Variables (Railway, enhq-site)

| Name | What | When it's read |
|---|---|---|
| `PUBLIC_GA4_ID` | GA4 measurement id. Unset: no analytics script at all. | At build |
| `SITE_LEAD_TOKEN` | The shared secret for the app's `POST /api/public/leads`. Same value on the app's web service. | At run |
| `LEAD_FORWARD_URL` | Optional. Defaults to `https://app.getexecutivesnow.com/api/public/leads`. | At run |

## How things fit

- **The demo form** posts to `/api/lead` on this server, which forwards it to
  the app with `X-Site-Lead-Token` and the visitor's IP (`X-Lead-Client-IP`).
  The secret never reaches the browser. Without JavaScript the form still
  works: the server answers with a redirect to `/demo/thanks` or `/demo/error`.
- **Screenshots** are in `public/shots/`: each name as `.png`/`.webp` at
  2880 px, `-1440` and `-720` sizes. Captured from a scratch copy of the
  fictional demo practice. The frame and the floating detail card are CSS
  (`src/components/Shot.astro`); the card's words are in `src/data/shots.ts`.
- **Video slots** for sections 03 to 06: `VIDEO_SLOTS` in
  `src/data/shots.ts`. Put a silent MP4 in `public/video/` and its path there;
  the screenshot becomes its poster.
- **The headshot**: `public/about/bryan-a` and `bryan-b`, two square crops
  (`scripts/make_images.py`). `HEADSHOT` in `src/config.ts` picks one.
- **Privacy and terms** are drafts for review: `LEGAL_DRAFT` in
  `src/config.ts` shows a draft notice, keeps them out of the sitemap and
  marks them noindex. Set it to `false`, with `LEGAL_EFFECTIVE`, once approved.
