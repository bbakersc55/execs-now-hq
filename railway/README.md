# Railway service configuration (Phase 7)

One image (`Dockerfile`), three services, each pointed at its own file under
Railway → service → Settings → **Config-as-code path**:

| Service | File | Runs |
|---|---|---|
| `web` | `railway/web.json` | `migrate_if_empty`: builds the schema on a brand-new empty database, and otherwise **refuses to start while any migration is unapplied**. Then the system checks, then gunicorn on 8080. Health check `/healthz`. |
| `qcluster` | `railway/qcluster.json` | the Django-Q2 worker, with the same unapplied-migration refusal. **No public domain.** Starts at 0 replicas and is scaled to 1 only at runbook C9. |
| `backup` | `railway/backup.json` | `scripts/backup_db_railway.sh`, nightly at 08:00 UTC (02:00 Mountain). |

Staging runs **`web` only**, from the `dev` branch. It never gets a qcluster
service (runbook B3).

The key names follow Railway's config schema as documented at the time of
writing. They have not been checked against a live project yet; runbook A1/B1
is where that happens. The variables each service needs are in
`docs/phase7_cutover_runbook.md` A4 and B1.

## Migrations are never applied by a deploy

CLAUDE.md's rule holds in production: SQL first, and applying depends on the
migration being additive, the suite being green, and a backup having run today.
A deploy that applied migrations by itself would skip all three. So a release
that carries a migration deploys, **refuses to start**, and the migration is
applied deliberately, after that day's backup:

    railway ssh --service web      # a shell inside the running service
    python manage.py migrate

(`railway run` would run it on the laptop with Railway's variables, and the
private `DATABASE_URL` does not resolve from outside Railway. The exact CLI
form is to be confirmed at runbook B2.)

Then redeploy (or restart) `web` and `qcluster`. The old version keeps serving
until the new one passes its health check, so a refused start does not take
the app down.
