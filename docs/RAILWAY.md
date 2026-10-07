# Railway

The repository includes `railway.toml`, `.python-version` (3.13), `requirements.txt`, and `scripts/start.sh`. Railpack installs the package; pre-deploy runs `alembic upgrade head`. Start command binds `$PORT` on `0.0.0.0`, with `/ready` as the deployment health check. Graceful shutdown cancels polling and closes Telegram/Redis/database connections.

1. Create a Railway project with a Python `bot-api` service and PostgreSQL/Redis services.
2. Deploy this repository into `bot-api` and reference the database/Redis connection URLs.
3. Set the required variables below, preferably through Railway's secret UI. Do not paste credentials into committed config or logs.
4. Initially use polling with exactly one replica and one uvicorn worker. Do not run a second poller for the same Telegram token. Rolling deployments can briefly overlap polling processes; webhook mode avoids that constraint.
5. Generate a public domain and verify `/health` and `/ready`. Follow the acceptance flow in the implementation report using a real BotFather token/provider you own.

Required:

| Variable | Meaning |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | BotFather secret |
| `DATABASE_URL` | Railway PostgreSQL reference; postgres/postgresql URLs are converted to asyncpg |
| `REDIS_URL` | Redis connection reference |
| `MASTER_ENCRYPTION_KEY` | Fernet key; persist across redeploys |

Optional: `APP_NAME`, `APP_ENV`, `APP_HOST`, `APP_PORT`, `BOT_MODE` (polling default), `BOT_DEFAULT_LANGUAGE` (ar default), `LOG_LEVEL`, `PROVIDER_TIMEOUT`, `MAX_RESPONSE_BYTES`, `MAX_MODELS`. Railway supplies `PORT`; it wins over `APP_PORT`.

Webhook: set `BOT_MODE=webhook`, `PUBLIC_BASE_URL=https://your-domain`, and a random `WEBHOOK_SECRET` (Telegram-compatible characters, 1–256 characters). Startup registers `/telegram/webhook`; only this path receives updates. Multiple replicas must share PostgreSQL, Redis and the encryption key. Public ingress must allow Telegram and the secret header. Agent jobs use a durable SQL queue/background worker; ordinary provider/chat handlers remain inline. Use one app replica/uvicorn worker with a private persistent workspace volume.

For CLI deployment from this directory: `railway up`. Verify the final deployment status and dependency readiness before claiming live deployment. The user explicitly postponed all Railway deployments until construction of every requested stage finishes; no deployment was performed.

To run migrations manually in an already-linked service: `railway run alembic upgrade head` with the intended environment/service selected. Back up the production database before future schema changes. The initial downgrade removes the seven stage tables and is for disposable development databases only.


Stage 3/4: attach a persistent private volume and set WORKSPACE_STORAGE_ROOT to its mounted directory (e.g. /data/workspaces). Preserve MASTER_ENCRYPTION_KEY for provider tokens, project chunks, plans, diffs and snapshots. Keep SANDBOX_BACKEND=disabled on a normal Railway app until an authenticated external isolated runner is designed; there is no Docker daemon there and no host fallback. New defaults are listed in .env.example. The migrations add seven workspace tables and seven agent tables. Live acceptance and Railway health verification are pending the user's deployment milestone and production credentials.

## Stages 5/6 deployment design (deferred)

Continue with one Python `bot-api` service, PostgreSQL, Redis and the private persistent workspace volume. No TypeScript/Rust sidecar is needed. Ensure trusted `git` is installed in the runtime before enabling repository import; if the selected Railpack image lacks Git, add a reviewed build installation step/image before live deployment. Linux resource limits are used by the controlled Git subprocess. HTTPS egress must reach api.github.com/github.com and the reviewed public MCP/issuer origins. Do not allow arbitrary private/metadata access.

Add the optional integration variables from .env.example only when configuring those features. GITHUB_APP_* and GITHUB_CLIENT_* / GITHUB_WEBHOOK_SECRET are operator secrets; user PAT/MCP tokens are connected inside private Telegram and encrypted in SQL, never shared service env variables. INTEGRATIONS_CALLBACK_BASE_URL is the app's HTTPS domain and must match provider callback registrations. MCP_OAUTH_CLIENTS and MCP_TOOL_POLICIES are explicit JSON admin configuration. Leave write/CI review/comments false by default.

Migration 45e2729dffcb adds GitHub connections/repos/links, MCP servers/credentials/tools/resources, OAuth states and AgentJob kind/encrypted payload. Pre-deploy already runs Alembic. Normal Railway does not provide a Docker daemon; keep SANDBOX_BACKEND=disabled until Stage 7 provisions a trusted external validator. With default GIT_REQUIRE_VALIDATION=true repository publication then remains blocked, as intended.

No Railway project creation, variable mutation, service start or deployment was performed for Stages 5/6. The user postponed deployment until all construction stages finish.

## Deferred Stage 7/8 artifact

Use the root multi-stage Dockerfile (configured in railway.toml). The admin UI is a static build within bot-api, not a second Node service. Predeploy performs serialized Alembic migration; ready checks DB/Redis/worker/bot. Set workspace volume ownership to UID 10001 with private modes before serving uploads. Keep GitHub/MCP writes and risky validation disabled until review and isolated runtime configuration pass.

Before actual deployment provide required core secrets plus HTTPS public/callback URL, OIDC issuer/authorize/token/JWKS/client/audience/bootstrap subjects and a backup runner's separate backup key. Do not put raw values in git or reports. Optional GitHub App/OAuth/webhook and MCP issuer-client settings enable their respective features. This file is a deployment procedure; no Railway service has been started during deferred construction.
