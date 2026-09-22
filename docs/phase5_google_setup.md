# Phase 5 — what to set up on the Google side

Everything below is in the **Execs NOW HQ** GCP project, the same one the
nightly backup bucket lives in. It is separate from anything else you run.

## 1. Turn on the Drive API

APIs & Services → Library → **Google Drive API** → Enable. Nothing else needs
enabling; the app reads one folder and never writes.

## 2. Add the Drive scope to the consent screen

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
Drive no matter what the code asks for. Disconnect and reconnect the Google
account on **Email settings** once, after this ships. The consent screen will
list Drive alongside Gmail; approving it is what makes the folder readable.

If you would rather see the scopes before agreeing, the authorisation URL the
app builds carries them in its `scope=` parameter.

## 4. Get the folder id

Open the Gemini notes folder in Drive. The URL ends in the id:

```
https://drive.google.com/drive/folders/1AbCdEfGh...   ← everything after /folders/
```

Paste that into the meeting queue's connect box. **One folder per tenant in
Beta** — the schema enforces it.

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
