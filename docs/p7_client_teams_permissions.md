# P7 — Client teams and permissions

**Spec · 2026-10-12 · decisions open (§10) · no code until they are answered**

Asked for on the 2026-10-12 call (`docs/beta_feedback_2026-10-12.md`, S1).
Today every client user in a client company sees the same things, and the
only difference between two of them is "client owner" or "client team
member". A client with thirty people in four departments needs more than
that: a person should see their own work, a manager their team's, and the
leadership all of it.

**Decided by Bryan on 10/12, and written into the sections below:**

- Client users belong to **teams** within a client company.
- A **member** sees goals company-wide, read-only, and sees and edits the
  projects and tasks that are assigned to them or that they created.
- A **manager** does anything within their team, and views other teams.
- **Senior leadership** has full edit on all three levels (goals, projects,
  tasks) across selected teams, or all of them.
- The **client owner** has everything.
- **Per user, what they may create:** tasks only; projects and tasks; or
  goals too.
- Teams are set up **by the practice or by the client owner**.
- **Steps** (a task's checklist) carry no permissions of their own.
- **Digests and the value report keep their current audiences.**

Everything else here is a proposal, and each open point is a row in §10 with
a recommendation.

---

## 0. What the app has today that this changes

| Exists today | In P7 |
|---|---|
| Two client roles: client owner (`FCC`) and client team member (`ECC`), one company each (`membership`) | The two codes stay. A client user also gets a **level** on each team they are in, and a **may-create** setting |
| A client user sees every goal, every project and every client-visible task of their company (`apps/work/permissions.py`) | What they see depends on their level (§2) |
| A client user may edit a task that is client-visible, in their company, and either assigned to a client-side user or created by a client (FR-3.9a) | That rule stays as the outer limit: P7 narrows inside it, and never widens past it (§2.5, P7-4) |
| Clients create tasks and projects, never goals; the client owner may propose a goal and propose a goal order | "Goals too" becomes a per-user setting (§3) |
| A project has a practice-side owner and a client-side owner who is a contact; a task has an assignee who is a user | A project and a task also carry a **team** (§1.2) |
| "Act as a colleague", the client owner's control | Unchanged, and still the client owner's alone |
| Seats per client company | Unchanged: a seat is a person, however many teams they are in |
| Digests go to stakeholders, who are contacts; the value report is the company's | Unchanged (decided) |

The practice side is not changed at all: a practice owner, associate or
assistant sees and edits what they do today.

---

## 1. Teams

### 1.1 What a team is

A team is a named group of client users inside one client company:
"Operations", "Sales", "Front office". A team belongs to exactly one client
company and is never shared between companies or practices.

- A client user may be in **more than one team**, with a level on each: a
  member of Sales and the manager of Operations.
- Every client company with portal users has **one default team**, made by
  the migration and named "Everyone" (renameable). It cannot be removed while
  it is the only team.
- A team can be **archived**. Its people keep their sign-in; its projects and
  tasks move to the default team, and the screen says how many will move
  before it is confirmed.
- A user in no team at all is treated as a member with nothing assigned: they
  see the goals and their own work, and nothing else.

### 1.2 Which team a piece of work belongs to

- **A goal belongs to the company, not to a team** (P7-2). Everyone in the
  company sees every goal.
- **A project belongs to one team.**
- **A task belongs to its project's team.** A task with no project belongs to
  the team chosen when it was made.
- When a client user creates a project or a standalone task, the team is
  theirs if they are in one team, and is asked for if they are in several.
- When the practice creates one for a client company, the team is asked for
  and defaults to the default team.
- Moving a project to another team moves its tasks with it.

### 1.3 Who sets teams up

Decided: the practice, or the client owner.

- **Practice side:** whoever may manage that company's portal users today
  (the practice owner; an associate assigned to that company; an assistant)
  may create, rename and archive teams, put people in them, and set levels
  and may-create (P7-8).
- **Client side:** the client owner only. A manager does not add people to
  their own team or change anyone's level.
- Every change is in the audit trail with who made it, as portal role changes
  are today.

---

## 2. Levels: who sees and changes what

A client user's level is set per team. The client owner's is not set at all:
they have everything, in every team.

### 2.1 The table

"Theirs" means assigned to them or created by them. For a project,
"assigned to them" means they are its client-side owner (P7-3).

| | Goals | Projects and tasks in their team | Projects and tasks in other teams |
|---|---|---|---|
| **Member** | See all, read-only | See and edit **theirs** only | Nothing, except theirs |
| **Manager** | See all, read-only | See and edit all | See all, read-only |
| **Senior leadership** (selected teams, or all) | See all; **edit** | See and edit all, in the teams they lead | See all, read-only |
| **Client owner** | See all; edit | See and edit all | (no other teams: all are theirs) |

### 2.2 A member

- Sees every goal of the company with its status and progress, as the value
  report shows it, and cannot change one.
- Sees and edits the tasks assigned to them and the tasks they created; sees
  and edits the projects they are the client-side owner of and the projects
  they created.
- **Sees the name of a project one of their tasks sits in,** with only their
  own tasks listed under it, so that a task is not shown without its context
  (P7-5). They do not see the project's other tasks.
- May reassign a task of theirs to someone in the same team. It then leaves
  their list unless they created it (P7-6).

### 2.3 A manager

- Everything a member has.
- Sees and edits every project and task in their team, and may assign any of
  them to anyone in the team.
- Sees every project and task in the other teams of the company, read-only.

### 2.4 Senior leadership

- Set per user as **all teams**, or **selected teams**.
- In the teams they lead: everything a manager has, and may assign across
  those teams.
- In the other teams: sees, read-only.
- **Edits goals** (P7-2: because a goal belongs to the company, a senior
  leader edits any goal, whichever teams they lead).

### 2.5 What no client level changes

These hold today and are not widened by any level, the client owner's
included (P7-4):

- A task that is **not client-visible** is never seen by a client user.
- A task **assigned to someone at the practice** is read-only to every client
  user, apart from shared comments: if the practice owns the work, the client
  asks.
- An **internal comment** is absent from every client response.
- A client hands work only to a colleague in their own company, never to
  someone at the practice.
- Deleting: a client user deletes only what they created themselves. A
  manager or senior leader may **cancel** any task they can edit, not delete
  it.
- Out of scope is "not found", never "not allowed".

### 2.6 Steps and comments

- **Steps carry no permissions of their own** (decided): whoever may edit a
  task may add, tick, reorder and remove its steps; whoever may only see it
  sees them.
- Shared comments follow the task: whoever sees a task may read and add
  shared comments on it, including on a task they cannot edit.

---

## 3. What a user may create

Set per user, by whoever sets up teams (§1.3):

| Setting | May create |
|---|---|
| **Tasks only** | Tasks, in their own team, or with no project |
| **Projects and tasks** | Those, and projects in their team (under a goal or not) |
| **Goals too** | Those, and goals for the company |

- This is separate from the level: a member may be allowed to create
  projects; a manager may be held to tasks only.
- A user may create only where they could then edit: a member's new project
  is theirs because they created it.
- **A goal created by a client user is live at once,** marked "Added by
  <name>, <client company>", and the practice is told in its activity feed
  and on the Work screen (P7-7). It is in the value report from the next time
  the report is drawn, as any goal is. The practice may edit or remove it, as
  it may any goal.
- The client owner's existing "Propose a goal" stays for a client owner who
  is set to less than "Goals too"; with "Goals too" the button creates
  instead of proposing.
- Proposing a **goal order** stays the client owner's alone.

---

## 4. Screens

### 4.1 Practice side

**The client company's page, "Portal users"** gains a second card, "Teams":

- The teams, each with its people and their levels, and a count of its open
  projects and tasks.
- "Add a team", rename, archive (with the count of what will move).
- For each person: the teams they are in and their level on each; "Senior
  leadership: all teams / these teams"; and "May create: tasks only /
  projects and tasks / goals too".
- "See the portal as…" (which exists) is how the practice checks what a level
  shows: it already opens the portal as a named user.

**Work screen and the task and project sheets:** a "Team" field on a project
and on a standalone task for a client company, defaulting to the default
team. A filter by team beside the existing filter by client.

**Inviting a portal user:** the invitation form asks for the team and the
level, defaulting to the default team and "Member" (P7-9).

### 4.2 Client owner side

**Portal → "Your team"** (the page that lists the company's users today, and
where "Act as a colleague" lives) gains the same Teams card, in the portal's
own look and the practice's brand:

- Add, rename, archive a team.
- Put a person in a team and set their level; set senior leadership and its
  teams; set what each may create.
- It does not invite people or change seats: that stays where it is.

### 4.3 Every other client user

- **My work:** their tasks and projects, as §2 gives them. For a manager or a
  senior leader, a switch "Mine / My team / Everyone", where "Everyone" is the
  read-only view of other teams.
- **Where we are** (the goals): unchanged for everyone, and read-only unless
  the user may edit goals.
- A thing they may see and not edit shows no edit controls, and says "Only
  <team>'s manager can change this" once, at the top of the sheet.
- "New" offers only what they may create.

### 4.4 Words

The role names stay in one place (`apps/tenancy/roles.py`,
`frontend/src/lib/roles.ts`). P7 adds the level names there: **Member**,
**Manager**, **Senior leadership**. "Client team member", the shown name of
`ECC`, now collides with "team member": P7-10 proposes showing the level in
its place wherever a client user is listed, and keeping "Client owner".

---

## 5. Data model

| Table | Columns | Notes |
|---|---|---|
| `client_team` *(new)* | `id`, `tenant_id`, `client_company_id`, `name`, `is_default`, `archived_at`, `created_by_id` | Unique live name per company; exactly one live default per company |
| `client_team_member` *(new)* | `id`, `tenant_id`, `team_id`, `membership_id`, `level` (`member`, `manager`, `leader`) | Unique per team and membership. The membership must be a client one of the team's own company (checked in code, and by the isolation tests) |
| `membership` | `+ may_create` (`tasks`, `projects`, `goals`; default `projects`), `+ leads_all_teams` (boolean, default false) | Meaningful for client roles only; a check constraint keeps both at their defaults for practice roles |
| `project` | `+ client_team_id` (nullable) | Null for the practice's internal projects, which have no client company |
| `task` | `+ client_team_id` (nullable) | Set for a standalone client task; a task in a project reads its project's |
| `goal` | `+ created_by_client` (boolean, default false) | A goal has no such flag today, because a client could not create one |

All new tables carry `tenant_id` and go through the tenant-aware manager.

**One place for the rule.** `apps/work/permissions.py` already holds
"FR-3.9a, the whole rule" in `client_may_edit`. P7 adds the level beside it,
in the same file: `client_scope(request)` gives the teams a user is in and at
what level; `goal_queryset_for`, `project_queryset_for` and
`task_queryset_for` use it for client roles; `client_may_edit` asks it after
FR-3.9a has said yes. No view decides for itself.

---

## 6. Migrations

Three, in this order, shown as SQL before they are generated:

1. **`tenancy` 0014** — `membership.may_create`, `membership.leads_all_teams`.
   Additive.
2. **`work` 0010** — `client_team`, `client_team_member`,
   `project.client_team_id`, `goal.created_by_client`. Additive. Then a
   **data step** (below).
3. **`crm` 0035** — `task.client_team_id`. Additive, with the task half of
   the data step.

**The data step, which writes:**

- For every client company that has at least one live portal user, or at
  least one project or task: one default team, "Everyone".
- Every live client membership of that company becomes a `client_team_member`
  of it, at the level §7 settles.
- Every project and every standalone task of that company gets that team.
- `may_create` is `projects` for everyone (what a client user may create
  today).

It is reversible (the reverse drops the rows it made). Because it writes
data, **production gets it only after a dry run that prints each company's
before and after, and Bryan's yes**, by "Releasing a migration". On the
laptop's `execsnowhq_local` it is applied when the suite is green, as any
migration is.

---

## 7. What changes for existing portal users

**Recommended: nothing changes for anyone on the day of the release.**

Bryan's recommendation is that every existing portal user becomes a member
of a default team with their current rights. Those two halves do not quite
fit, and the choice between them is P7-1:

- Today a client team member **sees every project and client-visible task of
  the company**, and edits any that is on the client's side. Under §2 that is
  what a **manager** of the only team has, not what a **member** has. A
  member sees only their own.
- So "with their current rights" means: everyone is put in the default team
  **at the level Manager**. Nobody loses sight of anything. The practice or
  the client owner then makes real teams and sets people to Member as they
  choose, and that is the moment anyone sees less.
- The other reading, everyone at the level **Member**, is the tidier end
  state and takes away each person's view of their colleagues' work on
  release day, without anyone having chosen it.

Either way:

- **Client owners** stay client owners, with everything.
- **May create** is "projects and tasks" for everyone, as today. Nobody gets
  "goals too" until someone sets it.
- **Nobody is senior leadership** until someone sets it.
- Sign-ins, seats, digest audiences, the value report and "Act as a
  colleague" are untouched.
- An invitation that is out and not yet accepted lands in the default team
  at the same level when it is accepted.

---

## 8. Tests

The two mandatory families, extended:

- **Practice isolation:** a team, a team member and a team's work in practice
  A are never in practice B's responses; a team of company X is never
  reachable by a user of company Y in the same practice. `client_team` and
  `client_team_member` are registered in the isolation registry, which fails
  on an unregistered model.
- **Role boundaries, as one matrix test:** for each of member, manager,
  senior leadership (selected), senior leadership (all) and client owner,
  against goals, projects, tasks, steps and comments, in their own team and
  in another: see, edit, create, assign, cancel, delete. One row of the table
  in §2.1 is one parametrized case, so the table and the tests cannot drift.
- FR-3.9a's existing tests stay green unchanged: no level reaches a task
  that is not client-visible or that the practice owns.
- The data step: every existing portal user can reach exactly the set of
  projects and tasks after the migration that they could before it, compared
  id for id on a seeded company.
- May-create: each setting creates what it should and is refused, with a
  sentence, on the rest.
- The practice side: every existing practice-role test passes unchanged.

---

## 9. Build phases

Each is finished, tested and reported before the next.

| Phase | What | Seen by a user |
|---|---|---|
| 1 | The tables, the three migrations with the data step, and the rule in `permissions.py`, with everyone at the level §7 settles | Nothing changes |
| 2 | Practice side: the Teams card, levels, may-create, the Team field on projects and tasks, the invitation form | The practice can make teams and set levels; a level takes effect when set |
| 3 | Client owner side: the Teams card in the portal | The client owner can do the same |
| 4 | The portal for members, managers and senior leaders: "Mine / My team / Everyone", read-only sheets, "New" by may-create, goals by a client user | The whole of §2 and §3 |

Phase 1 is released on its own with its dry run. The module is not behind a
switch: it is how the portal works, for every practice.

---

## 10. Decisions

| # | Question | Recommendation | Bryan |
|---|---|---|---|
| **P7-1** | **Existing portal users: Manager of the default team, or Member?** "Their current rights" is what a Manager has (§7). | **Manager of the default team,** so nobody loses anything on release day; set people to Member as real teams are made. | |
| **P7-2** | **Does a goal belong to a team?** "Senior leadership has full edit on all three levels across selected teams" reads as if it might. | **No: a goal is the company's.** Everyone sees every goal; any senior leader, and the client owner, may edit any goal. A goal per team would hide the engagement's shape from the people doing the work, and the value report is one report. | |
| **P7-3** | **What "assigned to them" means for a project,** which has no assignee today. | **Its client-side owner** (the field exists). No new column. | |
| **P7-4** | **Do "full edit" and "everything" reach work the practice owns?** Today a client user cannot edit a task assigned to someone at the practice, or see one that is not client-visible. | **No.** Levels divide the client's side of the work among the client's people; they do not widen it. | |
| **P7-5** | **Does a member see the name of a project their task sits in?** | **Yes: the name and their own tasks in it,** nothing else of it. | |
| **P7-6** | **May a member reassign their own task?** | **Yes, within their team.** It leaves their list unless they created it. | |
| **P7-7** | **A goal created by a client user: live at once, or a proposal the practice accepts?** | **Live at once, marked as added by the client, and the practice is told.** "Goals too" is given deliberately, per user; a second gate would make it the same as today's proposal. | |
| **P7-8** | **Who on the practice side sets up teams?** | **Whoever may manage that company's portal users today,** an assistant included. | |
| **P7-9** | **The default for a newly invited portal user.** | **The default team, level Member, may create "projects and tasks".** New people start narrow; existing people keep what they have (P7-1). | |
| **P7-10** | **The shown name of `ECC`,** "Client team member", beside the new "team" and "member". | **Show the level** (Member, Manager, Senior leadership) wherever a client user is listed; keep "Client owner". The code `ECC` stays in code and data. | |
| **P7-11** | **May a user be in more than one team?** | **Yes,** with a level on each. | |
| **P7-12** | **Archiving a team.** | **Its work moves to the default team; its people keep their sign-in.** Never deletes work. | |
| **P7-13** | **Manager and senior leader: delete, or cancel?** | **Cancel only.** Delete stays with whoever created the thing. | |
| **P7-14** | **Is this a module with a switch, or how the portal works?** | **How the portal works.** With one default team and everyone a Manager it is today's portal. | |
| **P7-15** | **Phases and releases.** | **Four phases as §9; phase 1 released alone,** with the dry run of its data step. | |

## 11. Not in P7

- Teams on the practice side (associates and assistants in groups).
- A team seeing its own digest or its own value report (decided: audiences
  are unchanged).
- Per-step permissions (decided: none).
- Private tasks (on the roadmap, its own spec).
- Two practices sharing one client (backlog S6, its own spec); P7's teams are
  inside one client company of one practice.
