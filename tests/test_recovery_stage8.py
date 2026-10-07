import os
import subprocess
import sys
import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text

from app.core.security import SecretManager
from app.db.models import Provider, User
from app.db.session import database
from scripts.backup_restore import backup, restore


async def test_legacy_and_versioned_key_rotation():
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    legacy = Fernet(old.encode()).encrypt(b"legacy-secret").decode()
    current = SecretManager(new, [old])
    assert current.decrypt(legacy) == "legacy-secret"
    older = SecretManager(old).encrypt("provider-secret")
    assert current.decrypt(older) == "provider-secret"
    rotated = current.encrypt(current.decrypt(older))
    assert SecretManager(new).decrypt(rotated) == "provider-secret"
    assert current.key_id in rotated


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="requires isolated PostgreSQL fixture"
)
async def test_zero_upgrade_userdata_and_encrypted_backup_separate_restore(tmp_path):
    source = "s8_source_" + uuid.uuid4().hex[:12]
    target = "s8_restore_" + uuid.uuid4().hex[:12]
    base = os.environ["TEST_DATABASE_URL"].rsplit("/", 1)[0]
    docker = os.environ.get("TEST_POSTGRES_CONTAINER", "telegram-agent-test-pg")

    def psql(sql):
        child = {
            k: v
            for k, v in os.environ.items()
            if k
            not in {
                "DOCKER_HOST",
                "DOCKER_CONTEXT",
                "DOCKER_TLS",
                "DOCKER_TLS_VERIFY",
                "DOCKER_CERT_PATH",
            }
        }
        subprocess.run(
            [
                "docker",
                "--host=unix:///var/run/docker.sock",
                "exec",
                docker,
                "psql",
                "-U",
                "agent",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                sql,
            ],
            check=True,
            capture_output=True,
            env=child,
        )

    psql(f'CREATE DATABASE "{source}"')
    psql(f'CREATE DATABASE "{target}"')
    try:
        child = os.environ | {"DATABASE_URL": base + "/" + source}
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "45e2729dffcb"],
            env=child,
            check=True,
            capture_output=True,
        )
        engine, sessions = database(
            "postgresql+asyncpg://" + (base + "/" + source).split("://", 1)[1]
        )
        key = Fernet.generate_key().decode()
        crypto = SecretManager(key)
        async with sessions() as session:
            user = User(telegram_user_id=99001, language="ar", is_active=True)
            session.add(user)
            await session.flush()
            session.add(
                Provider(
                    user_id=user.id,
                    name="restored-provider",
                    provider_type="CUSTOM_OPENAI_COMPATIBLE",
                    base_url="https://example.com/v1",
                    encrypted_api_token=crypto.encrypt("private-test-credential"),
                    token_hint="***",
                    extra_headers_encrypted=crypto.encrypt_headers({}),
                )
            )
            await session.commit()
        await engine.dispose()
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=child,
            check=True,
            capture_output=True,
        )
        backup_key = Fernet.generate_key().decode()
        metadata = await backup(base + "/" + source, tmp_path / "restore.enc", backup_key, docker)
        assert "private-test-credential" not in (tmp_path / "restore.enc").read_bytes().decode()
        with pytest.raises(RuntimeError, match="separate database"):
            await restore(base + "/" + source, tmp_path / "restore.enc", backup_key, docker)
        assert (await restore(base + "/" + target, tmp_path / "restore.enc", backup_key, docker))[
            "status"
        ] == "RESTORED"
        restored, factory = database(
            "postgresql+asyncpg://" + (base + "/" + target).split("://", 1)[1]
        )
        async with factory() as session:
            provider = await session.scalar(select(Provider))
            assert crypto.decrypt(provider.encrypted_api_token) == "private-test-credential"
            assert await session.scalar(select(User.telegram_user_id)) == 99001
            assert (
                await session.scalar(text("SELECT version_num FROM alembic_version"))
                == metadata["schema_version"]
            )
        await restored.dispose()
        import asyncio

        from fastapi.testclient import TestClient

        from app.core.config import Settings
        from app.main import create_app

        settings = Settings(
            telegram_bot_token="123456:dummy",
            database_url=base + "/" + target,
            redis_url=os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:56379/0"),
            master_encryption_key=key,
            workspace_storage_root=str(tmp_path / "restored-workspaces"),
            _env_file=None,
        )

        def startup_check():
            with TestClient(create_app(settings, start_bot=False)) as client:
                assert client.get("/ready").status_code == 200
                assert client.get("/version").json()["schema_version"] == metadata["schema_version"]

        await asyncio.to_thread(startup_check)
    finally:
        psql(f'DROP DATABASE "{target}" WITH (FORCE)')
        psql(f'DROP DATABASE "{source}" WITH (FORCE)')
