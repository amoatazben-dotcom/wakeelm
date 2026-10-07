import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.db import models  # noqa: F401
from app.db.base import Base

url = os.environ["DATABASE_URL"]
if url.startswith(("postgres://", "postgresql://")):
    url = "postgresql+asyncpg://" + url.split("://", 1)[1]


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        if connection.dialect.name == "postgresql":
            # Session lock serializes deploy migrations, including multiple predeploy replicas.
            await connection.execute(text("SET lock_timeout = '30s'"))
            await connection.execute(text("SELECT pg_advisory_lock(78124900)"))
            await connection.commit()
        try:
            await connection.run_sync(run)
        finally:
            if connection.dialect.name == "postgresql":
                await connection.rollback()
                await connection.execute(text("SELECT pg_advisory_unlock(78124900)"))
                await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
