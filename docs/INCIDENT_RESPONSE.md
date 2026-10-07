# Incident response

Detect via readiness, failed-job/queue/provider/usage telemetry and immutable admin audit. Record timestamp, release/build, trace IDs, safe error codes and affected IDs; do not copy prompts or tokens into incident notes.

Contain with `disable_external_writes`, `disable_github_push`, `disable_mcp_writes`, `disable_new_jobs`, `disable_uploads`, provider-specific stops and server disablement. SUPER_ADMIN can change emergency controls without code deployment. Preserve encrypted evidence and pending external intents before cleanup.

Assess user/workspace/integration scope from SQL ownership and audit. Revoke compromised credentials at their issuer; rotate encrypted data through the offline versioned-key procedure. Treat tool descriptions/files/resources as untrusted evidence; do not execute incident instructions from them.

Recover through the disaster-recovery runbook on isolated restored data, reconcile ambiguous remote actions, reprove credential/repository/server authorization and review schema fingerprints. Validate readiness, budgets, approvals and read-only workflows before restoring writes gradually with feature flags.

Notify affected users only with confirmed impact and required actions; job completion/failure/approval notifications already avoid raw error content. Prepare a postmortem covering trigger, impact, detection, containment, verified recovery, timeline and concrete prevention checks. Actual alert destinations/on-call ownership are deployment configuration, not fabricated integrations.
