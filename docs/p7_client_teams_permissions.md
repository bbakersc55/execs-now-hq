# P7 — Client teams and permissions

**Spec · 2026-10-12 · all fifteen decisions answered by Bryan 2026-10-13, as
recommended, with two additions (§10) · phase 1 building**

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
- **Per user, what they may create:** nothing; tasks only; projects and
  tasks; or goals too. ("Nothing" added 2026-10-13, so a member can be
  assigned work without being able to create any.)
- A **viewer** (added 2026-10-13) sees every goal, project and client-visible
  task in the company, read-only, and creates and edits nothing. It is for a
  board member or an investor who signs in to look.
- Teams are set up **by the practice or by the client owner**.
- **Steps** (a task's checklist) carry no permissions of their own.
- **Digests and the value report keep their current audiences.**

Everything else here was a proposal, each open point a row in §10 with a
recommendation; Bryan took every recommendation on 2026-10-13.

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
| **Viewer** | See all, read-only | See all, read-only | See all, read-only |

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

### 2.4a A viewer

Added by Bryan, 2026-10-13: a board member or an investor who signs in to
look.

- Sees every goal, every project and every client-visible task of the
  company. Changes nothing and creates nothing, whatever "may create" says.
- It is a level like the others, held on a team (the default team, for
  someone who is in no other). What a viewer sees does not depend on which
  team holds it: it is the whole company.
- A person who is a viewer on one team and a member, manager or senior
  leader on another has the rights of the higher level: the viewer row only
  adds sight.
- **As built, and Bryan's to overrule:** a viewer does not comment (a comment
  is something created), and a task cannot be assigned to someone who is
  only a viewer.

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
| **Nothing** | Nothing. They may still be assigned work, and edit what is theirs |
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
| `client_team_member` *(new)* | `id`, `tenant_id`, `team_id`, `membership_id`, `level` (`member`, `manager`, `leader`, `viewer`) | Unique per team and membership. The membership must be a client one of the team's own company (checked in code, and by the isolation tests) |
| `membership` | `+ may_create` (`nothing`, `tasks`, `projects`, `goals`; default `projects`), `+ leads_all_teams` (boolean, default false) | Meaningful for client roles only; a check constraint keeps both at their defaults for practice roles |
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
3. **`crm` 0036** — `task.client_team_id`. (Written as 0035 on 10/12; that
   number was taken the same night by the LinkedIn and Alignable links.) Additive, with the task half of
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

**Two release-day changes, by Bryan's rulings of 2026-10-13 and 10-14:** a
client user who did not make a project, and is not the client owner, can no
longer delete it (they can set it to cancelled); and the client owner may
delete a task a colleague made. See "As built: phase 1", reading 3. The
second is in a commit after phase 2, so it goes out with whichever release
carries that commit.

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

| # | Question | Recommendation | Bryan, 2026-10-13 |
|---|---|---|---|
| **P7-1** | **Existing portal users: Manager of the default team, or Member?** "Their current rights" is what a Manager has (§7). | **Manager of the default team,** so nobody loses anything on release day; set people to Member as real teams are made. | As recommended, 10/13 |
| **P7-2** | **Does a goal belong to a team?** "Senior leadership has full edit on all three levels across selected teams" reads as if it might. | **No: a goal is the company's.** Everyone sees every goal; any senior leader, and the client owner, may edit any goal. A goal per team would hide the engagement's shape from the people doing the work, and the value report is one report. | As recommended, 10/13 |
| **P7-3** | **What "assigned to them" means for a project,** which has no assignee today. | **Its client-side owner** (the field exists). No new column. | As recommended, 10/13 |
| **P7-4** | **Do "full edit" and "everything" reach work the practice owns?** Today a client user cannot edit a task assigned to someone at the practice, or see one that is not client-visible. | **No.** Levels divide the client's side of the work among the client's people; they do not widen it. | As recommended, 10/13 |
| **P7-5** | **Does a member see the name of a project their task sits in?** | **Yes: the name and their own tasks in it,** nothing else of it. | As recommended, 10/13 |
| **P7-6** | **May a member reassign their own task?** | **Yes, within their team.** It leaves their list unless they created it. | As recommended, 10/13 |
| **P7-7** | **A goal created by a client user: live at once, or a proposal the practice accepts?** | **Live at once, marked as added by the client, and the practice is told.** "Goals too" is given deliberately, per user; a second gate would make it the same as today's proposal. | As recommended, 10/13 |
| **P7-8** | **Who on the practice side sets up teams?** | **Whoever may manage that company's portal users today,** an assistant included. | As recommended, 10/13 |
| **P7-9** | **The default for a newly invited portal user.** | **The default team, level Member, may create "projects and tasks".** New people start narrow; existing people keep what they have (P7-1). | As recommended, 10/13 |
| **P7-10** | **The shown name of `ECC`,** "Client team member", beside the new "team" and "member". | **Show the level** (Member, Manager, Senior leadership) wherever a client user is listed; keep "Client owner". The code `ECC` stays in code and data. | As recommended, 10/13 |
| **P7-11** | **May a user be in more than one team?** | **Yes,** with a level on each. | As recommended, 10/13 |
| **P7-12** | **Archiving a team.** | **Its work moves to the default team; its people keep their sign-in.** Never deletes work. | As recommended, 10/13 |
| **P7-13** | **Manager and senior leader: delete, or cancel?** | **Cancel only.** Delete stays with whoever created the thing. | As recommended, 10/13 |
| **P7-14** | **Is this a module with a switch, or how the portal works?** | **How the portal works.** With one default team and everyone a Manager it is today's portal. | As recommended, 10/13 |
| **P7-15** | **Phases and releases.** | **Four phases as §9; phase 1 released alone,** with the dry run of its data step. | As recommended, 10/13 |

| **P7-16** | *(Bryan's addition)* **A fourth level, Viewer.** | | Sees every goal, project and client-visible task in the company, read-only; creates nothing, edits nothing. For a board member or an investor (§2.4a). |
| **P7-17** | *(Bryan's addition)* **"Nothing" as a may-create choice.** | | A member can be assigned work without being able to create any (§3). |

On P7-7 Bryan added: the Propose button stays for everyone who is not given
"goals too".

## 11. Not in P7

- Teams on the practice side (associates and assistants in groups).
- A team seeing its own digest or its own value report (decided: audiences
  are unchanged).
- Per-step permissions (decided: none).
- Private tasks (on the roadmap, its own spec).
- Two practices sharing one client (backlog S6, its own spec); P7's teams are
  inside one client company of one practice.

---

## As built: phase 1 (2026-10-13) — the tables, the data step and the rule

**Seen by a user: one thing.** Every portal user is a Manager of their
company's default team, which is what each could see and do before, except
that a client's project is now deleted only by whoever made it or by the
client owner (reading 3, below).

**What exists**

- `client_team` and `client_team_member` (`apps/work/models.py`);
  `membership.may_create` and `membership.leads_all_teams`;
  `project.client_team`, `task.client_team`, `goal.created_by_client`.
- **The rule, in one place:** `ClientScope` in `apps/work/permissions.py`,
  read once a request by `client_scope(request)`. The querysets and
  `client_may_edit` ask it after FR-3.13 and FR-3.9a have had their say. No
  view decides for itself.
- **The data step** is `apps/work/team_backfill.py`, read by the two
  migrations, by `manage.py client_teams_dry_run`, and by the test that holds
  it to the rule as it was before P7.
- **A portal user is placed the moment they have a sign-in**
  (`apps/work/signals.py`): on the default team, as Manager. Until phase 2's
  invitation form there is nowhere to choose a level, and anything less
  would give a person invited after the release less than one invited
  before. P7-9 (new people start as Member) takes effect with that form.

**Wired to the routes now**, because with everyone a Manager each gives the
answer it gave before: which projects and tasks a client user sees and may
change; who a task may be handed to; "may create" for tasks and projects; a
viewer not commenting; the team new work lands on.

**Ruled and tested, and not opened by any route until phase 4:** a senior
leader or the client owner editing a goal, and a goal created by someone
given "goals too". Both would change what a client owner can do on the day
phase 1 is released, and the second needs the practice told. Which of a
goal's fields a client may change (the outcome statement is the practice's
sentence) is a question for phase 4.

**Readings made while building.** Bryan, 2026-10-13: 1, 2, 4 and 5 stand; 3
is overruled, as it now reads.

1. **The tasks in a project that is theirs are theirs.** A member who made a
   project, or is its client-side owner, sees its tasks and may change the
   ones on the client's side.
2. **A viewer does not comment,** and **a task is not handed to someone who
   only looks** (§2.4a).
3. ~~Deleting a client's project is as it was.~~ **Overruled by Bryan,
   2026-10-13: P7-13 applies to projects as well as tasks.** A client's
   project is deleted by whoever made it or by the client owner; a manager
   or a senior leader cancels it (sets it to cancelled). **This is a
   release-day change, the only one in phase 1:** before, any client user of
   the company could delete a project a colleague had made. **A task is the
   same (Bryan, 2026-10-14):** whoever made it, or the client owner. Until
   then FR-3.9a.3 kept it to its maker alone, the client owner not excepted,
   and its test was changed on that word. A task the practice made or
   assigned stays untouchable by any client user. So there are two
   release-day changes: fewer people delete a project, and the client owner
   may delete a colleague's task.
4. **A senior leader of selected teams** hands a task to anyone on a team
   they lead; **of every team**, and the client owner, to anyone who takes
   work.
5. **New work with no team named** goes to its maker's team; for someone on
   several, the default team if they are on it, else the first by name. The
   portal asks in phase 4.
6. **The value report's arithmetic is the company's for every level:** a
   member sees a goal's progress worked out from every client-visible task,
   not from their own (`report_task_queryset_for`).
7. **The data step gives a default team to every company that has a project
   or a task,** portal users or not, as §6 says. On the laptop that includes
   the practice's own company, which has tasks filed against it.
8. **The level names are on the model** (`ClientTeamMember.Level`), not yet
   in `roles.py` and `roles.ts`: nothing shows one until phase 2 (P7-10).

**Proven by tests** (`tests/test_client_teams.py`): each row of §2.1 through
the routes a portal user calls, viewer and "on no team" included; what no
level widens; may-create, "nothing" included; assignment within a team; a
person on two teams; the two new tables in the isolation registry, and a team
giving nothing outside its own company or practice; the data step leaving
every portal user reaching, id for id, what the rule before P7 gave them,
run twice, and undone; the dry run writing nothing.
**Not proven:** nothing was looked at in a browser (there is nothing new to
see); no level other than Manager has been held by a real person; the data
step has run on the laptop's copy only as a dry run.

---

## As built: phase 2 (2026-10-13) — the practice sets teams up

**Seen by the practice:** on a client company's page, under "Portal access",
a **Teams** card; a **Team** field on a new or edited project and on a task
that is in no project; a **filter by team** on Work and Tasks, beside the one
by client; and three more choices on an invitation. **Seen by a client user:**
nothing new on their screens, and whatever level they are set to from the
moment it is set.

**The Teams card** (`frontend/src/components/ClientTeams.tsx`,
`/api/client-teams/`)

- Each team: its name, what it holds (its projects, and its open tasks, those
  inside its projects included), how many people are on it. Add a team,
  rename one, archive one. The default team is renamed like any other and is
  never archived.
- **Archiving says what will move before it is confirmed:** the projects and
  the tasks in no project go to the default team. Nothing is deleted.
- Each person: their level on every team ("Not on it", Viewer, Member,
  Manager, Senior leadership), "senior leadership of every team", and what
  they may create (Nothing, Tasks only, Projects and tasks, Goals too). The
  client owner's row says they have everything; only their may-create is set.
- Every control saves as it is changed, and every change is in the audit
  trail with who made it: `client_team.created`, `.renamed`, `.archived`,
  `.level_set`, `.person_removed`, `portal.may_create_changed`,
  `portal.leads_all_teams_changed`.

**The Team field.** A project for a client company, and a task for one that
is in no project, name a team; left alone, it is the default team. A task in
a project shows its project's team and is not asked. Moving a project moves
its tasks. The field is drawn only when the company has more than one team.

**The invitation** (P7-9). Granting portal access asks for the team, the
level and may-create, starting at the default team, Member, and projects and
tasks. A client owner is asked nothing. Someone whose access is taken away
and given back is where they were.

**Level names** are in `apps/tenancy/roles.py` and `frontend/src/lib/roles.ts`
(`LEVEL_LABEL`, `MAY_CREATE_LABEL`), held identical by `test_vocabulary.py`.
On the practice's list of a company's portal users each person now reads by
level and teams ("Manager · Operations, Sales") or "Client owner" (P7-10).

**Readings made while building, each Bryan's to overrule**

1. **Who sets teams up: the practice owner, and an associate on a company
   they are assigned. Not an assistant.** P7-8 was answered "whoever may
   manage that company's portal users today, an assistant included", and
   those two halves do not agree: today an assistant cannot grant, change or
   revoke portal access (matrix §9). The narrower reading is built. An
   assistant reads the teams' names, so that they can file work on a team,
   and sees no card. One word from Bryan opens it to them.
2. **Archiving a team does not leave anyone on no team.** A person who was
   on that team and no other joins the default team at the level they held.
   The confirmation says how many.
3. **P7-10 is done where the practice lists a company's portal users, and
   not yet elsewhere.** The role picker still offers "Client owner" and
   "Client team member", because it is choosing the role, not the level; the
   portal's own lists and the "act as" picker are phases 3 and 4.
4. **Taking someone off their last team is allowed,** and the card says what
   it means: they see only work that is theirs.
5. **A team's "open tasks"** are its tasks not done and not cancelled, in its
   projects or in none.

**Known, and waiting for phases 3 and 4**

- The portal has not changed. A person set to Member or Viewer today is held
  to it by the server: a task they may not change shows no edit controls
  (the portal already reads `may_edit`), but "New task" and "New project"
  are still offered to someone who may not create, and answer with a
  sentence; and the assignee picker still offers every colleague, where the
  server now refuses one who is not on the task's team, also with a sentence.
- The client owner sets nothing up yet (phase 3).
- No migration in phase 2.

**Proven by tests:** `tests/test_client_teams_setup.py` (the card; make,
rename, archive with its preview and what moves; a level, senior leadership
and may-create each taking effect on the person's own routes at once; who may
and who may not, by role, on every route; a team not found from another
practice or reached through another company; the Team field and the filter;
the invitation's choices, its refusals, and a restored sign-in; every audit
verb) and `frontend/src/components/ClientTeams.test.tsx` (the card's
controls and what each sends; the archive confirmation's words; the
invitation's three choices; the Team field on the two forms; the filter on
Work). **Not seen in a browser by anyone.**


---

## As built: phase 3 (2026-10-14) — the client owner sets teams up

**Seen by a client owner:** **Your team** in the portal's sidebar, under
"Your engagement", and on it the same Teams card the practice has on the
company's page. **Seen by every other client user:** nothing new. **Seen by
the practice:** nothing new; what a client owner changes shows on the
practice's card, and in the audit trail under the client owner's name.

**What the client owner can do** (`/team`, `frontend/src/screens/YourTeam.tsx`;
the routes are phase 2's `/api/client-teams/`, opened to them)

- Add a team, rename one (the default included), archive one, with the same
  confirmation of what moves to the default team. Nothing is deleted.
- Put a colleague on a team at a level (Viewer, Member, Manager, Senior
  leadership), change it, or take them off; make a colleague senior
  leadership of every team; set what a colleague may create.
- Each change takes effect at once, and is audited with the client owner as
  the one who made it, under the same verbs as the practice's.
- For their own company only. Another company of the same practice, its
  teams and its people, are not found; so is anything of another practice.
- It does not invite people or change seats (§4.2).

**Readings made while building, each Bryan's to overrule**

1. **"Your team" is a new page.** §4.2 places the card on "the page that
   lists the company's users today, and where 'Act as a colleague' lives".
   There is no such page: "Act as a colleague" is a picker in the account
   menu, and nothing in the portal lists the company's users. The card is the
   list now.
2. **A client owner's settings are the practice's.** A client owner does not
   change their own may-create, senior leadership or levels, nor another
   client owner's: the row says "set by <practice>", and the server answers
   403 with that sentence. Otherwise a client owner could give themselves
   "Goals too", which P7-7 makes something given deliberately.
3. **A client owner gives nobody more to create than they may create
   themselves.** With "projects and tasks" (everyone's today), "Goals too" is
   shown and not offered, and refused with a sentence if sent. Without this,
   "Goals too" given to a colleague would be the client owner's through "Act
   as a colleague". Lowering someone who has more is never refused. Once the
   practice gives the client owner "Goals too", they may give it.
4. **Any other client user is refused with a sentence, not "not found"**,
   on their own company's routes ("Only your client owner sets up your
   company's teams."): it is their company, and the role is what stops them.
   Phase 2 answered them 404. The teams' names, for a picker, are refused to
   them too until phase 4's screens ask for them.
5. **The client owner acting as a colleague has the colleague's reach,** and
   so no card, until they stop.

**Still phase 4** (the portal for everyone else): "Mine / My team /
Everyone"; a read-only sheet saying "Only <team>'s manager can change this";
"New" offering only what a person may create (it is still offered, and
answered with a sentence); the team asked for when someone on several makes
work; the assignee picker narrowed to the task's team (the server already
refuses the rest); a goal made by someone with "Goals too", and a senior
leader or the client owner editing a goal; P7-10's level names in the
portal's other places, the acting banner's "Client team member" among them.

**No migration in phase 3.**

**Proven by tests:** `tests/test_client_teams_portal.py` (the client owner
makes, renames and archives a team, sets a level, senior leadership and
may-create, each audited as theirs; a level they set taking effect on the
colleague's own routes; a client owner's settings refused, theirs and a
second client owner's; the may-create ceiling and its lifting by the
practice; every other level refused on every route, and the client owner
while acting as a colleague; another company and another practice not
found), the phase 2 test changed for (4), and
`frontend/src/screens/YourTeam.test.tsx` (the page and its card; the client
owner's row read-only and naming the practice; "Goals too" not offered, then
offered; a change sent for their own company; nothing asked for another
client user; "Your team" in the sidebar for the client owner alone). **Not
seen in a browser by anyone.**

**Fixed after Bryan's demo checks (2026-10-14):** the card's people table ran
past its edge in the portal, its pickers cut to "Mer" and "Projec" (the card
was held to a form's 720px); team changes were in the audit trail and not on
Activity, where they are now their own type, Team, with the acting practice
user named as on any acted entry; and "X on behalf of X stopped acting" names
X once.

---

## As built: phase 4 (2026-10-14) — the portal for everyone else

**No migration.** The rule was phase 1's; phase 4 tells the portal what it
says, and opens goals to the people §2 and §3 name.

**What the portal is told** (`/api/me` → `portal`, from
`ClientScope.describe`): the person's level by name, what they may create,
whether they edit goals, whether they get "Mine / My team / Everyone", the
teams they may put new work on, and whether "Propose a goal" is theirs. Every
one of these is also held by the server on its own.

**What each level sees now**

| | Lists | A sheet they cannot change | New | Goals |
|---|---|---|---|---|
| **Member** | Their own work, and the projects it sits in (no switch) | No edit controls; "Only <team>'s manager can change this." once at the top | What "may create" gives, on their team | See all, read-only |
| **Manager** | Mine / My team / Everyone (Everyone is the other teams, read-only) | Same line, on another team's work | Same, on their team; "which team?" if on several | See all, read-only |
| **Senior leadership** | Mine / My team / Everyone | Same line, on a team they do not lead | Same, on the teams they lead | **Change** a goal's title, description and target date |
| **Viewer** | Everything client-visible, read-only (no switch) | The line, everywhere | Nothing, whatever "may create" says | See all, read-only |
| **Client owner** | Mine / My team / Everyone | (changes everything on the client's side) | What the practice set; "Goals too" adds goals | Change, as senior leadership |

Work the practice owns stays the practice's at every level, with its own
line ("This task is the practice's to change…").

**Built**

- **Mine / My team / Everyone** on Work and Tasks (`?view=`), for a
  manager, a senior leader and the client owner. Narrows, never widens.
- **The read-only line,** `read_only_line` on a task and on a project,
  the same sentence the route answers with when it refuses.
- **New offers only what may be created;** a viewer is offered nothing.
  **Which team** is asked when the person may put work on more than one,
  starting at the default team if they are on it.
- **The assignee picker** lists only those the task's team may be handed
  to (`/api/portal-people/?team=`), never someone who only looks.
- **Goals:** "New goal" for "Goals too": live at once, "Added by <name>,
  <company>" on Work and on the goal, and on the practice's Activity
  ("added a goal for <company>: “…”"). A senior leader or the client owner
  edits a goal's title, description and target date. A goal a client added
  is deleted by its maker or the client owner.
- **Level names** in the portal: the account menu, Profile, the acting
  banner, and the people list. The practice's role picker still offers
  "Client team member", because it chooses the role, not the level.

**Readings made while building, each Bryan's to overrule**

1. **A client's part of a goal is its words and its date:** title,
   description, target date. The measure, the baseline and target, the
   outcome statement, the client owner and the status stay the practice's
   (Module 4B's judgement), refused with a sentence if sent.
2. **A goal a client added is deleted by its maker or the client owner**
   (as P7-13 has it for projects and tasks). A goal the practice set is never
   a client's to delete.
3. **"Propose a goal" stays the client owner's,** while they are not given
   "Goals too". Bryan's note reads "stays for everyone who is not given goals
   too"; only the client owner had it, so nobody else gains it.
4. **The switch starts at Everyone,** what each person sees today, and is
   remembered per person in their browser. "My team" is every team they are
   on, at any level; for the client owner and senior leadership of every
   team it is everything.
5. **A goal sheet carries no read-only line:** "Where we are" is unchanged
   (§4.3), and a goal is read-only to most people by nature.
6. **"Add a task here" on a project's page** is offered where the person
   may create tasks and may change that project.

**Proven by tests:** `tests/test_client_teams_phase4.py` (what each level is
told and called, the banner's level; the three views per level, never
widening; the read-only line and the refusal saying the same; the assignee
list per team; a goal added, marked, on Activity, held to its words; who
changes and deletes a goal; another company and practice not reached), the
phase 1 goal assertions changed for phase 4, and
`frontend/src/screens/PortalLevels.test.tsx` (New by may-create; the goal
form; which team, and that team's people; the switch and its requests; the
"Added by" marker; the banner's level). **Not seen in a browser by anyone.**
