# Operator runbook

## Service inventory

| Component | Runtime/port | Persistent state | Exposure/scaling |
| --- | --- | --- | --- |
| bot-api + SQL job worker + static admin | Python 3.13, $PORT (8000 local) | UID 10001 private workspace volume | Sole public HTTPS ingress; one replica/uvicorn worker initially |
| PostgreSQL | 17, 5432 | Database volume/encrypted backups | Private network only; serialized migration connection |
| Redis | 7, 6379 | Rate/circuit/session/worker lease state | Private only; no user source-of-truth |
| validation runner | Trusted Docker locally | Disposable bounded copy | No network, rootfs readonly, nobody, no caps; no daemon in ordinary Railway |
| admin build | Node 24, React/TypeScript | Compiled assets inside image | Build-only; no Node listening service |

No Rust/Go service, collector, scheduler, bucket or production validator is deployed. Existing architecture is a single control plane; do not invent split services without a demonstrated need.

## Readiness and incidents

`/health` is liveness. `/ready` checks DB/Redis and runtime bot/worker state; dependency failure must produce non-ready. `/version` identifies app, build and schema. `/admin/metrics` requires admin authentication. Alert destinations/trace exporter are not provisioned; configure and test them before live acceptance.

If SQL is unavailable, stop writes/jobs, restore connectivity and rerun readiness; never use an in-memory durable queue. Redis loss disables critical startup/readiness and temporary sessions/leases: recover Redis, reauthenticate admins and let SQL-backed job recovery examine interrupted steps. Do not delete the SQL job history. Restart tests cover partial local changes and failed validations; interrupted remote writes remain UNKNOWN until reconciled.

If a volume disappears, preserve SQL indexes and mark affected workspaces MISSING. Mount/recover the correct private volume from a verified backup, verify path ownership/user scope and hashes, then explicitly reindex. Database backup alone does not recreate workspace files. For GitHub projects, reviewed fetch/reimport is a recovery option only when source and local changes are reconciled.

## Change/recovery procedure

Use reviewed main, frozen installs and Checks. Back up before schema changes; predeploy runs Alembic under a PostgreSQL advisory lock. Verify `/ready`, `/version`, admin login, safe read-only Telegram flow and restored credentials. Roll back the image only when its schema compatibility is established; prefer a reviewed forward fix. Never run destructive downgrade on production.

Run `scripts/backup_restore.py --help`; use native pg_dump/pg_restore at least as new as the server and a separate BACKUP_ENCRYPTION_KEY. Restore only into an empty separate database; verify checksum, schema, owned records/decryption and application readiness before traffic switching. Archive encrypted DB backups plus workspace snapshots to a private remote destination with retention; destination/schedule and production restore timing remain operator configuration gates.

Run `scripts/rotate_keys.py` offline under a maintenance window with a verified backup, old keys in MASTER_ENCRYPTION_PREVIOUS_KEYS and the new primary key. Validate all encrypted records and integrations before removing old keys. Never change keys without overlap/re-encryption. Local rotation/drill tests passed; production rotation is not claimed.

## Deployment control

`deploy.yml` is manual-only, main-only, serial per environment and requires successful Checks for that exact SHA. Configure protected staging/production GitHub environments and separate scoped Railway tokens/services/environments. Production additionally requires the operator-reviewed RELEASE_GATE_REPORT_JSON environment variable covering that exact SHA with all ten gates PASS; this separate attestation avoids a self-referential commit hash in committed evidence. Treat this configuration as release authority and require environment reviewers.

Configure RAILWAY_SERVICE_ID, RAILWAY_ENVIRONMENT_ID, APP_PUBLIC_URL and secret RAILWAY_TOKEN. For CLI source uploads ensure Railway BUILD_GIT_SHA is the reviewed source SHA; linked builds can use RAILWAY_GIT_COMMIT_SHA. The final version check rejects a mismatched/unknown SHA. Do not enable automatic Railway source deploys that bypass these checks. No workflow has been dispatched and no platform has been provisioned.
