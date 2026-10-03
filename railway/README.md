# Railway service configuration (Phase 7)

One image (`Dockerfile`), three services. **Railway no longer accepts
config-as-code files** (2026-09-29: "deprecated, use `.railway/railway.ts`"),
so these JSON files are the written record of each service's settings, and the
settings themselves are applied to each service through Railway's API
(`serviceInstanceUpdate`): Dockerfile path, start command, health check,
restart policy, cron schedule. The start commands are scripts in `scripts/`,
because a quoted `sh -c '…'` start command was not run as written.

| Service | File | Runs |
|---|---|---|
| `web` (named **`execs-now-hq`** in the production project) | `railway/web.json` | `migrate_if_empty`: builds the schema on a brand-new empty database; on the demo (`APP_ENVIRONMENT=demo`) applies unapplied migrations; otherwise **refuses to start while any migration is unapplied**. Then the system checks, then gunicorn on 8080. Health check `/healthz`. |
| `qcluster` | `railway/qcluster.json` | the Django-Q2 worker, with the same unapplied-migration refusal. **No public domain.** Starts at 0 replicas and is scaled to 1 only at runbook C9. |
| `backup` | `railway/backup.json` | `scripts/backup_db_railway.sh`, nightly at 08:00 UTC (02:00 Mountain). |

Staging runs **`web` only**, from the `dev` branch. It never gets a qcluster
service (runbook B3).

The key names follow Railway's config schema as documented at the time of
writing. They have not been checked against a live project yet; runbook A1/B1
is where that happens. The variables each service needs are in
`docs/phase7_cutover_runbook.md` A4 and B1.

## Migrations are never applied by a deploy

A release that carries a migration deploys, web **refuses to start**, and
qcluster **waits**. The migration is then applied by hand inside the waiting
worker, the only active container running the new code:

    railway ssh --service qcluster -- python manage.py migrate

The worker starts by itself, and web is redeployed onto the new code. The full
sequence, including the backup check that comes first, is
`docs/phase7_cutover_runbook.md`, "Releasing a migration". It is the only way a
migration reaches production.

**The demo is the exception** (owner, 2026-10-02): its web applies its own
migrations at start. It deploys from `dev` with no worker, so it has no
waiting container to migrate from, and it holds only fictional data. The
command refuses if a demo setting ever meets production's host.
