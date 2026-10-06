from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_and_readiness(tmp_path):
    settings = Settings(
        telegram_bot_token="123456:dummy",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/health.db",
        redis_url="redis://127.0.0.1:1",
        master_encryption_key=Fernet.generate_key().decode(),
        _env_file=None,
    )
    with TestClient(create_app(settings, start_bot=False)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["postgresql"] is True
        assert response.json()["checks"]["redis"] is False
        assert "dummy" not in response.text
        assert client.post("/telegram/webhook", json={}).status_code == 403
