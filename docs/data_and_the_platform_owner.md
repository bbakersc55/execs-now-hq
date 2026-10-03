# Data and the platform owner

**What the platform owner can and cannot see · P2, 2026-10-02**

Execs NOW HQ runs many practices. The **platform owner** (one person in Beta,
Bryan Baker) creates and archives practices. **The app gives the platform
owner no view inside any practice.**

## What the platform owner sees

In the Practices area, for each practice:

- its record: display name, legal name, domain, status, created date;
- its totals: number of staff, number of client companies, AI spend this
  month, date of last activity;
- the feedback its staff chose to send with the Feedback button: the
  practice's name, the sender's role, their three answers, the page they were
  on, and a screenshot if they attached one.

That's all. No contacts, companies, tasks, goals, notes, emails, meetings,
strategy sessions or files.

## How that is enforced

- **No practice is bound in the Practices area.** Every query for practice
  data fails closed, through the same mechanism that keeps one practice from
  seeing another's.
- **One module counts, and returns only numbers and dates**
  (`apps/platform/stats.py`). **One module reads feedback, and returns only
  the feedback** (`apps/platform/feedback.py`). A test fails if any other
  platform code names a model that holds a practice's data.
- **The isolation tests include the platform owner.** They plant recognizable
  data in a practice, call every API route as the platform owner in the
  Practices area, and check that none returns it.
- **There is no support-grant feature**, and no way in the app to "view as" a
  practice. The platform owner's own practice is the only one they belong to.

## What code cannot promise

Anyone who operates the servers (the Railway database and the Google Cloud
backups) can technically read the database directly. The beta agreement says
so (clause 2): we don't, and we restrict that access to what is needed to run
and back up the service.
