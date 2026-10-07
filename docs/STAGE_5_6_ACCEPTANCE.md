# Stage 5/6 acceptance mapping

This maps the supplied prompt to implemented behavior and controlled verification. Live owner-account credentials and Railway deployment remain separate operational acceptance; deployment is deferred by explicit instruction.

| Prompt | Implementation / evidence |
| --- | --- |
| 5.1–5.2 | GitService protocol and bounded Linux ControlledGitService. Optional Rust omitted with documented rationale. |
| 5.3–5.5 | Native typed GitHub service, App user/installation authorization, verified RS256 App JWT, repository-scoped ephemeral tokens and scoped PAT fallback. Valid and expired token tests. |
| 5.6 | Eight Stage 5/6 integration tables in tested Alembic migration; three are GitHub ownership/repository links. |
| 5.7–5.9 | Bilingual connection chooser, pages/search/metadata, private one-use callbacks, signed idempotent webhooks and authorized repository discovery. Telegram/ASGI/API fixtures. |
| 5.10 | Real controlled bare-repository clone plus Stage 3 indexing; credentials excluded from origin/config. |
| 5.11–5.12 | Sanitized agent branches, protected/default ref rejection and stale SHA checks; explicit import-current-base action. No silent rebase/overwrite. |
| 5.13–5.15 | Existing orchestrator/patch/validator/registry. Complete acceptance test runs existing patch engine and actual Docker validation, then separate commit approval. |
| 5.16 | Separate push approval; exact branch/SHA/file/digest checks and scan; downloadable base-to-worktree diff on approval card. No force/mirror/all ref modes. |
| 5.17 | PR title plus generated Summary/Changes/Validation/Risks sections, separately approved, draft in Telegram, no merge. Verified in complete repository acceptance. |
| 5.18–5.19 | Issue loading and context labels; untrusted content cannot alter mode, tools or approvals. Planner sanitizes its complete context and explicitly labels SYSTEM_POLICY and USER_REQUEST. |
| 5.20–5.21 | Secret/artifact/large-file/ignore scanning; checks/Actions/status read APIs. Push CI review attestation and workflow-write deny protect production deployment boundary. |
| 5.22–5.23 | Required GitHub audit events including remote-write failure; fixture and security tests, real Git/Docker acceptance. Optional Rust tests inapplicable. |
| 6.1–6.4 | Official Python SDK and pinned HTTPS Streamable HTTP through existing policy. MCP SQL ownership/encryption models; no arbitrary stdio or duplicate runtime. |
| 6.5–6.7 | Bilingual server/tool/resource/prompt UI, explicit transport selection, HTTPS/DNS/IP/redirect validation and credentials per owned server. |
| 6.8 | Bounded tools/resources/resource-template/prompts discovery. SDK-advertised logging/task/experimental capability metadata retained; absent capabilities are not assumed. Logging/task advertisement does not grant server-originated execution or a new unbounded task runner. |
| 6.9 | mcp.<integration>.<external-tool>_<immutable-tool-id> namespace. Server/external-name SQL identity and old opaque-name saved-plan compatibility. |
| 6.10–6.11 | Reviewed READ/SEARCH LOW; reviewed CREATE draft/temporary artifact can be MEDIUM with explicit approval; other CREATE/UPDATE/SEND HIGH; dangerous/unknown disabled. MCP adapter enters shared ToolPolicyEngine. |
| 6.12–6.14 | PKCE/state/nonce/TTL/redirect/issuer/resource binding; encrypted access/refresh and restricted scopes; grant/cancel controls on failed jobs, explicit resume and repeated ownership/policy/scope checks. |
| 6.15–6.17 | Discovered resources/prompts only; all server roles serialized as untrusted; sanitizer covers outputs and full planner input, known application secrets and byte limits. |
| 6.18–6.20 | At most eight relevant schemas; database/Supabase read-only, arbitrary SQL blocked; GitHub MCP and deployment-provider writes denied; no shell/SSH/admin/billing/credential retrieval. |
| 6.21–6.22 | Schema/description/output fingerprint plus current configured policy semantics checked on execution. Both schema drift and policy drift require review. Exact per-tool approvals with full details. |
| 6.23–6.25 | Generic profiles, canonical native GitHub writes and existing durable job infrastructure for clone/discovery/resource/tool/auth follow-up. No second orchestrator. |
| 6.26–6.27 | Optional Rust/TypeScript helpers omitted because no demonstrated benefit; alternatives, boundaries, costs and fallback documented. |
| 6.28–6.30 | Required auth/call/approval/denial/resource/prompt/token events, controlled SDK server with read/write/danger/resource/template/prompt/OAuth flow, offline/deadline/TLS/SSRF/schema/isolation tests. |
| Railway / variables / documentation | Existing Python app/worker lease, SQL/Redis/volume architecture documented. MCP_CALLBACK_BASE_URL alias supported. Optional component variables do not become startup requirements. No Railway operations. |

Controlled acceptance proves the application paths and security checks, not that a third-party account has already been configured. The operator must provide an actual GitHub App installation/public callback and compatible MCP issuer/client before live account acceptance. Secret heuristics and CI review attestation remain explicit practical limitations. Resource templates are discovered/displayed; arbitrary template expansion or subscription is not exposed. Advertised MCP server task/logging capabilities are metadata only.
