# Stage 7/8 implementation report

Date: 2026-10-07. Branch: `stage-7-8-routing-production-hardening`. Application: 0.8.0. Software implementation and local acceptance are delivered; operational release status is **NOT_READY_FOR_PRODUCTION**. Railway has not been started, following the explicit construction/deployment sequencing instruction.

## Delivered components

1. New routing package: structured requests/decisions, bilingual task classifier, normalized capability/health/context/price scoring, all eight selectable policies, optional one-call TTL capability probes and bounded classified fallback.
2. Shared gateway integrated into chat/project answers/planning, per-role model policy, persistent cost/token/call/duration budgets and shared circuits. Manual selection/fallback preferences remain user-controlled.
3. Persisted specialist DAG with structured results and explicit dependencies; coordinator, analysis, implementation, review, test, security, documentation, research and integration responsibilities. Role limits remain subordinate to existing ownership/mode/hash/approval/sandbox policy.
4. Encrypted scoped memory layers, validation/deduplication/expiry/provenance, progressive extractive conversation compaction, project context integration, task/step receipts and exact-context compression.
5. PostgreSQL usage reservations and aggregate quotas, seeded plan policies/flags, emergency controls, per-user plans and overrides, resource/upload/index/repository/integration limits. Cost estimates remain distinct from actual billing.
6. Structured safe logs, W3C traces, bounded Prometheus metrics, sanitized error sink, health/readiness/version, retained failures, safe restart and durable PR/MCP write intents.
7. OIDC+PKCE+state+nonce+RS256 issuer/audience/expiry/MFA, encrypted short secure sessions, RBAC, CSRF/Origin, audit and metadata-only admin API. Static React/TypeScript operations UI: Arabic/English, RTL/LTR, live jobs/usage/health/audit and authorized operational controls.
8. Versioned encryption envelopes with legacy/key-overlap reads, offline transactional rotation, encrypted pg_dump/empty separate-target restore, retention/data-deletion workflow and incident/disaster/release runbooks.
9. Multi-stage non-root runtime image, TypeScript build only, pinned dependency lockfiles, dedicated serialized migrations, readonly SHA-pinned Python/admin CI and source/history/SAST/dependency/container scans.

## Database migrations

- `8c248b07f28e`: memory, graph, usage, plans/assignments, flags, admin identities/audit.
- `a4bcb8ee6bcb`: durable encrypted external-action receipts.
- `771dc45faaa3`: distinguish known/unknown price estimates from actual billing.
- `b86da35fba71`: idempotently seed flag/plan controls without overwriting operator changes; downgrade retains seed/custom data until the earlier table removal.

User data upgraded from stage 5/6 and restored into a second isolated PostgreSQL database. Application startup/readiness and schema metadata against restored data are exercised by `tests/test_recovery_stage8.py`.

## Verification evidence

- Full real PostgreSQL/Redis/Docker sandbox suite: 239 tests passed before the final small redaction/boundary additions; current final counts are recorded by the stage 9 report. No skip is claimed as a pass.
- TypeScript compile + production Vite build, 3 client tests and 2 real Chromium Arabic/English/RTL/auth/role scenarios passed.
- Routing policies/fallback/evidence, scoped memory/secret rejection, real specialist tools/DAG/no replay, budget/quotas/flags/circuits, OIDC claim/signature/MFA/nonce, admin authz/CSRF/audit, account cleanup, PR repeat suppression and existing stage 1–6 regressions are tested.
- Isolated load: 100 controlled-provider requests, concurrency 10, 0 errors; p50 62.267ms, p95 206.146ms, p99 245.613ms; 100 durable completed records, 1,500 tokens. This is local controlled latency, not production capacity. Raw resource/queue measurements: `release-evidence/stage8-load.json`.
- pip-audit: no known Python dependency vulnerabilities. npm audit: 0 findings. Bandit: no untriaged medium/high findings; B104 explicitly documents the required container listener.
- Gitleaks source and full Git history: no leaks. Actual runtime image scan after removing build-time pip/vendor packages: **55 HIGH package findings representing 16 distinct Debian CVEs; 0 CRITICAL; no fixed version reported**. No blanket ignore or false PASS. Raw evidence: `release-evidence/stage8-container-audit.json`.

## Acceptance mapping

Stage 7: all 20 software acceptance categories are covered by routing/service/agent/memory tests and existing real integration/sandbox regressions. Core source directories and the detailed router/multi-agent/memory/cost documents specify exactly which bounded techniques are used. Optional semantic backends and unsupported capability probes are not invented features.

Stage 8: logging/tracing/metrics/readiness, bounded retries/write receipts, accounting/quotas/caps, admin/RBAC/bilingual UI/RTL, flags/stops, redaction/rotation, backup/separate restore, cleanup/retention, circuits/degradation, version/migration process and incident runbooks are implemented and locally exercised. Healthy **production Railway deployment is BLOCKED**, not passed. Runtime vulnerability gate is **FAIL** pending upstream fixes/risk resolution. Hosted CI execution is **BLOCKED** by the pre-existing GitHub account billing lock. Live OIDC/provider/App acceptance and remote scheduled backup configuration need deployment credentials/configuration.

## Runtime/services and limitations

Python 3.13 remains the sole runtime control plane; PostgreSQL/Redis and private filesystem persist state. Node 24/TypeScript/React is only frontend build/test and static assets; no privileged Node service, Rust or Go component was justified by measurements. Trusted Git supplies repository runtime. The architecture includes no fictional deployed service/exporter/store.

Model classifiers/scores and extractive memory are bounded heuristics, not verified intelligence/quality benchmarks. JSON probes demonstrate bounded JSON output, not all provider response-format extensions. Unknown cost is conservatively reserved and reported as unknown. No billing provider is integrated. Metrics/traces have a pluggable/Prometheus-compatible local implementation; external collection and alert/on-call destinations are not provisioned. Source/image/client tooling is verified locally; production validator, volume ownership, real OIDC enrollment and scheduled remote backups remain release configuration gates.

The next stage freezes features and audits release gates. Do not tag/deploy a beta while the image/hosted-CI/live-configuration/deployment gates are unresolved.
