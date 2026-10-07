# Encrypted backup and restore

Run `python -m scripts.backup_restore backup /private-backups/snapshot.enc` in a dedicated trusted backup runner with DATABASE_URL and a separate BACKUP_ENCRYPTION_KEY. The runner needs PostgreSQL client tools at least as new as the server. Native credentials are passed only through the child environment, never command arguments/logs. The `--docker-container` option is for isolated local fixtures only.

Backups are PostgreSQL custom format encrypted with a separate Fernet key. Sidecar metadata records timestamp, app/schema version, source database name, checksum and encrypted size, never credentials or the master key. Files are private and existing snapshots are never overwritten. Dumps have time and size bounds. Keep MASTER_ENCRYPTION_KEY and retained previous keys in a separately protected recovery vault; a dump alone cannot decrypt provider credentials.

Schedule daily backups, retain 7 daily/4 weekly/3 monthly snapshots, upload to a private durable object store and verify retention there. Scheduling/object storage has not been provisioned while Railway is deferred. Alert on nonzero backup exit, missing newest snapshot or stale restore drill. This repository automates dump/encryption/restore, not an imaginary remote backup service.

Restore with `python -m scripts.backup_restore restore snapshot.enc` and an empty DIFFERENT database. The script rejects the source database, nonempty targets, oversized or tampered files; restores in a single transaction and verifies schema. Reconnect a staging app, verify owners/encrypted credentials/jobs/approvals/flags/usage, test readiness, then separately restore private workspace storage. Never restore into the live database first.

The automated drill creates two isolated PostgreSQL databases, upgrades stage 5/6 user data, dumps/encrypts/restores to the second, and verifies preserved identity, decryption and schema. Actual external scheduled backups remain BLOCKED pending deployment configuration. Repeat drills monthly and before each release/migration. SQL backups do not substitute for workspace volume backups.
