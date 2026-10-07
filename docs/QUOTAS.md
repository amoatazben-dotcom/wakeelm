# Server-side plans and quotas

FREE, STANDARD, PRO and ADMIN policies are seeded in SQL, with per-user assignments and numeric overrides. All limits live in QuotaEngine/plan policy, not scattered constants. FREE defaults: 50 messages/day, 100k tokens/day, 10 jobs/day, 2 concurrent jobs, 100MB storage, 3 repository workspaces, 3 MCP servers, 5 synchronized GitHub repositories, $1 estimated daily/$5 monthly spend and 20MB upload. Higher tier values are visible in the policy migration and usage API.

Messages, model token/cost reservations, new jobs/concurrency, uploaded and expanded/indexed storage, repository imports, MCP additions and GitHub synchronization are enforced on the server. Reservations count until reconciliation, including interrupted calls. PostgreSQL locks serialize cap checks; aggregates avoid loading every historical row. Resource checks lock the owning user. Expanded archive size is checked after indexing in addition to compressed upload limits.

Telegram's Usage screen shows today/month totals, limits and unknown-price reservations. Admin/SUPER_ADMIN may change quotas; SUPPORT and READ_ONLY may not. Every change is independently audited. Existing application caps remain stricter upper bounds where relevant. Redis cannot authorize additional billable operations after SQL is unavailable.
