# Phase 6 — what to set up on the Google side

One scope, on the OAuth client you already have, in the **Execs NOW HQ** GCP
project. Read §3 before you grant it.

## 1. Add the scope to the consent screen

APIs & Services → OAuth consent screen → Scopes → **Add or remove scopes**:

```
https://www.googleapis.com/auth/gmail.readonly
```

The Gmail API is already enabled (Module 1 sends through it), so there is
nothing else to turn on.

## 2. Re-consent, from Email settings

The app asks for this scope **only when you tick the box**, so an existing
connection does not have it. On **Settings → Email**, reconnect with *"also
collect replies"* ticked. The Gmail scopes are requested again at the same
time, so **sending is re-granted, not replaced** — you will not lose the
ability to send halfway through.

If you untick the read box on Google's screen, the app says so and keeps the
send half working. It does not claim nothing was stored.

## 3. What you are actually granting — read this part

`gmail.readonly` is **a read over your entire mailbox**. Google has no narrower
grant: there is no "only the threads this app started" scope to ask for.

**The app reads only threads it started.** It works from `gmail_thread_id`
values it stored itself when it sent, and asks Gmail for those and nothing
else. That boundary is in `GmailReader` — in our code — and **not enforced by
Google**. It is worth knowing which of the two is true:

| | Enforced by |
|---|---|
| The app *can* read your whole mailbox | nothing — the grant allows it |
| The app *does* read only its own threads | the app's code, and its tests |

If that is not a trade you want, the module simply stays off: leave the box
unticked and everything else works exactly as it does now. Replies then live
only in Gmail, which is where they live today.

Under the **Internal** consent screen Beta runs on, the scope costs nothing in
verification — no CASA assessment, no refresh-token expiry. **The bill arrives
at V1**, when the app goes External and `gmail.send`, `gmail.settings.basic`,
`drive.readonly` and now `gmail.readonly` all need a security assessment. This
does not lengthen that assessment; it adds a fourth scope to justify in it, and
the justification is the table above.

## 4. Nothing else

- **No webhook, no public endpoint, no DNS.** Inbound arrives by polling, so
  Module 6 runs on the laptop and the Railway move verifies nothing about it
  beyond continuing to work.
- **No inbound domain and no `reply+<token>@` address.** The thread token rides
  in the `Message-ID` and in `X-ExecsNowHQ-Thread`, which is what a reply
  quotes back.
- **Nothing to forge.** With polling there is no endpoint to post to;
  authenticity comes from reading your own mailbox over an authenticated
  Google call.

## 5. Turning it off

Disconnect and reconnect Gmail with the box unticked, or revoke the app at
[myaccount.google.com/permissions](https://myaccount.google.com/permissions)
and reconnect. Replies already collected stay on the contacts' records —
they are the practice's history, not the connection's.
