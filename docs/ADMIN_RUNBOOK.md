# Admin runbook

The browser UI is served at `/admin-web/` by the Python service. Authentication is the configured HTTPS OIDC provider with PKCE/state/nonce, issuer/audience checks and MFA. Bootstrap only reviewed subjects with ADMIN_SUPER_SUBJECTS; never use a shared password or put provider tokens in browser storage.

Start with overview health, queue, usage and bounded audit metadata. Readonly/Auditor inspect; Support handles user/job metadata; Admin controls operations/quotas; Super Admin alone manages identities and irreversible data deletion. Backend authorization is authoritative even when buttons are hidden. Cookie writes require CSRF plus the exact Origin; sessions expire after 900 seconds by default.

To contain an incident, turn off the relevant global flag (new jobs, provider calls, GitHub or MCP writes, uploads), record the incident and review the immutable admin audit receipt. Cancel active jobs and wait for acknowledgment; cancellation is not a rollback of an already completed remote write. Reconcile UNKNOWN/PENDING external writes manually with the provider before any retry. Disable a compromised account and revoke its issuer sessions/connected credentials.

Adjust a user's plan/overrides only after reviewing usage and estimated-vs-unknown prices. Costs are estimates, not invoices. An unhealthy provider may be disabled; manual routing must remain explicit. Do not enable writes just to bypass unavailable validation.

Deletion requires Super Admin and the explicit target ID confirmation. It cancels jobs before deleting credentials, private files and memory; minimal inactive pseudonymous audit linkage remains. Export/backup and required retention must be handled before deletion according to operator policy.

Troubleshoot a 401 by checking issuer/audience/MFA/expiry and exact HTTPS callback configuration; a 403 by checking RBAC, disabled identity, CSRF and Origin. Never capture callback codes, cookies, secrets or raw private prompts in a support ticket. See SECURITY_OPERATIONS and INCIDENT_RESPONSE.
