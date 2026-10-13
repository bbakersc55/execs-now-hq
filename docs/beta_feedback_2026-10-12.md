# Beta feedback, the 2026-10-12 call

What was asked for on the call of 2026-10-12, as a backlog. Each item has a
status: **tonight** (a quick fix, built the night of 10/12), **this week**,
**spec first** (no code until a spec is approved), or **later**. Nothing here
is built unless its row says so. Pricing heard on the same call is in
`docs/p4_billing.md`, "Heard on the 2026-10-12 call, not decided".

"Built" in the last column is filled in as each item lands, with its commit.

## Tonight

| # | Item | Status | Built |
|---|---|---|---|
| T1 | **Portal "Where we are": goal order.** The goal cards show the client's proposed order while the text says they are in the current order. Cards and "The engagement, in order" follow the current order until the practice accepts a proposal; the proposal stays a list. The Goals (propose) box spans the full width like the boxes above it. | tonight | `f86df49` |
| T2 | **Work screen goal cards.** The title full width across the top in the bold weight; beneath it one row with the status chip, horizon date and owner avatar; beneath that the progress line and bar spanning the card ("2 of 4 done"); then projects and tasks as now. Three columns kept. | tonight | `4d43f57` |
| T3 | **Tasks, list and board: sorting.** Default by due date (overdue first, then soonest, undated last); a sort control with Due date, Priority then due, Recently updated. | tonight | `800987c` |
| T4 | **Meeting queue.** "Ours" becomes the practice's name everywhere. A practice task can be assigned to any team member, not only the owner. The client assign tool chooses an existing goal, then project, then task in that hierarchy, or creates a new one in place at any level, and the assignee chosen is kept on what it creates. Melissa's assignment bug from the call (assigned in the portal, then had to reassign by hand): reproduce and fix, or say what was found. | tonight | `7a3f4b5`. The bug as described was not reproduced; two ways a person with a sign-in reads as having no seat were found and fixed |
| T5 | **Contacts and companies: LinkedIn and Alignable.** Dedicated URL fields, shown as links. Tags: if the practice cannot already add, rename and remove tags, add that under Settings. | tonight | `0401a1a`. Tags are still added on a contact; Settings has rename and remove |
| T6 | **Notes.** Search must match the body as well as the title (a bug). Folders: built-in Internal (no link), Contacts (linked to a contact), Companies (linked to a company), plus custom folders the practice adds; a note sits in one folder; opening a folder filters to it. | tonight | `891aa9c`, tests `67536fc` |
| T7 | **Template editor.** Any section can be removed, built-in ones included; each section has a tick "On the prospect's map", off by default for sections that feed nothing to the PDF. | tonight | `ffd8ca0` |
| T8 | **Strategy map.** Every piece of text that lands on the PDF is editable before sending, the mirror, values and next steps included. No em dashes in generated map text: the model is told, and any that slip through become a colon in titles and a comma or full stop in sentences. | tonight | `795f762`. The model is not yet told: the prompts are pinned by the golden files and wait for Bryan's yes |
| T9 | **Replies screen.** One subtitle sentence saying what it is: replies to mail the app sent, matched to contacts; unmatched ones wait here to be filed. | tonight | `32daa97` |
| T10 | **Portal invitation outside the client's domain.** Verify that an invitation to an address outside the client's domain (a board member on gmail) signs in by link; fix if not. | tonight | `562397a`. Verified, no change needed |

## This week

| # | Item | Status |
|---|---|---|
| W1 | **Beta access to the demo.** A private copy of Summit per visitor, invited by email, sign-in by link, their demo mail to their own address, 30 days extendable, suspend and revoke, a "Reset my demo" button, and a hard stop on AI spend on the demo. | this week |
| W2 | **Practice-specific words for goals, projects, tasks and steps.** Set under Settings and on the Getting started list; used everywhere, the portal and the PDF included. | this week |
| W3 | **The strategy map as a Word document.** | this week |
| W4 | **Notion and ClickUp import** of goals, projects and tasks, from CSV templates matched to each tool's export. Melissa is sending samples. | this week |

## Spec first

| # | Item | Status |
|---|---|---|
| S1 | **Client teams and permissions.** Client users belong to teams within a client company, with member, manager, senior leadership and client owner rights, and a per-user setting for what they may create. **Spec written 10/12: `docs/p7_client_teams_permissions.md`, decisions open.** | spec first |
| S2 | **PDF redesign** in the style of the 5FT View weekly brief (cards, eyebrow labels, one or two lines per item), after a mock Bryan approves. | spec first |
| S3 | **Pipeline stages editable on both pipelines,** with the automation per stage and an optional campaign per stage. The default is not to enroll; the stage move asks "Enroll in X?". | spec first |
| S4 | **Email templates editable under Settings,** all of them except sign-in links and unsubscribe footers. | spec first |
| S5 | **Desktop notifications** for tasks due, digests waiting, replies, meeting proposals and client proposals, each switchable. | spec first |
| S6 | **Two practices sharing one client.** The Work and the portal only: each practice edits its own goals, projects and tasks, both see all, the client sees one list, and each practice's digests are its own. With **referral fee payouts**: a percentage for a period or a flat amount, recorded as an expense under Commissions. | spec first |
| S7 | **Microsoft 365 transport.** Spec exists (`docs/m365_transport.md`), seven decisions open. | spec first |
| S8 | **Contract e-signature.** | spec first |

## Later

| # | Item | Status |
|---|---|---|
| L1 | **A format editor for the PDF.** | later |
| L2 | **Integrations to migrate from Notion and ClickUp directly** (after W4's CSV import). | later |
