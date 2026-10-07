import os
import subprocess
from unittest.mock import Mock

import pytest

import main as entrypoint


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(entrypoint, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    for name in (
        "SERVER_PORT",
        "PORT",
        "APP_PORT",
        "WORKSPACE_STORAGE_ROOT",
        "RUN_MIGRATIONS",
        "BOT_DEFAULT_LANGUAGE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:unit-test-only")
    monkeypatch.setenv("BOT_DEFAULT_LANGUAGE", "ar")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:private-password@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")
    from cryptography.fernet import Fernet

    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", Fernet.generate_key().decode())
    run = Mock(return_value=subprocess.CompletedProcess([], 0))
    serve = Mock()
    monkeypatch.setattr(entrypoint.subprocess, "run", run)
    monkeypatch.setattr("uvicorn.run", serve)
    return tmp_path, run, serve


def test_dotenv_and_assigned_port_preserve_process_values(runtime, monkeypatch):
    root, _, _ = runtime
    monkeypatch.delenv("BOT_DEFAULT_LANGUAGE")
    (root / ".env").write_text("SERVER_PORT=9000\nPORT=9001\nBOT_DEFAULT_LANGUAGE=en\n")
    monkeypatch.setenv("SERVER_PORT", "9200")
    assert entrypoint.prepare_environment() == 9200
    assert os.environ["BOT_DEFAULT_LANGUAGE"] == "en"
    assert os.environ["WORKSPACE_STORAGE_ROOT"] == str(root / "storage" / "workspaces")


@pytest.mark.parametrize("value", ["0", "65536", "invalid"])
def test_invalid_port_never_migrates_or_starts(runtime, monkeypatch, value):
    _, run, serve = runtime
    monkeypatch.setenv("SERVER_PORT", value)
    with pytest.raises(SystemExit, match="valid TCP port"):
        entrypoint.main()
    run.assert_not_called()
    serve.assert_not_called()


def test_migration_precedes_single_process_server(runtime):
    root, run, serve = runtime
    entrypoint.main()
    assert run.call_args.kwargs["cwd"] == root
    assert run.call_args.args[0][1:] == ["-m", "alembic", "upgrade", "head"]
    assert serve.call_args.kwargs["workers"] == 1
    assert serve.call_args.kwargs["host"] == "0.0.0.0"


def test_migration_failure_stops_startup_without_leaking_secrets(runtime):
    _, run, serve = runtime
    run.return_value = subprocess.CompletedProcess([], 1, stderr="private-password")
    with pytest.raises(SystemExit) as error:
        entrypoint.main()
    assert "private-password" not in str(error.value)
    serve.assert_not_called()


def test_external_migration_can_be_selected(runtime, monkeypatch):
    _, run, serve = runtime
    monkeypatch.setenv("RUN_MIGRATIONS", "false")
    entrypoint.main()
    run.assert_not_called()
    serve.assert_called_once()
