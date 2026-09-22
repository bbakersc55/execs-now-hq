# Phase 5 — what to set up on the Google side

Everything below is in the **Execs NOW HQ** GCP project, the same one the
nightly backup bucket lives in. It is separate from anything else you run.

## 1. Turn on the Drive API

APIs & Services → Library → **Google Drive API** → Enable. Nothing else needs
enabling; the app reads one folder and never writes.

## 2. Add the Drive scope to the consent screen

*(You do steps 2–4 from the app itself — the **meeting queue** screen has a
"Connect your notes folder" panel that runs the consent and takes the folder.
This section is what has to be true on the Google side for it to work.)*

The OAuth client already exists — it is the one Module 1 uses to send mail.
Meeting ingestion adds **one scope** to it:

```
https://www.googleapis.com/auth/drive.readonly
```

**It is asked for separately from the Gmail scopes**, not folded into them: a
practice that never turns meeting ingestion on should never be asked for its
Drive. In the code that is `gmail_oauth.scopes_for(drive=True)`, and the
consent screen is where it has to be declared as well — APIs & Services →
OAuth consent screen → Scopes → **Add or remove scopes** → paste the scope
above → Update → Save.

**`drive.readonly` is a restricted scope.** On the **Internal** consent screen
Beta runs on (assumption C1) that costs nothing: internal apps need no
verification and have no refresh-token expiry. It matters at V1, when the app
moves to **External** and `gmail.send`, `gmail.readonly` and now
`drive.readonly` all require Google verification with a **CASA security
assessment** — already the longest lead time in the V1 plan
(`04_build_plan.md`, Phase 8+). Adding Drive does not lengthen that assessment,
but it does add a third restricted scope to justify in it, so the justification
is worth writing while the reason is fresh: *the app reads one folder of the
practice's own meeting notes, nominated by the practice, and never writes.*

## 3. Re-consent once

An existing connection was granted without the Drive scope, so it cannot read
Drive no matter what the code asks for.

**Do this from the meeting queue**, not from Email settings: step one of
"Connect your notes folder" is an **Allow Drive access** button that sends you
to Google and brings you back to the same screen. It asks for the Gmail scopes
again at the same time, so **sending mail is re-granted, not replaced** — you
will not lose the ability to send halfway through.

Google lets you untick a scope on that screen. If you untick Drive, the app
says so plainly and keeps the mail connection working; it does not pretend
nothing was stored.

If you would rather see the scopes before agreeing, the authorisation URL the
app builds carries them in its `scope=` parameter.

## 4. Get the folder id

Open the Gemini notes folder in Drive. The URL ends in the id:

```
https://drive.google.com/drive/folders/1AbCdEfGh...   ← everything after /folders/
```

Paste **the whole address** into step two of the connect panel — the app takes
the id out of it, `?usp=sharing` and all. The id on its own works too.

It then opens the folder and tells you its name, how many files are in it and
how many of those it can read, **before** it saves anything. Confirm, and it
starts watching. **One folder per tenant in Beta** — the schema enforces it.

Only the founder fractional can connect or disconnect the folder (matrix
11.10). A CF or VA sees which folder is watched and when it was last read, and
no connect controls.

## 5. What the app will and will not do with it

- It calls `changes.list` from a stored cursor every ten minutes, and on
  "Sync now".
- It reads **Google Docs, `.txt` and `.docx`** in that folder, exporting each
  as text. A PDF, a video or a Google Sheet is **recorded and skipped with a
  reason on the screen** — never silently ignored.
- It **never writes to Drive**, never moves or renames a file, and never
  deletes one. `drive.readonly` is not merely what we ask for; it is all the
  app can do.
- The owner of each file is captured at ingestion, because who owned the
  document decides who may read the proposal (matrix §11).

## 6. If you would rather not grant Drive at all

Nothing else in the product depends on it. Leaving the scope ungranted leaves
the meeting queue empty and every other module exactly as it is — the folder is
simply never connected, and the health screen says so rather than failing.
