import json
import shutil
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from test_workspaces import service

from app.core.config import Settings
from app.core.exceptions import SafeError
from app.core.security import SecretManager
from app.db.base import Base, now
from app.db.models import Provider, User
from app.db.models.agent import AgentJob
from app.db.models.integrations import GitHubConnection, MCPCredential, MCPServer, OAuthState
from app.db.models.platform import MemoryItem
from app.db.models.projects import Workspace
from app.db.session import database
from scripts.rotate_keys import rotate


async def test_missing_volume_never_reindexes_existing_project_as_empty(stack, tmp_path):
    w = service(stack, tmp_path)
    workspace = await w.ingest("main.py", b"VALUE = 1\n")
    before = await w.files(workspace.id)
    shutil.rmtree(w.storage.root_for(stack.user.id, workspace.id))
    with pytest.raises(SafeError, match="WORKSPACE_STORAGE_MISSING"):
        await w.index(workspace.id)
    assert workspace.status == "MISSING"
    assert len(await w.files(workspace.id)) == len(before) == 1
    with pytest.raises(SafeError, match="WORKSPACE_STORAGE_MISSING"):
        w.storage.list_files(stack.user.id, workspace.id)


async def test_transactional_rotation_of_legacy_provider_oauth_memory_and_nested_job_result(
    tmp_path,
):
    url = f"sqlite+aiosqlite:///{tmp_path}/rotation.db"
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    old_crypto = SecretManager(old)
    engine, factory = database(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        user = User(telegram_user_id=50001)
        session.add(user)
        await session.flush()
        session.add(
            Workspace(
                id="workspace",
                user_id=user.id,
                name="rotation",
                type="SINGLE_FILE",
                root_path="/private/test",
                source_type="TEST",
                source_filename="a.py",
                status="READY",
            )
        )
        await session.flush()
        session.add_all(
            [
                Provider(
                    user_id=user.id,
                    name="legacy",
                    provider_type="CUSTOM_OPENAI_COMPATIBLE",
                    base_url="https://example.com/v1",
                    encrypted_api_token=Fernet(old.encode()).encrypt(b"legacy-api-secret").decode(),
                    token_hint="***",
                    extra_headers_encrypted=old_crypto.encrypt_headers({"x-key": "old-header"}),
                ),
                GitHubConnection(
                    id="connection",
                    user_id=user.id,
                    connection_type="PAT",
                    status="ACTIVE",
                    encrypted_token=old_crypto.encrypt("github-secret"),
                ),
                MCPServer(
                    id="server",
                    user_id=user.id,
                    name="MCP",
                    server_url="https://example.com/mcp",
                    encrypted_auth_config=old_crypto.encrypt(json.dumps({"token": "mcp-secret"})),
                ),
                OAuthState(
                    id="state",
                    user_id=user.id,
                    kind="MCP",
                    target_id="server",
                    nonce_hash="a" * 64,
                    payload_encrypted=old_crypto.encrypt("oauth-secret"),
                    expires_at=now() + timedelta(minutes=5),
                ),
                AgentJob(
                    id="job",
                    user_id=user.id,
                    workspace_id="workspace",
                    mode="READ_ONLY",
                    max_steps=1,
                    status="COMPLETED",
                    request_text=old_crypto.encrypt("private goal"),
                    result_json={"answer_encrypted": old_crypto.encrypt("private result")},
                ),
                MemoryItem(
                    user_id=user.id,
                    layer="PREFERENCE",
                    scope_key="PREFERENCE::",
                    digest="b" * 64,
                    content_encrypted=old_crypto.encrypt("use Arabic"),
                    provenance_json={},
                    confidence=1,
                ),
            ]
        )
        await session.flush()
        session.add(
            MCPCredential(
                id="credential",
                user_id=user.id,
                mcp_server_id="server",
                credential_type="OAUTH",
                encrypted_access_token=old_crypto.encrypt("access-secret"),
                encrypted_refresh_token=old_crypto.encrypt("refresh-secret"),
                expires_at=now() + timedelta(hours=1),
                issuer="https://example.com",
            )
        )
        await session.commit()
    await engine.dispose()
    settings = Settings(
        telegram_bot_token="123456:dummy",
        database_url=url,
        redis_url="redis://127.0.0.1:1",
        master_encryption_key=new,
        master_encryption_previous_keys=[old],
        _env_file=None,
    )
    result = await rotate(settings)
    assert result["rotated_fields"] >= 9
    crypto = SecretManager(new)
    engine, factory = database(url)
    async with factory() as session:
        assert (
            crypto.decrypt((await session.scalar(select(Provider))).encrypted_api_token)
            == "legacy-api-secret"
        )
        assert (
            crypto.decrypt((await session.scalar(select(MCPCredential))).encrypted_refresh_token)
            == "refresh-secret"
        )
        assert (
            crypto.decrypt((await session.scalar(select(AgentJob))).result_json["answer_encrypted"])
            == "private result"
        )
        assert (
            crypto.decrypt((await session.scalar(select(MemoryItem))).content_encrypted)
            == "use Arabic"
        )
    await engine.dispose()
