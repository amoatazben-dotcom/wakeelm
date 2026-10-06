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
