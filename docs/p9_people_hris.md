# P9 — the People Command Center, with an HRIS (decided 2026-11-12, not built)

**Status: decided, not built.** Bryan decided the scope on 2026-11-12. Nothing
here is in the code yet. It comes third in the build order:

1. the SkyRun bonus;
2. the rest of the Operations Command Center (the SOP studio, the plans
   engine, the worksheet engine with four tools and the tool builder, the
   connector rails);
3. **People, with the HRIS** (this spec);
4. Technology.

People is the second Command Center, in the frame `docs/p8_command_centers.md`
built (its catalog row is already there, "coming", marked "Next"). This takes
the place of the "simple HRIS" in `CLAUDE.md`'s post-Beta list.

## Who sees what

- **The practice manages the employee records** of each client company.
- On the client's side, in the portal:
  - **the client owner and senior leaders see everyone**;
  - **a manager sees their direct reports**;
  - **each employee sees their own record**.

## The employee record

A record holds:

- name;
- contact details;
- address;
- emergency contact;
- title;
- team;
- manager;
- employment type (**contractors included**);
- work state;
- start date;
- status;
- pay rate;
- documents.

### Offer letters

- Offer letters go through **the app's own e-signature** (`docs/p6_esign.md`).
- **A signed offer creates the employee record and starts onboarding.**

### Never stored

The app never stores any of these:

- bank details;
- Social Security numbers;
- I-9 documents;
- medical and leave paperwork;
- background checks;
- benefits.

The employee gives those to the payroll provider directly. Where the app shows
one at all, it shows **only the masked last four, read live** from the
provider and never kept.

## Onboarding and offboarding

- **Checklists in three sections: People, IT and Manager.** Each section has
  standard items, and each client adds **custom fields of its own**.
- **Each employee has an access list** of the systems they use.
- **Offboarding builds the revoke tasks from the access list.**
- **Offboarding never terminates anyone in payroll automatically.** Payroll
  is changed by a person, in the payroll provider.

## Security

- **Two-factor sign-in by authenticator app, with backup codes.** It is
  **required for anyone with an HR permission**.
- **Everyone is signed out after 12 hours.**
- **People screens ask for the code again after 4 hours.**
- **HR access is a permission, not a role.** Two to start:
  - **HR Director** sees everything the app holds;
  - **HR Generalist** sees the sensitive fields masked.
- **Pay and personal fields are encrypted.**
- **Every view and every export is logged.**
- **Connected AI apps never see People data.** No MCP tool reads it
  (`docs/p7_mcp.md`).

## The state rules library

- **The first five states:** Utah, California, Colorado, Arizona and Nevada.
- **Thirteen topics** per state.
- **Each rule links to the state's own source** and carries a **last-verified
  date**.
- **Re-checked every quarter**, with **Bryan approving any change** before
  it shows.
- **Every People screen says "HR guidance, not legal advice".**

## The six rated areas

1. Hiring
2. Onboarding and offboarding
3. Pay and benefits
4. Performance
5. Managers
6. Compliance

## Pulse surveys

- **Anonymous or named, chosen per survey.**
- **An anonymous survey's results show only after five responses.**

## Price

- **The HRIS is included in the People Command Center** at $50 a month.
- **Employees count as client users**, at **$10 per block of 25**.

## Later

- **Version two:** time off.
- **Version two or later:**
  - an applicant tracking system;
  - the Gusto connection;
  - the QuickBooks connection.
- **Gusto's partner program** needs a pre-approval and a security review. The
  security work above is built so it doubles as that paperwork.

## Open, to settle before the build

These are not decided. They are not guesses at answers, just the gaps.

1. **The thirteen topics.** The decision fixed how many there are, not their
   names. They are written here before the library is built.
2. **Where "the masked last four, read live" comes from in version one.**
   It is read from the payroll provider, but the Gusto connection is version
   two or later. Until a connection exists, version one either shows nothing
   there or reads from another provider; which one is not decided.
3. **"Everyone signed out after 12 hours."** Today, staff are signed out
   after 12 hours **without activity**, and client portal sessions last 30
   days (handoff, "From Release 5"). Not decided:
   - whether 12 hours is counted from sign-in or from the last activity;
   - whether it covers every practice's client users, or only where People
     is on.
4. **Who holds the HR permissions.** Not decided whether only client users
   hold them, or the practice's own people as well.
