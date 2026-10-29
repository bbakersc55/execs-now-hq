# Several mailboxes per practice (2026-10-28)

A practice can send from, and read, more than one mailbox: the practice
owner's own, a shared address like info@, a client's mailbox the practice
runs. Code: `apps/crm/services/mailboxes.py`, `sender.choose`,
`mail_filing.py`, `views_mail.py`; screens: Settings → Email → Mailboxes,
the From choices, and the Mail tab on every contact and company.

## What a mailbox is

| Kind | Where its sign-in lives | Connected from |
|---|---|---|
| Someone's own | their Gmail or Microsoft 365 connection, as before | "Your connection" on Settings → Email |
| A shared address | on the mailbox's own row (`mailbox.token_ciphertext`) | "Connect another mailbox" |
| A client's mailbox | the same, with the client company it belongs to | "Connect another mailbox" |

A shared or client mailbox's token is never kept in `tenant_secret`, which
holds one token per person: connecting info@ must never replace the
connector's own. Each mailbox has its own send-as check, its own reply
reading (when it was connected with "Also collect replies"), and, on a
laptop, its own entries on the dev allow-list. Gmail and Microsoft 365
mailboxes each go through their own transport; a Microsoft one can be
connected only once the Entra registration's variables are set.

## Where a message goes from

`sender.choose`, in order: the choice made on the Outbox item (or a
campaign's From); the mailbox the conversation's thread is already in; the
company's default ("Mail about this company goes from", on its Mail tab);
the sender's own address where their per-kind setting says so; their
default mailbox (Settings → Email); and the practice alias. A disconnected
mailbox is passed over. The row records the mailbox with its From, and the
Outbox item shows it before approval and can change it; a conversation lives
in one mailbox, so changing the mailbox moves the draft to that mailbox's
thread.

**A practice with one connection is unchanged.** Its connection becomes its
one mailbox the first time anything asks; with no default set anywhere, the
From is exactly what it was and goes through the same connection.

## Disconnecting

Disconnecting a mailbox (its own Disconnect, or a person's own on their
connection) stops both at once: nothing is sent through it (a message
waiting on it is refused at approval with the reason, never sent from
another mailbox) and nothing is read from it. The row stays, so threads
still say which mailbox they were.

## The Mail tab

Every message in or out with the contact (or anyone at the company), across
the mailboxes, newest first, with which mailbox it was in. Reply in place
goes through the thread's mailbox, threaded; an assistant's reply is a draft
in the Outbox. Marketing mail is still written and approved in the Outbox.
The practice owner and associates see it for the contacts and companies they
can see; an assistant only for the client companies they are assigned to; a
client never. An invoice's mail stays out of anyone's view who may not see
the invoice.

**"File mail with contacts and companies"**, per mailbox and off unless
turned on, also brings in mail the app did not send: every 15 minutes, with
the reply poll, new mail in that mailbox (from 30 days back the first time)
is looked at by its envelope only, and fetched and kept only when someone on
it other than the practice's own people is a contact or at a company's
domain. Anything else, personal mail included, is never stored, not even in
the unmatched queue.
