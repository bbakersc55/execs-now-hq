# P17. Security updates, the routine, and the unused sign-in pages

Branch `security-updates`, cut from `dev` at `6517289` on 2026-11-27. Asked for
by the owner before signing the PCI questionnaire (SAQ A). Not pushed. The
routine it starts is in `docs/security_updates.md`.

## Plan

1. **The updates.** Every Python package with a known advisory to a fixed
   version; Django to the newest 5.2; the frontend build and test tools that
   have advisories. Nothing else, except what a fix needs. Then the code
   changes they need, and the drawn-signature path made PNG-only.
2. **A current image.** Base images pinned by digest; Debian's fixes installed
   afresh on every build instead of from a cached layer; a record in the image
   to check.
3. **The routine.** An audit step in the gate with a dated allow-list,
   Dependabot for Python, the frontend and the base images, and the written
   rule.
4. **The sign-in pages.** Django's admin off outside the laptop; allauth's
   pages reduced to the ones the sign-in uses, the rest "not found".
5. **The audits again**, the full gate, a commit, no push.

## Questions, and the default taken

1. *How far to update each package?* **The newest release in the same line
   that holds every fix** (DRF 3.18.3, pypdf 6.21.4, PyJWT 2.15.1, Django
   5.2.19, certifi 2026.11.20). Where the fix exists only in a new major version,
   that version: **Pillow 13.0.0, oauthlib 4.0.1, Vitest 4.1.12.**
2. *oauthlib 4 needs a newer allauth (65.19.2 allows only oauthlib 3).* **allauth
   65.22.0, the first release that accepts oauthlib 4.0.1**, not the newest
   (65.23.0).
3. *Moderate advisories too?* **Yes, every advisory, as asked**: OpenTelemetry's
   and urllib3's moderate ones are fixed by the same updates.
4. *Vitest 5 (npm's suggestion) or 4?* **4.1.12, the first fixed release.** It
   drops the flagged worker-pool library and runs on Vite 6. **Vite stays on 6**
   (6.4.3 to 6.4.6). The suite needed no changes.
5. *Dev-only Python packages?* **Audited too, and in the gate**: they run on
   the laptop. None had an advisory.
6. *How to make the build use current system packages?* Railway documents no
   switch to turn its layer cache off. **The commit Railway passes to the build
   (`RAILWAY_GIT_COMMIT_SHA`, declared as an `ARG`) is used by the
   system-package step, so the step runs again for every commit**, now with
   `apt-get upgrade`. The cost: that step and `pip install` after it run on
   every build, adding about a minute. The step writes
   `/etc/enhq-system-packages`. Not exercised here: this laptop has no Docker,
   and nothing was pushed. The demo's first build from `dev` will be the first
   proof (release steps).
7. *Pin the base images by digest?* **Yes**, to the digests Railway used for
   Release 54, which are still Docker Hub's current ones. Builds then use exactly
   what was tested, and Dependabot has a digest to move when Docker rebuilds the
   tag.
8. *The gate's Python audit: pip-audit or our own?* **Our own, standard library
   only**: OSV's batch API plus each advisory's record. pip-audit would add
   about a dozen packages to the laptop's pins for the same lookup.
9. *How the audit ranks.* **GitHub's severity on the advisory, or on its GHSA
   alias; unrated counts as high.** It blocks only when a fixed version exists,
   as asked. **Unreachable advisory service: the gate fails** ("couldn't
   check" isn't clean).
10. *The allow-list.* `scripts/audit_allowlist.toml`. **Each entry names the
    advisory (any alias), the package, a reason and two dates at most 30 days
    apart. An expired entry fails the gate. An unused one is reported.**
    Empty today.
11. *Dependabot, which updates?* **Version updates monthly, patch releases
    only, grouped into one pull request per ecosystem, against `dev`.** Minor
    and major versions are left to a decision. **GitHub's "security updates"
    (automatic pull requests) stay off**: GitHub opens them against `main`
    whatever the config says. Alerts are the trigger instead.
12. *Deadlines for moderate and low?* **The next monthly update, and within 90
    days.** Critical and high: 30 days, as asked.
13. *The admin: where does it still answer?* **On the laptop only**
    (`ADMIN_ENABLED = IS_LOCAL`), where `createsuperuser` is the documented
    exception. It answers "not found" in production and on the demo.
14. *Which allauth pages close?* **Every one the sign-in doesn't use**, not only
    password reset, password change and sign-up: also password set, email
    management, re-authentication, login by code, social connections and Google's
    token login. **Their names stay registered** (each leads to the 404), so
    allauth code building a link can't fail. Sign-up now answers 404, no
    longer our 403 page. A refused Google sign-in still lands on the 403 page,
    because the adapter sends it there first.
15. *allauth's own `/accounts/login/`?* It can't sign anyone in (no
    passwords). **It now redirects to our sign-in page**, since allauth's own
    pages link to it.
16. *The CLAUDE.md line describing the gate* ("runs the whole backend suite...")
    **is left as written**: it is the owner's rule text. The gate script and
    `docs/security_updates.md` describe the audit.
17. *The laptop findings (question 8)* are in the report, not in the repository.

## What changed

- `requirements.txt`: brotli 1.2.1, certifi 2026.11.20, Django 5.2.19,
  django-allauth 65.22.0, djangorestframework 3.18.3, oauthlib 4.0.1,
  opentelemetry-api 1.45.2, pillow 13.0.0, pyasn1 0.6.5, PyJWT 2.15.1,
  pypdf 6.21.4, urllib3 2.8.0. No package was added or removed; `pip check`
  is clean, and a fresh install matches the pins exactly.
- `frontend/package.json` and its lock: vite 6.4.6, vitest 4.1.12;
  source-map-js 1.2.4 (from postcss). The built bundle is byte-identical:
  the same entry file and integrity hash as Release 54's.
- `apps/esign/drawing.py`: one check for a drawn signature. The bytes must
  start with the PNG signature before Pillow is called, and Pillow is given
  only its PNG reader (`formats=["PNG"]`). Used by the signing page
  (`apps/esign/services.py`) and the owner-agreement page
  (`apps/agreements/services.py`), which had the same open-anything code.
- `Dockerfile`: digests; the per-commit system-package step with `apt-get
  upgrade` and its record.
- `scripts/dependency_audit.py`, `scripts/audit_allowlist.toml`, and the gate's
  new first step.
- `.github/dependabot.yml`.
- `config/urls.py`, `config/settings.py` (`ADMIN_ENABLED`),
  `apps/accounts/urls_allauth.py`.
- Tests: `test_drawn_signature_png.py`, `test_dependency_audit.py`,
  `test_security_updates.py`, `test_sign_in_pages.py`; `test_google_signin.py`'s
  sign-up test now expects 404.

## Report only: what was found

**Practice users and the email link.** In production nobody uses it: 2 live
practice memberships, both Practice owners. Bryan signs in with Google and has
never had an email link. Blue Sky's owner requested one once and never used it;
their last sign-in, 2026-10-05, came another way. What relies on it:

- **The demo's visitors.** Each is the Practice owner of their own copy. They
  arrive by an invitation link (`apps/tenancy/demo/visitors.py`) and come back
  through "Email me a sign-in link".
- The laptop's `dev_va_login`.

Google-only would cut the demo visitors off. The narrow fix: refuse an email
link to a practice role outside the demo and the laptop. That's about an hour,
with tests.

**Two-step sign-in.** It isn't installed; allauth's own (`allauth.mfa`) is
available. Four routes sign a practice user in: allauth's Google callback, the
External Google client, Microsoft and the email link. The last three call
Django's `login()` directly, so one gate after login is needed, not allauth's
alone. The work:

- enrolment (an authenticator app, plus recovery codes);
- a code step after every staff sign-in, before any page or API answers;
- the rule: required for the platform owner and anyone with See full tax
  numbers, optional for the rest;
- the reveal code moving from email to the authenticator for those people;
- a reset by the platform owner, and the platform owner's own recovery by
  recovery codes;
- tests across the four routes.

About the size of P16: two to three working sessions, plus a walk. Google
can require two-step at Google's end, but ENHQ can't see whether it did,
which is why the code step belongs in ENHQ.

**Card numbers in free text.** Where one typed or emailed in would be stored:

- notes (body, transcript, summary);
- task comments and descriptions;
- inbound and outbound email: `EmailMessage.body_text`, `body_html` and `raw`
  (the provider's whole message), with attachments in the media bucket;
- form answers: intake `answers`, owner agreements, pre-call and strategy
  answers;
- meeting notes and proposals;
- SOPs, plans and documents;
- AI tool runs.

Anything sent to Claude for a summary also goes to Anthropic. Nightly backups
keep copies for 30 days.

The smallest safe catch is one function at the write boundary of those fields:
runs of 13 to 19 digits with spaces or dashes between them, a card brand's
prefix, and a passing Luhn check, masked to the last four ("•••• 1111").
Applied:

- when text is saved (a model mixin on the listed fields);
- when inbound mail is stored, to the body and `raw`;
- before text is sent to Claude.

What could go wrong:

- False positives: about one random 16-digit number in ten passes Luhn, so a
  tracking number or account number with a brand prefix would be masked, and
  that loss is permanent.
- Misses: numbers split across lines, spoken ("four one one one"),
  photographed, or inside PDF and image attachments.
- Text already stored needs a one-off sweep, and the backups still hold it
  for 30 days.
- Searches and AI drafts made before the mask keep their copies.

**The buckets.** Both are private:

- `execs-now-hq-media` and `execs-now-hq-db-backups` have public access
  prevention enforced and uniform bucket-level access.
- Neither grants anything to `allUsers` or `allAuthenticatedUsers`.
- Access: the project's owners, editors and viewers (one owner, a user) and
  one service account each with object admin (the media bucket also has a
  read-only one).
- Deleted objects are kept 7 days (soft delete).

Uploaded files are never served from the bucket. The app reads each one with
its service account and returns it from its own view, after that view's
permission checks; there are no public or signed links.

## Release steps

No migration: allauth 65.22 brings none, and the laptop's database has
nothing unapplied.

1. **Merge and push `dev`** (on a yes): `security-updates` fast-forwards onto
   `dev`. The demo then builds the new `Dockerfile` first, before production
   sees it. Check three things on the demo:
   - Its build log has "system packages for commit <the commit>" followed by
     apt's `Get:` lines. That shows the step ran rather than coming from the
     cache.
   - `railway ssh -p 792ddb0f-a2fb-45a0-9034-fafca1d4d81f -e production -s
     execs-now-hq -- cat /etc/enhq-system-packages` shows `commit=<the
     commit>`, today's `built=` and `still_upgradable=0`. If it says
     `commit=unknown`, Railway didn't pass the commit: stop there.
   - `/admin/` and `/accounts/password/reset/` answer 404, and a demo
     visitor's email link still signs them in.
2. **Release by the runbook**:
   - R1, the day's backup.
   - R2, `git fetch . dev:main && git push origin main`.
   - R3 and R4: nothing to apply; the worker shouldn't wait.
   - R6, web and `mcp` up by themselves. The build is about a minute longer
     than before.
3. **Check production**:
   - `cat /etc/enhq-system-packages` in web, as above.
   - `/admin/`, `/accounts/password/reset/` and `/accounts/signup/` answer 404,
     and `/accounts/login/` redirects to `/`.
   - Google sign-in, and a client's email link.
4. **The card pages (R6b).** Run `card_pages check`, then `card_pages
   approve --note "Release N: security updates" --by "Bryan"` if it reports
   any change. The approval covers the app's script files and the headers.
   Built on the laptop, the bundle was byte-identical to Release 54's, but the
   build Railway makes is the one that counts.
5. **GitHub**, once: switch on the dependency graph and Dependabot alerts,
   and leave "Dependabot security updates" off (`docs/security_updates.md`).
