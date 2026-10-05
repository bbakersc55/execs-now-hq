# UI 3 — the top bar, Settings and Profile

**Spec for owner review · 2026-10-05 · no code and no migration until approved**

The owner's words: *move settings and profile out of the bottom of the sidebar
into a bar across the top, with the profile picture at the top right. Clicking
it opens a dropdown with Settings and Profile. Settings shows the options that
person's permissions allow. Profile is where they change personal information
and their profile picture.*

Decisions for the owner are numbered D1–D12 in §9, each with a recommended
default. Everything else below assumes the defaults.

## 1. What is there today

- The sidebar holds, top to bottom: the product name and practice, the
  practice/Practices switch (platform owner only), **New note**, the
  navigation, **Collapse**, and a block with the person's initials, name, role
  and "Act as a colleague".
- The navigation ends in a **Settings** group: Email settings (practice owner,
  associate), Branding, Referral settings, Stage automations, Staff, AI usage
  (practice owner).
- "Recording audio retention" is a card at the bottom of Notes, practice owner
  only.
- **Feedback** is a floating button at the bottom right of every staff screen.
- **There is no Sign out anywhere in the app.** A session ends when it expires
  (12 hours for staff, 30 days for a client). The top bar is where that gets
  fixed.
- A person is a sign-in email, a full name and a time zone (stored, never
  used). There is no picture; the colored initials are generated from the name.

## 2. The top bar

A bar across the top of the content area, to the right of the sidebar, 56px
tall, white with a bottom border, on every signed-in screen.

| Left | Right |
|---|---|
| The sidebar's **collapse/expand** button | **Feedback** (staff in a practice only), then the **profile button**: the picture, or the initials when there is none |

The middle is left empty (D1). The always-on banners (acting as a colleague,
demo) stay where they are, directly under the bar, and are never covered by it.

**The profile menu** opens under the picture. It is the same kind of menu as
the one on a Pipeline card: Enter/Space opens, arrows move, Escape closes and
returns focus, a click outside closes.

1. A header that is not a link: name, role by name ("Practice owner"), and the
   practice.
2. **Profile**
3. **Settings** (only for someone who has at least one setting; §4)
4. **Act as a colleague** (practice owner only, as today; D2)
5. **Sign out**, separated at the bottom

**Sign out** is new. `POST /auth/sign-out` ends the session on the server and
returns to the sign-in screen. If the person is acting as a colleague, it ends
that first and records it, as stopping does today. Client users get it too.

## 3. What moves out of the sidebar, and what stays

**Moves out:** the Settings group (all six entries) to the Settings page; the
name/role block to the profile menu; Collapse to the left end of the top bar.

**Stays:** the product name and practice; the practice/Practices switch (D3);
New note, and `n`; every other navigation group, unchanged, for staff and for
client users.

The sidebar gets shorter by eight rows, which is most of the point: on a laptop
the navigation currently scrolls.

## 4. Settings

One page at `/settings`, reached only from the profile menu. A list of sections
on the left, the chosen section on the right. A person sees only the sections
their role allows; nothing is shown disabled. The existing screens are reused
as they are, and **their addresses do not change**, so bookmarks and links in
emails keep working (D4).

| Section | Practice owner | Associate | Assistant | Client owner / team member |
|---|---|---|---|---|
| Email (connection, sender, footer) | yes | their own connection only, as today | no | no |
| Branding | yes | no | no | no |
| Staff | yes | no | no | no |
| Pipeline: Stage automations | yes | no | no | no |
| Pipeline: Referral settings | yes | no | no | no |
| Notes: Recording audio retention | yes | no | no | no |
| AI usage | yes | no | no | no |

- **An assistant has no settings today**, so their menu has no Settings entry
  rather than an empty page.
- **Client portal users see no Settings.** Their menu is Profile and Sign out.
  When "a client owner manages their own users" is built, that becomes the
  first client Settings section.
- **"Recording audio retention" moves here**, to a Notes section, with the same
  card, wording and warning. It leaves the bottom of Notes.
- Strategy templates stay where they are, reached from Strategy (D5).
- This is layout. No permission changes: every section is served by the
  endpoint it uses today, with today's role rules.

## 5. Profile

A page at `/profile`, for every signed-in person including client users.

**Fields**

| Field | Editable | Notes |
|---|---|---|
| Full name | yes | Shown wherever the person is named: assignee, comments, digests |
| Profile picture | yes | §6 |
| Sign-in email | **no**, shown read-only (D6) | It is the identity Google sign-in and sign-in links match on |
| Role, practice, client company | no | Shown; the practice owner sets them |
| Time zone | not shown (D7) | Stored but nothing reads it; digests use the practice's time zone |

Job title and phone are not added (D8).

**While acting as a colleague, Profile is read-only.** The practice owner can
see a colleague's profile but cannot rename them or change their picture from
inside their session. A person's profile is theirs.

A practice owner already sets a staff member's name when inviting them; that
stays. Profile is the person changing their own.

## 6. The profile picture

- **Upload:** JPEG, PNG or WebP, up to 5 MB (D9). Anything else is refused with
  a sentence saying what is accepted.
- **Cropping:** the browser shows the picture with a square crop the person can
  move and zoom, and a round preview, since it is shown round. No cropping
  library: one canvas.
- **What is stored:** the server re-encodes the crop to a 256×256 JPEG. That
  discards the original, any location or camera data in it, and anything that
  is not really an image. The stored file is a few tens of KB.
- **Storage:** the practice's file storage (the same bucket and code as flyers
  and logos), under `avatars/`, never under the recordings prefix. It is in the
  nightly backup like any other file.
- **Serving:** `GET /api/people/<id>/picture`, signed-in only, never a public
  link. A staff member can fetch pictures of people in their practice. A client
  user can fetch their own, their company's users', and the practice staff's;
  never another client company's.
- **Removing:** "Remove picture" returns to initials and deletes the file.
- **Where it appears (D10):** first, the top bar and the Profile page only.
  Then, as its own phase, everywhere the initials appear today: assignees on
  task cards and lists, comments, Staff, contacts' owners. It does **not**
  appear in emails, digests or PDFs.

## 7. Data model

One column. Nothing else changes: the name is already on the user, and Sign
out, Settings and the top bar need no schema.

The picture belongs on the **membership** (the person in a practice), not on
the user: files are stored per practice, a membership is already per practice,
and a client user's membership is what ties them to their company for the
serving rule in §6.

```python
# apps/tenancy/models.py, Membership
avatar = models.ForeignKey(
    "tenancy.StoredFile", null=True, blank=True,
    on_delete=models.SET_NULL, related_name="+",
)
```

Planned SQL (the real `sqlmigrate` output is shown before the migration is
generated, as always):

```sql
ALTER TABLE "membership"
  ADD COLUMN "avatar_id" uuid NULL
  CONSTRAINT "membership_avatar_id_fk_stored_file_id"
  REFERENCES "stored_file" ("id") DEFERRABLE INITIALLY DEFERRED;
SET CONSTRAINTS "membership_avatar_id_fk_stored_file_id" IMMEDIATE;
CREATE INDEX "membership_avatar_id_idx" ON "membership" ("avatar_id");
```

Additive and nullable: no rows are rewritten, nothing is dropped, and every
existing person simply has no picture. On the laptop it is applied at once
under the standing rule; in production it goes through "Releasing a migration"
in the cutover runbook. A new storage purpose, `avatar`, is a constant, not
schema.

## 8. Build phases

Each phase is finished, tested and shown before the next. v2 and v3 goldens
untouched throughout; phase 5 is the only one that changes payloads other
screens read, and it is checked against the goldens before anything is merged.

1. **Top bar and Sign out.** The bar, the profile menu (initials), Collapse and
   Feedback moved, the name block removed from the sidebar, the sign-out
   endpoint. *No schema.*
   Tests: the menu's entries per role (practice owner, associate, assistant,
   client owner, client team member, platform owner in Practices); keyboard
   use; sign-out ends the session and a second request is refused; sign-out
   while acting as ends and records the acting; the vocabulary tests (roles by
   name, "practice").
2. **Settings page.** `/settings` with sections by role, the Settings group
   removed from the sidebar, "Recording audio retention" moved. *No schema.*
   Tests: each role sees exactly its sections; an assistant and both client
   roles have no Settings entry and `/settings` shows nothing of it; old
   addresses still open; the role-boundary tests for every settings endpoint
   are unchanged and still pass.
3. **Profile: name.** `/profile`, `GET`/`PATCH /api/me/profile`.
   Tests: a person changes only their own name; read-only while acting as;
   the email is refused if sent; practice isolation; both client roles can use
   it and see nothing beyond their own profile.
4. **Profile picture.** The migration (SQL first), upload with crop, serve,
   remove; shown in the top bar and on Profile.
   Tests: file type and size limits; the stored file is a 256×256 JPEG whatever
   was sent; **practice isolation** (a user in practice A cannot fetch a
   picture from practice B); **role boundaries** (a client user cannot fetch a
   picture from another client company; signed-out gets nothing); remove
   deletes the file; only your own can be changed, and not while acting as.
5. **Pictures wherever a person is shown.** Its own approval, after 4 is in
   use.

## 9. Decisions for the owner

| # | Decision | Recommended default |
|---|---|---|
| D1 | Does the top bar hold a global search? | **Not now.** Each list has its own search; a global one is its own piece of work. The space is left for it. |
| D2 | Where does "Act as a colleague" live? | **In the profile menu**, practice owner only. The banner that shows while acting stays exactly as it is. |
| D3 | Does the practice/Practices switch (platform owner) move to the profile menu? | **No, it stays in the sidebar.** It changes what the whole sidebar shows, so it belongs beside it. |
| D4 | Do the settings screens get new addresses under `/settings/…`? | **No.** Keep today's addresses and show them inside the Settings page, so no link breaks. |
| D5 | Do Strategy templates move into Settings? | **No.** They are working material reached from Strategy, not a setting. |
| D6 | Can a person change their own sign-in email? | **No, shown read-only for now.** It is how Google sign-in and sign-in links find the account; changing it safely needs a confirmation sent to the new address and is a follow-up. |
| D7 | Show time zone on Profile? | **No, until something uses it.** A field that changes nothing is a broken promise. |
| D8 | Add job title and phone to a person? | **No for now.** Name and picture only. They are easy to add once there is a place that shows them. |
| D9 | Picture limits | **JPEG, PNG or WebP, up to 5 MB, stored as a 256×256 JPEG.** |
| D10 | Where pictures appear | **Top bar and Profile first; everywhere initials show as a later phase; never in emails, digests or PDFs.** |
| D11 | Can client portal users have a profile picture? | **Yes.** Same page, same rules; a client never sees another company's people. |
| D12 | Does Feedback move into the top bar or stay floating? | **Into the bar**, at the right, staff only. The floating button covers the bottom of long pages and the Pipeline's last column. |
