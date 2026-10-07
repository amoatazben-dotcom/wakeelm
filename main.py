"""Portable Python hosting entry point: python main.py (including Botkeep)."""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


def prepare_environment():
    os.chdir(ROOT)
    # Botkeep writes .env; actual process variables take precedence.
    load_dotenv(ROOT / ".env", override=False)
    os.environ.setdefault("WORKSPACE_STORAGE_ROOT", str(ROOT / "storage" / "workspaces"))
    value = (
        os.environ.get("SERVER_PORT")
        or os.environ.get("PORT")
        or os.environ.get("APP_PORT", "8000")
    )
    try:
        port = int(value)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise SystemExit("SERVER_PORT / PORT / APP_PORT must be a valid TCP port") from None
    return port


def main():
    port = prepare_environment()
    from app.core.config import Settings

    Settings()  # Validate before applying any database migrations.
    migrate = os.environ.get("RUN_MIGRATIONS", "true").lower()
    if migrate not in {"true", "false"}:
        raise SystemExit("RUN_MIGRATIONS must be true or false")
    if migrate == "true":
        # Same serialized Alembic migrations used by Railway. No shell or root needed.
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            capture_output=True,
            timeout=300,
            check=False,
        )
        if result.returncode:
            # Connection errors may contain secrets; do not expose raw stderr.
            raise SystemExit("Database migration failed; check connection/TLS and schema settings")
    import uvicorn

    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=port,
        workers=1,
        access_log=False,
    )


if __name__ == "__main__":
    main()
