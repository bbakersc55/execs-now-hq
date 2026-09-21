# Inter, vendored

`InterVariable.woff2` — Inter v4.0, the variable face, from
https://github.com/rsms/inter/releases (SIL Open Font License 1.1, copied
beside it as `Inter-LICENSE.txt`).

**Vendored rather than linked to Google Fonts**, on the owner's ruling of
2026-09-21. The app runs on a laptop during Beta and is demonstrated on other
people's wifi; a `<link>` to fonts.googleapis.com falls back silently to system
fonts exactly when it matters most, and nothing in the screen tells you it has.
Served by Vite in development and from the built bundle in production, so it
works with no internet at all.

One file: the variable face covers every weight the design uses (400–700)
without a request per weight.
