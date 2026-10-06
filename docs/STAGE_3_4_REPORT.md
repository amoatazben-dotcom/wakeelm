# Stage 3/4 implementation report

Implementation and local acceptance were verified. **Live Telegram/provider/Railway acceptance remains pending** because the user explicitly postponed deployment until all requested construction stages finish. No production credential or Railway resource was created/changed during this work.

## 1. Files created

Stage 3 (already published): models/projects.py; storage/base.py, paths.py, local.py, archives.py and package marker; indexing/parsers.py, scanner.py, chunker.py and marker; context/engine.py, semantic.py and marker; services/workspace_service.py, search_service.py; bot/handlers/workspaces.py; tests/test_workspaces.py; migration f5b9bb2e57e2; FILES_AND_WORKSPACES.md, PROJECT_INDEXING.md, CONTEXT_ENGINE.md.

Stage 4 new files:

- `.dockerignore`
- `alembic/versions/70b1efb2e547_stage_4_secure_agent_jobs_approvals_.py`
- `app/agent/__init__.py`
- `app/agent/approvals.py`
- `app/agent/orchestrator.py`
- `app/agent/ownership.py`
- `app/agent/patches.py`
- `app/agent/planner.py`
- `app/agent/schemas.py`
- `app/agent/validator.py`
- `app/agent/worker.py`
- `app/bot/handlers/agent.py`
- `app/db/models/agent.py`
- `app/sandbox/__init__.py`
- `app/sandbox/commands.py`
- `app/sandbox/runner.py`
- `app/services/agent_service.py`
- `app/tools/__init__.py`
- `app/tools/registry.py`
- `docker/validation.Dockerfile`
- `docs/AGENT_RUNTIME.md`
- `docs/APPROVALS.md`
- `docs/SANDBOX.md`
- `docs/TOOL_SECURITY.md`
- `tests/test_agent.py`
- `tests/test_sandbox_integration.py`
- `docs/STAGE_3_4_REPORT.md` (this report)

## 2. Files modified

- `.env.example`
- `.github/workflows/checks.yml`
- `README.md`
- `app/api/health.py`
- `app/bot/dispatcher.py`
- `app/bot/middleware.py`
- `app/db/models/__init__.py`
- `app/indexing/parsers.py`
- `app/indexing/scanner.py`
- `app/locales/ar.json`
- `app/locales/en.json`
- `app/main.py`
- `app/providers/adapters/openai.py`
- `app/services/model_service.py`
- `app/services/workspace_service.py`
- `app/storage/paths.py`
- `docs/ARCHITECTURE.md`
- `docs/RAILWAY.md`
- `docs/SECURITY.md`
- `docs/WORKFLOW.md`
- `tests/test_telegram.py`

Stage 3 also updated config/dependencies/lock/requirements, Telegram routing/localization, SQLite foreign-key setup, .gitignore and ModelService context completion support; its commits retain the full diff.

## 3. Database migrations

- `f5b9bb2e57e2` after initial `4a07d561ec44`: workspaces, project_files, project_manifests, project_symbols, project_chunks, project_embeddings, workspace_events.
- `70b1efb2e547` after Stage 3: agent_jobs, agent_steps, tool_calls, approvals, workspace_change_sets, file_snapshots, validation_runs. Telegram chat IDs use BIGINT.
- Applied to disposable PostgreSQL 17; Stage 4 downgrade/re-upgrade and `alembic check` verified. Downgrades destroy stage data and are development-only.

## 4. New environment variables

`.env.example` lists every default: WORKSPACE_STORAGE_ROOT; MAX_UPLOAD_SIZE_MB, MAX_ARCHIVE_SIZE_MB, MAX_EXTRACTED_SIZE_MB, MAX_ARCHIVE_FILES, MAX_SINGLE_FILE_SIZE_MB, MAX_PROJECT_FILES; CONTEXT_MAX_TOKENS, CONTEXT_SAFETY_MARGIN; MAX_AGENT_STEPS, MAX_TOOL_CALLS, MAX_REPLANS, MAX_REPAIR_ATTEMPTS, MAX_TASK_DURATION, MAX_COMMAND_OUTPUT_BYTES, COMMAND_TIMEOUT; SANDBOX_BACKEND, SANDBOX_IMAGE, REQUIRE_EDIT_APPROVAL, MAX_PATCH_FILES, APPROVAL_TTL_SECONDS.

No new production secret is needed for local implementation. Later Railway deployment still needs TELEGRAM_BOT_TOKEN, a persistent MASTER_ENCRYPTION_KEY and database/Redis references plus a private persistent workspace volume. AI provider keys are added through the bot, encrypted per user. Keep sandbox disabled on ordinary Railway until hosted isolation is provisioned.

## 5. Supported upload types

Bounded regular documents/source/config/text; ZIP, TAR, TAR.GZ/TGZ and GZ; text/Markdown and common Python/JS/TS/Java/Kotlin/Dart/Rust/Go/config formats; PDF, DOCX and XLSX parsers. Unknown/binary types may be stored but are not fed to text context. No RAR/7z, nested archives, encrypted ZIP or archive links/devices. No document macros/formulas/embedded code are executed.

## 6. Workspace security

Per-user/UUID private directories; parameterized scoped SQL; descriptor-relative no-follow traversal; size/count/extraction/compression-ratio limits; no absolute/traversal/backslash/symlink/hardlink/device paths; original/extracted/working/metadata areas; ownership on every callback/service query; deletion/reindex blocked during active or cancellation-pending jobs; batch hash checks/snapshots/compensation and audited rollback.

## 7. Indexing

Hashes/encoding/language/MIME/ignore/generated metadata, bounded document parsing, framework/build/test/package/database/container/CI evidence manifests; robust Python AST symbols and structural chunks. Other languages have text/manifest support, not equivalent AST precision. Chunks encrypt text with provenance. Reindex deletes dependent embeddings/chunks/symbols safely; unchanged duplicate content is parsed once per indexing pass.

## 8. Search

Scoped exact literal text, filenames/paths, Python symbols and optional globs, bounded result counts and directory-first paginated UI. Optional embedding/provider/vector-store interfaces and portable cosine retrieval exist; no automatic paid embeddings. Exact search does not require an embedding provider.

## 9. Context

Request/file/symbol ranking, relevant chunk selection, token estimate/window reservation/safety margin, recent observation bounds and path/line/method/reason provenance. The engine never sends the whole project. Grounded Q&A requires JSON and rejects invented citation paths; narrative correctness remains model-dependent.

## 10. Agent modes

READ_ONLY reads/searches; SUGGEST also proposes encrypted diffs; WORKSPACE may apply bounded edits and run gated validation. Explicit user acceptance can queue a completed suggestion as a workspace apply task. Status, cancellation, last jobs, approvals, diff downloads, tests and confirmed rollback are bilingual.

## 11. Registered tools

workspace.list_files, workspace.read_file, workspace.file_info; project.search_text/search_files/search_symbols/get_manifest/diff; workspace.propose_patch/apply_patch/restore_file; validation.detect_commands/run; agent.request_approval. Registry entries declare input/output envelope schema, modes, risk, timeout and output budget. There is no arbitrary shell, host/network/admin, Git push, deployment or MCP tool.

## 12. Approval rules

Every validation command and restoration; patch deletion, >3 files, >200 changed lines, or all edits when REQUIRE_EDIT_APPROVAL=true. Persisted ownership/job/step/hash/expiry/state binding; exact normalized arguments; row locks; no replay/cross-user/expired approvals. Repair validation needs a new approval. Explicit wrapper cannot authorize an unknown action. User rollback has separate exact-change-set confirmation.

## 13. Sandbox

Actual Docker runner verified with trusted Python image. Disposable copy only, no production env/client proxy config/socket/host files, network none, nonroot, read-only root, no capabilities, no-new-privileges, default seccomp, PID/memory/CPU/tmpfs limits, forced timeout/cancellation, bounded encrypted first/last output. Disabled backend fails closed. Kernel-sharing Docker is not a VM and requires a dedicated patched validation host; see SANDBOX.md.

## 14. Validation commands

Fixed IDs: python_tests/python_lint/python_types; node_tests/node_lint/node_build; android_tests/android_lint; flutter_tests/dart_analyze; rust_tests/rust_check; go_tests. Project evidence gates detection; Node root scripts must exist. Actual Python test execution and isolation were verified. Other language execution requires a separately configured trusted toolchain/cache image and was not live-verified. Syntax checks currently use Python AST. Semantic goal comparison is REVIEW_REQUIRED; no command run is labeled NOT_RUN.

## 15. Test results

Final verification: 147 tests passed with disposable PostgreSQL 17, Redis 7 and real Docker sandbox enabled; no skipped test in that run. Ruff lint/format pass; Alembic check reports no schema drift; wheel build includes all agent/storage modules and both locales. One upstream FastAPI/Starlette TestClient deprecation warning remains. GitHub Actions workflow includes the container tests, but account billing prevents remote execution; local results are the evidence.

## 16. Security test results

Traversal/archive links/bombs/count/size/ownership/binary checks; unknown tool/extra shell args/mode denials; stale patch/unified/line/full/new edits; no-follow new paths; partial batch compensation and crash recovery; encrypted snapshots/plan/request; approval ownership/hash/step/replay/expiry/rejection; limits/replanning/cancel busy protection; real container production-env/proxy/host/socket exclusion, metadata/public network blocking, read-only/nonroot/copy isolation, timeout/output/cancellation. An actual failing pytest run was repaired in one bounded batch, approved again and passed. Telegram dispatcher exercises job creation/status/cancel alongside previous onboarding/chat functionality using a simulated Telegram transport.

## 17. Railway deployment status

Intentionally not deployed, per latest user instruction. No claim of a healthy live bot or production acceptance. Production Telegram and paid provider calls were not exercised. Normal Railway cannot execute Docker sandbox commands without a separately provisioned isolated backend; disabled default prevents host fallback.

## 18. Git branch

Stage 3/4 review branch: `stage-3-4-project-intelligence-agent-runtime`. Stage 4 development/review branch: `stage-4-secure-agent-runtime`; verified snapshots are published to main without force push. Repository: https://github.com/amoatazben-dotcom/wakeelm .

## 19. Commit list

Stage 3 published commits: faaefae (secure ingestion/indexing), aa12562 (context/search/bilingual workspace UI), 43b6106 (storage adapters/index replacement fix).

Stage 4 is split into:

- feat: persist agent jobs approvals and structured provider planning
- feat: enforce tool policy patches rollback and isolated validation
- feat: run cancellable background agents with bilingual Telegram controls
- test: verify container isolation and document stage 3 and 4

Published hashes are available in repository branch history; no history rewriting is used.

## 20. Known limitations

No live deployment acceptance yet; CI account billing locked; local filesystem/shared-volume single-worker topology; trusted Docker host required; Python-only trusted sample image/AST precision; no provider-billing quotas or embeddings UI; no automatic dependencies installation; no semantic proof of the goal; model citations/JSON can fail safely; Docker shares the host kernel; persistence is durable but interrupted model calls are stopped rather than exactly-once replayed. UI histories are bounded to the latest ten jobs/change sets/test runs. Original project sources remain plaintext on private disk; chunks/plans/diffs/snapshots/results are encrypted in SQL.

## 21. Remaining Stage 5 work

Implement the next supplied Stage 5 requirements. For production command execution on Railway, design an authenticated isolated validation worker/backend and deployment topology first. Add multi-language trusted images/offline dependencies, broader AST indexing, optional semantic setup/UI, explicit usage/cost quotas and stronger goal verification as requested. After all construction stages, configure secrets/volume, deploy Railway and execute the live acceptance checklist with the user’s Telegram/provider configuration.
