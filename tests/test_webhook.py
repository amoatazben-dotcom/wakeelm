from unittest.mock import AsyncMock

from cryptography.fernet import Fernet
from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_authenticated_webhook_validation_and_dedup(tmp_path):
    config = Settings(
        telegram_bot_token="123456:dummy",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/webhook.db",
        redis_url="redis://127.0.0.1:1",
        master_encryption_key=Fernet.generate_key().decode(),
        bot_mode="webhook",
        public_base_url="https://public.example",
        webhook_secret="test-secret",
        _env_file=None,
    )
    with TestClient(create_app(config, start_bot=False)) as client:
        app = client.app
        app.state.redis = FakeRedis()
        dispatcher = AsyncMock()
        app.state.dispatcher = dispatcher
        headers = {"X-Telegram-Bot-Api-Secret-Token": "test-secret"}
        assert client.post("/telegram/webhook", json={"update_id": 10}).status_code == 403
        assert (
            client.post("/telegram/webhook", json={"update_id": 10}, headers=headers).status_code
            == 200
        )
        assert (
            client.post("/telegram/webhook", json={"update_id": 10}, headers=headers).status_code
            == 200
        )
        assert dispatcher.feed_update.await_count == 1
        assert client.post("/telegram/webhook", content="{bad", headers=headers).status_code == 400
        assert (
            client.post("/telegram/webhook", content="x" * 1_000_001, headers=headers).status_code
            == 413
        )
        dispatcher.feed_update.side_effect = RuntimeError("private diagnostic")
        response = client.post("/telegram/webhook", json={"update_id": 20}, headers=headers)
        assert response.status_code == 503 and "private diagnostic" not in response.text
        dispatcher.feed_update.side_effect = None
        assert (
            client.post("/telegram/webhook", json={"update_id": 20}, headers=headers).status_code
            == 200
        )
