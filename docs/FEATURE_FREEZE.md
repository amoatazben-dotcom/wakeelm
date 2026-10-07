# Final beta feature freeze

Baseline: Stage 7/8 implementation published at `d5c79530c046fdf4006a8da36934c326e9c04864` on main and `stage-7-8-routing-production-hardening`. Stage 9 branch: `stage-9-final-integration-beta`. Candidate identifier: `v0.9.0-beta.1`; this is not a created Git tag or a claim of readiness.

From this baseline changes are restricted to BUG_FIX, SECURITY_FIX, RELIABILITY_FIX, PERFORMANCE_FIX, LOCALIZATION_FIX, TEST_ADDITION, DOCUMENTATION and RELEASE_CONFIGURATION. No new model adapter, major UI, tool family, language/runtime or integration feature is added during stage 9.

Mandatory gates use PASS / FAIL / BLOCKED / NOT_APPLICABLE. A missing credential, deferred Railway deployment, blocked hosted CI or unresolved runtime vulnerability cannot become PASS. Evidence is local unless explicitly recorded as live. No beta tag, release or deployment is authorized by an unverified checklist.

Known baseline release blockers: runtime-image HIGH Debian findings without a reported fixed version, GitHub hosted Actions blocked by account billing, unconfigured real OIDC/provider/GitHub/MCP deployment credentials, and Railway/remote backups/production validator not provisioned while construction is deferred. Stage 9 must finish all independently executable work and describe these concrete remaining gates.
