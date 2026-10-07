"""Encrypted PostgreSQL backup/empty-target restore. Credentials stay in child environment."""

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.db.base import now
from app.db.session import database
from app.platform.version import APP_VERSION

MAX_BYTES = 256 * 1024 * 1024


def command(url, executable, args, docker=None):
    parsed = make_url(url)
    if docker:
        # Intended for isolated local drills only; production uses native pg tools.
        for name in [
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        ]:
            os.environ.pop(name, None)
        return [
            "docker",
            "--host=unix:///var/run/docker.sock",
            "exec",
            "-i",
            docker,
            executable,
            "-U",
            parsed.username,
            "-d",
            parsed.database,
            *args,
        ], os.environ.copy()
    child = os.environ.copy()
    child.update(
        PGHOST=parsed.host or "localhost",
        PGPORT=str(parsed.port or 5432),
        PGUSER=parsed.username or "",
        PGPASSWORD=parsed.password or "",
        PGDATABASE=parsed.database or "",
    )
    return [executable, "-d", parsed.database, *args], child


async def schema(url):
    async_url = "postgresql+asyncpg://" + url.split("://", 1)[1]
    engine, _ = database(async_url)
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        await engine.dispose()


async def backup(url, output, key, docker=None):
    output = Path(output)
    cipher = Fernet(key.encode())
    version = await schema(url)
    args, child = command(url, "pg_dump", ["--format=custom", "--no-owner", "--no-acl"], docker)
    with tempfile.TemporaryFile() as temporary:
        result = subprocess.run(
            args, env=child, stdout=temporary, stderr=subprocess.PIPE, timeout=120
        )
        if result.returncode:
            raise RuntimeError("pg_dump failed; details withheld to protect connection secrets")
        if temporary.tell() > MAX_BYTES:
            raise RuntimeError("Backup exceeds bounded encryption limit")
        temporary.seek(0)
        encrypted = cipher.encrypt(temporary.read())
    metadata = {
        "timestamp": now().isoformat(),
        "app_version": APP_VERSION,
        "schema_version": version,
        "source_database": make_url(url).database,
        "sha256": hashlib.sha256(encrypted).hexdigest(),
        "format": "pg-custom-fernet-v1",
        "bytes": len(encrypted),
    }
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(encrypted)
    output.with_suffix(output.suffix + ".json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


async def restore(url, source, key, docker=None):
    source = Path(source)
    metadata = json.loads(source.with_suffix(source.suffix + ".json").read_text())
    if make_url(url).database == metadata["source_database"]:
        raise RuntimeError("Restore must use a separate database")
    engine, _ = database("postgresql+asyncpg://" + url.split("://", 1)[1])
    try:
        async with engine.connect() as connection:
            count = await connection.scalar(
                text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            )
            if count:
                raise RuntimeError("Restore target must be empty")
    finally:
        await engine.dispose()
    if source.stat().st_size > MAX_BYTES * 2:
        raise RuntimeError("Backup too large")
    encrypted = source.read_bytes()
    if hashlib.sha256(encrypted).hexdigest() != metadata["sha256"]:
        raise RuntimeError("Backup checksum mismatch")
    raw = Fernet(key.encode()).decrypt(encrypted)
    args, child = command(
        url,
        "pg_restore",
        ["--no-owner", "--no-acl", "--exit-on-error", "--single-transaction"],
        docker,
    )
    result = subprocess.run(
        args, env=child, input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120
    )
    if result.returncode:
        raise RuntimeError("pg_restore failed; connection details withheld")
    if await schema(url) != metadata["schema_version"]:
        raise RuntimeError("Restored schema differs")
    return {"status": "RESTORED", "schema_version": metadata["schema_version"]}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("path")
    parser.add_argument("--docker-container")
    args = parser.parse_args()
    result = await (backup if args.operation == "backup" else restore)(
        os.environ["DATABASE_URL"],
        args.path,
        os.environ["BACKUP_ENCRYPTION_KEY"],
        args.docker_container,
    )
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
