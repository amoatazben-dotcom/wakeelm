# Failure containment and restart

The existing PostgreSQL job queue/steps/approvals remain authoritative. Redis contains cooldowns, event caches, circuit state, cancellation hints and leased worker/workspace locks; unique plans, receipts, approvals, budgets and integration intents are SQL. A single renewed worker lease coordinates replicas. Lease loss cancels the worker; standby replicas do not recover a live owner's job.

Retries/replans/repairs/model fallbacks are bounded. Failed jobs are retained until artifact retention, rather than an unbounded requeue. Interrupted local patch batches roll back encrypted snapshots. Remote writes are never replayed automatically after ambiguous interruption. Git push is bound to the approved branch and SHA. PR creation saves a durable intent before HTTP and a result after success; replay returns a known result, while PENDING requires reconciliation. Reviewed MCP writes use encrypted SQL result receipts with the same fail-closed rule. Authentication failures proven before a write may resume after fresh user authorization.

Provider/model circuits use CLOSED/OPEN/HALF_OPEN behavior with a single bounded probe lease. Integration HTTP has separate origin/tenant circuits and never retries writes automatically. Exact search survives semantic unavailability; core local coding survives MCP outage; router fallback survives an individual model failure. Risky validation stays disabled unless an actual isolated sandbox is available.

Retention runs hourly under the worker lease and a dedicated lock. Deleted user data removes private workspace files and credentials/memory/connections, cancels active jobs first, and leaves only an inactive pseudonymous tombstone and policy-retained audit. No active workspace is silently removed during a job.
