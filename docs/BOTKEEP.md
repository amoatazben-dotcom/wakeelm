# Botkeep deployment

This profile uses the existing FastAPI/aiogram app, SQL models, Redis and worker.
It does not require Docker, root, apt, runuser or Railway-specific variables.
Railway continues to use its existing Dockerfile/start.sh and predeploy migration.

Official requirements: https://botkeep.cloud/docs/python,
https://botkeep.cloud/docs/github, https://botkeep.cloud/docs/hosting.

## Application settings

Select the Python profile, Python 3.13 (3.12 also supported), repository
`amoatazben-dotcom/wakeelm`, repository root, and the branch containing this change.
Install `requirements.txt`; if a custom install command is offered, use
`python -m pip install -r requirements.txt`. Start with **`python main.py`**.
Use one instance/worker for Telegram polling. The launcher loads Botkeep's `.env`
without overriding process variables, validates settings, runs serialized
`alembic upgrade head`, then listens on `0.0.0.0` at the assigned `SERVER_PORT`.
`PORT`, `APP_PORT`, then 8000 are fallbacks for other Python hosts.
Set `RUN_MIGRATIONS=false` only if an operator has already applied migrations.
Startup stops on failed migrations; it does not start with a broken schema.

## Environment and persistent data

Configure values privately in Botkeep's Environment panel, never in Git or a ZIP:

| Name | Value/source |
| --- | --- |
| `APP_ENV` | `production` |
| `TELEGRAM_BOT_TOKEN` | Existing BotFather token |
| `DATABASE_URL` | Reachable PostgreSQL connection string from Database panel |
| `REDIS_URL` | Reachable Redis connection string from Database panel |
| `MASTER_ENCRYPTION_KEY` | Preserve the existing key when moving existing data |
| `BOT_MODE` | `polling` initially |
| `BOT_DEFAULT_LANGUAGE` | `ar` |
| `WORKSPACE_STORAGE_ROOT` | `storage/workspaces` within the persistent project files |
| `SANDBOX_BACKEND` | `disabled` |
| `PUBLIC_BASE_URL` | Assigned HTTPS domain, if configured |
| `INTEGRATIONS_CALLBACK_BASE_URL` | Same HTTPS origin; update registered callbacks |

Create PostgreSQL and Redis profiles or use reachable external services.
Railway's `*.railway.internal` hostnames and `${{...}}` references cannot be used
from Botkeep. Copy actual connection details for the destination environment.
Use verified TLS per the database panel. asyncpg supports `ssl=verify-full` in the
PostgreSQL URL and a trusted CA in the runtime; Redis uses `rediss://` for TLS.
Never disable certificate verification to work around a failed connection.
Confirm the platform's CA installation and persistent directory before migration.
Back up SQL, workspace files and encryption keys before importing existing data.

Polling needs outbound HTTPS to Telegram and provider hosts; it does not need a
Telegram webhook. Do not run the Railway poller and Botkeep poller simultaneously
with the same bot token. Prepare and test the destination, then stop the source
poller immediately before starting the destination. This is an operator cutover,
not an automatic database transfer. Do not delete the source data.

## Admin dashboard and optional tools

Python runtime does not build the React dashboard. For the complete dashboard,
build it outside Botkeep with Node 24:

```sh
npm ci --prefix admin-web --ignore-scripts
npm run build --prefix admin-web
```

Upload a clean ZIP with `main.py`, `requirements.txt`, `pyproject.toml`,
`alembic.ini`, `app/`, `alembic/`, `scripts/`, and `admin-web/dist/` at the archive
root. Exclude `.env`, `.git`, storage, node_modules and virtual environments.
GitHub imports alone do not include the ignored dist directory: the bot/API work,
but the dashboard requires the prebuilt ZIP. OIDC settings remain mandatory for
admin access. Model providers are still configured per user through `/providers`;
unconsumed OPENROUTER/OPENAI environment variables do not enable a shared provider.

Repository import additionally needs the `git` executable. Check the Python
profile supports it; do not assume apt/root. Isolated Docker command validation
remains unavailable without a separately provisioned runner. Keep existing write
and validation policies rather than enabling unsafe host command execution.

## Acceptance

Check Console for successful startup. Configure the assigned port in Network and
HTTPS routing in Domains. `/health` must return 200 and `/ready` must return 200
with PostgreSQL, Redis, bot and agent_worker checks true. `/version` identifies
the migrated schema. Try `/start`, provider discovery and a project upload in a
private Telegram chat; restart and verify data survives. These live checks require
the actual account configuration and are not asserted by the local startup tests.
