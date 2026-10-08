# Telegram AI Agent — Stage 9 Beta candidate

Async Python backend with FastAPI, aiogram 3, PostgreSQL, Redis and a universal OpenAI-compatible gateway. Arabic is the default; English is persisted per user. Provider onboarding, discovery, model selection and chat are joined by secure project uploads/indexing/search/context and a bounded coding agent with patches, diffs, approvals, rollback and container validation. Stages 5/6 add owned GitHub repositories, isolated agent branches and separately approved commit/push/PR actions, plus reviewed MCP tools/resources/prompts and OAuth. Deployment tools remain unavailable.

Candidate `0.9.0-beta.1`: stages 7/8 routing, specialist graphs, scoped memory, quotas, OIDC admin and operations are integrated. Final local verification:245 backend tests without skips, 3 client tests and 2 Chromium tests. Status **NOT_READY_FOR_BETA**: runtime OS HIGH findings, hosted CI billing lock and live Railway/configuration gates remain unresolved. No Beta tag or Railway deployment exists. See [final report](docs/STAGE_9_FINAL_REPORT.md), [checklist](docs/BETA_RELEASE_CHECKLIST.md), [required variables](docs/REQUIRED_VARIABLES.md) and [security audit](docs/FINAL_SECURITY_AUDIT.md).

## Local setup

Python 3.13 is selected for deployment; 3.12 is also supported. This workspace was verified on both Python 3.12.14 and 3.13.15.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Put the generated key into `MASTER_ENCRYPTION_KEY` in your private `.env`, set `TELEGRAM_BOT_TOKEN` from BotFather and connect PostgreSQL and Redis. Do not commit `.env`. Keep an encrypted backup of the master key; losing it makes saved tokens unreadable.

```sh
# Supply DATABASE_URL to Alembic through the environment (it does not read .env).
export DATABASE_URL=postgresql://agent:local-password@localhost:5432/agent
alembic upgrade head
sh scripts/start.sh
```

Endpoints: `/health` (liveness), `/ready` (dependency readiness). Commands: `/start`, `/help`, `/settings`, `/providers`, `/models`, `/cancel`. Interact in a private chat only.

Menus: new chat, API providers, models, settings and the latest 20 audit entries are functional. Files/projects and intelligent tasks are implemented; GitHub and tools/MCP are implemented; the admin dashboard exposes scoped usage and estimated costs with unknown-price labeling. Actual invoice/billing integration remains unavailable.

## Checks

```sh
pytest -q
ruff check app tests alembic
ruff format --check app tests alembic
```

Tests never call production Telegram or paid AI APIs. HTTP safety tests use an isolated local mock server; dispatcher tests simulate Telegram requests and verify the full onboarding/chat/delete flow. The two live-dependency checks are opt-in:

```sh
TEST_DATABASE_URL=postgresql://agent:local-test-only@127.0.0.1:55432/agent \
TEST_REDIS_URL=redis://127.0.0.1:56379/0 pytest -q
```

Use a disposable database **with migrations already applied** and a disposable Redis for this command. Integration tests create their own users and clean up provider/model records; audit records remain for inspection.

See [architecture](docs/ARCHITECTURE.md), [providers](docs/PROVIDERS.md), [security](docs/SECURITY.md), [Railway](docs/RAILWAY.md) and [implementation report](docs/IMPLEMENTATION_REPORT.md).


## Projects and coding tasks

Upload text/source/config, PDF, DOCX, XLSX or bounded ZIP/TAR/GZ project archives. Browse/search indexed files, ask grounded questions and choose READ_ONLY, SUGGEST or WORKSPACE tasks. Small workspace edits are allowed in WORKSPACE; sensitive edits and every command require persisted approval. Jobs run in a background worker and can be cancelled from their status card. Diffs and rollback are available in project change history.

Persist `WORKSPACE_STORAGE_ROOT` on a private volume; defaults/limits are in `.env.example`. Command execution is disabled until an administrator provisions a trusted Docker validator. It never falls back to executing uploaded code on the API host. Railway publication is intentionally deferred until all requested construction stages finish.

See [agent runtime](docs/AGENT_RUNTIME.md), [tool policy](docs/TOOL_SECURITY.md), [approvals](docs/APPROVALS.md), [sandbox](docs/SANDBOX.md), [uploads](docs/FILES_AND_WORKSPACES.md), [indexing](docs/PROJECT_INDEXING.md), [context](docs/CONTEXT_ENGINE.md) and [stage 3/4 report](docs/STAGE_3_4_REPORT.md).

## GitHub and MCP

GitHub App is preferred; scoped fine-grained PAT is the fallback. GitHub and MCP menus use private connections and queued discovery/import. Writes are disabled until operator configuration and always require exact approvals. Unknown MCP tools remain disabled until schema/description review. Optional integration settings do not prevent the basic bot from starting.

See [GitHub setup](docs/GITHUB_APP.md), [repository workflow](docs/REPOSITORY_AGENT.md), [Git safety](docs/GIT_SECURITY.md), [MCP](docs/MCP.md), [OAuth](docs/MCP_AUTH.md), [MCP security](docs/MCP_SECURITY.md), [integration profiles](docs/INTEGRATIONS.md), [technology choice](docs/TECHNOLOGY_SELECTION.md) and [stage 5/6 report](docs/STAGE_5_6_REPORT.md). Railway deployment remains deferred by request.

## Stages 7/8 platform

Tenant-scoped model routing and bounded fallback, encrypted memory, role-restricted specialist graphs, durable usage reservations/quotas, shared circuits, feature flags/emergency stops and an OIDC/MFA/RBAC admin API are implemented. The TypeScript/React dashboard supports Arabic RTL and English. Build it with `npm ci --prefix admin-web` and `npm run build --prefix admin-web`; FastAPI serves `/admin-web/`. OIDC is required to access operational data.

See [router](docs/MODEL_ROUTER.md), [specialists](docs/MULTI_AGENT.md), [memory](docs/MEMORY.md), [quotas](docs/QUOTAS.md), [admin](docs/ADMIN_DASHBOARD.md), [backups](docs/BACKUP_RESTORE.md) and [release process](docs/RELEASE_PROCESS.md). Railway deployment remains deferred by instruction; local tests do not assert production readiness. Container scan findings and live deployment/identity gates are tracked in release evidence and the final beta checklist.

## Native Android client — stages 1–2

The canonical Kotlin/Compose client is in `android-client/`. It connects to the
same platform account/provider gateway as Telegram. Projects/tasks are placeholders
for later Android stages. Backend compatibility is in `/api/v1`; apply
`alembic upgrade head` and run the backend branch before client end-to-end use.
Send `/login` privately to the bot, then paste the five-minute single-use code
into Android. Provider keys are registered through the backend, never bundled.

Use a full **JDK 17**, Android SDK 37.2/build tools 36 and Android Studio supporting
AGP 9.4.1. `minSdk=26`, `compileSdk=37.2`, `targetSdk=37`. From the repo root:

```sh
cd android-client
chmod +x gradlew
./gradlew :app:lintDebug :app:testDebugUnitTest :app:assembleDebug
./gradlew :app:assembleDebugAndroidTest
# With an Android 8+ device/emulator:
./gradlew :app:connectedDebugAndroidTest
# Alternate HTTPS backend (trailing slash required):
./gradlew :app:installDebug -PbackendUrl=https://your-backend.example/
```

Default API URL is the platform's public Railway hostname, not an embedded
credential. That deployed main backend must receive compatibility routes before
this branch's login/chat is usable against it. Arabic/English and system/light/dark
are switchable in More. Cached views work offline; AI generation needs a connection.
See [Android architecture](docs/android/ARCHITECTURE.md),
[API contract](docs/android/API_CONTRACT.md), [security](docs/android/SECURITY.md)
and [verification report](docs/android/STAGE_1_2_REPORT.md).

**FINAL APK NOT GENERATED YET.** Only debug builds are permitted for validation;
no final/release APK, AAB, signing or release publication in these stages.
