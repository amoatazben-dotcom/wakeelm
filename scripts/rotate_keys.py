"""Offline rotation: pause workers, set active + previous keys, then run this module."""

import asyncio

from sqlalchemy import JSON, Text, select

from app.core.config import Settings
from app.core.security import SecretManager
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import database


def rotate_json(value, crypto):
    if isinstance(value, dict):
        return {
            key: crypto.encrypt(crypto.decrypt(item))
            if key.endswith("_encrypted") and isinstance(item, str)
            else rotate_json(item, crypto)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [rotate_json(item, crypto) for item in value]
    return value


async def rotate(settings=None):
    settings = settings or Settings()
    crypto = SecretManager(
        settings.master_encryption_key.get_secret_value(),
        [key.get_secret_value() for key in settings.master_encryption_previous_keys],
    )
    engine, sessions = database(settings.async_database_url)
    count = 0
    try:
        async with sessions() as session, session.begin():
            for mapper in Base.registry.mappers:
                model = mapper.class_
                encrypted = [
                    column.name
                    for column in mapper.columns
                    if isinstance(column.type, Text)
                    and ("encrypted" in column.name or column.name == "request_text")
                ]
                nested = [column.name for column in mapper.columns if isinstance(column.type, JSON)]
                if not encrypted and not nested:
                    continue
                for row in await session.scalars(select(model).with_for_update()):
                    for field in encrypted:
                        value = getattr(row, field)
                        if value:
                            setattr(row, field, crypto.encrypt(crypto.decrypt(value)))
                            count += 1
                    for field in nested:
                        setattr(row, field, rotate_json(getattr(row, field), crypto))
        return {"rotated_fields": count, "active_key_id": crypto.key_id}
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print(asyncio.run(rotate()))
