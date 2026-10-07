# Recovery runbooks

DB loss: activate global external-write/new-job stops; pause bot/worker; restore encrypted snapshot to a separate empty DB; verify schema, ownership and decryption; restore private volume; test readiness and safe read-only workflows before cutover. Reconcile PENDING external actions with remote evidence, never blindly replay them.

Redis loss: pause billable work until Redis is healthy; SQL plans/approvals/usage/intents survive; expect disposable caches/rate limits/circuits and admin sessions to reset. Reacquire leases and mark interrupted work FAILED/review-required. Critical authorizations remain SQL. Ask admins to sign in again.

Worker crash: recover APPLYING changes from snapshots; keep failed-job evidence; reconcile unknown writes; resume only supported authentication-bound failures after fresh consent. Missing workspace volume: mark jobs for review and restore the corresponding private snapshot rather than inventing empty files.

Revoked GitHub credentials: disable provider/connection, cancel pending external writes, revoke app/PAT remotely, refresh installation authorization and reverify repository ownership before enabling. Compromised MCP: global/server write stop, disable capabilities, revoke tokens at issuer, discard cached discovery, review schemas/provenance and require newly bound approvals.

Encryption incident: pause writes; preserve encrypted DB/volume backups; provision new active key plus old keys; run `python -m scripts.rotate_keys` offline transactionally; verify old and new ciphertext; restart with retained previous keys; retire old keys only after backup retention expires. GitHub app/webhook/internal identity secrets rotate at the issuer/platform with bounded overlap.

Bad deployment: stop new jobs/writes, restore prior application artifact compatible with current schema, avoid automatic destructive downgrade, verify ready/version. Provider outage: circuits/fallback keep bounded; manual mode reports failure, never silently changes user selection. Record actual RPO/RTO from a drill; no production recovery time has been measured yet.
