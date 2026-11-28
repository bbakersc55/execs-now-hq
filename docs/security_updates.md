# Security updates: how ENHQ stays current

Written 2026-11-27 for the processor's PCI questionnaire (SAQ A), and kept as the
rule. It covers what ENHQ itself runs: its Python packages, its frontend
packages, the base images it is built on and their system packages. Railway runs
the servers and the Postgres database; their updates are Railway's (below).

## Where alerts come from

1. **The gate, on every commit** (`scripts/gate.sh`, its first step,
   `scripts/dependency_audit.py`). It checks every pinned Python package
   (production's and the laptop's) and every frontend package that reaches a
   browser against the public advisory databases: OSV for Python, npm's for the
   frontend. A known high or critical advisory with a fixed version stops the
   commit. So does an audit that couldn't reach those databases: "couldn't
   check" doesn't count as clean.
2. **GitHub's Dependabot alerts**, between commits. GitHub emails the repository's
   owner and lists the alert under the repository's Security tab the day an
   advisory names a package we pin. These are the alerts that start the clock
   below when no commit is being made.
3. **Dependabot's monthly pull requests** (`.github/dependabot.yml`), against
   `dev`: the month's patch releases of what we pin, one pull request each for
   Python, the frontend (build and test tools included) and the two base
   images. They keep small updates from building up into a big one.
4. **Every production build** installs Debian's current security fixes on top of
   the base image (`apt-get upgrade` in the `Dockerfile`, run afresh for every
   commit) and writes what it did to `/etc/enhq-system-packages` in the image.

## How they are ranked

By GitHub's severity, which every advisory source here uses: **critical, high,
moderate, low** (from the advisory's CVSS score). An advisory with no rating is
treated as high until it has one.

## How fast

| Rank | Live in production within |
|---|---|
| Critical | 30 days of the alert, sooner when it's reachable from outside (a page anyone can open) |
| High | 30 days of the alert |
| Moderate, low | With the next monthly update, and within 90 days |

"Live in production" means released by the runbook, not just committed. The
clock starts at the first of: GitHub's alert, a gate that fails on it, or a
monthly pull request that carries the fix.

## Who does it

- **Bryan, the owner**, is responsible for the deadline, reads GitHub's alerts,
  and says "release".
- **Claude Code** makes the change on a branch from `dev`: the update, any code
  change the new version needs, the tests, and the full gate. It writes what it
  did in `docs/handoff.md`, and at the release runs the runbook's steps.
- A Dependabot pull request is never merged on GitHub, where no gate runs. Its
  change is made on `dev` through the gate; Dependabot then closes it by
  itself.

## Exceptions

A high or critical advisory that can't be fixed at once (the fixed version needs
work, or doesn't run on our Python yet) goes in `scripts/audit_allowlist.toml`:
the advisory, the package, the reason, and dates at most 30 days apart. The gate
then passes it, and fails again when the entry expires. An exception buys time;
it doesn't move the 30 days.

## What this doesn't cover

- Railway's servers, its build system and the Postgres server itself: Railway
  keeps them current (Postgres 18, Railway-managed). Major Postgres upgrades
  are a decision with their own runbook.
- The gateway's Collect.js and card fields: NMI's, under NMI's PCI compliance.
  The card pages' script check (`docs/p16_card_page_scripts.md`) notices when
  they change.
- Python, Node and Debian themselves moving to a new version (3.13, Node 26,
  Debian 13): Dependabot proposes only new builds of the same tags. Debian 12
  left Debian's regular security support in June 2026 and is now under Debian
  LTS, which still publishes its security fixes, so the move to Debian 13 should
  be planned before Debian 12's LTS ends (June 2028).
- The laptop's own operating system and tools: the owner's.

## GitHub settings this needs (once)

Repository → **Settings** → **Advanced Security** (under "Security"):

1. **Dependency graph**: Enable. It must be on for anything below to work.
2. **Dependabot alerts**: Enable. These are the emails and the Security tab.
3. **Dependabot security updates**: leave **off**. GitHub always opens these
   pull requests against the default branch, `main`, outside the release flow.
   Alerts plus the monthly pull requests against `dev` do the same job without
   reaching `main` outside a release.

The monthly pull requests start by themselves once `.github/dependabot.yml`
reaches the default branch, `main`, at the next release.
