# Telegram AI Agent — Stages 1 & 2

Async Python backend with FastAPI, aiogram 3, PostgreSQL, Redis and a universal OpenAI-compatible gateway. Arabic is the default; English is persisted per user. This implements provider onboarding, discovery, optional model testing, active model selection and independent single-turn chat. Autonomous coding, shell execution, repository writes and MCP execution are outside this stage.

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

Menus: new chat, API providers, models, settings and the latest 20 audit entries are functional. Files, projects, tools/MCP and the usage dashboard explicitly show “coming later”. Usage token counts are safely logged when supplied by the provider; there is no usage billing dashboard.

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
