from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.base import now
from app.db.models import User
from app.services.audit_service import audit


async def ensure_user(session, telegram, default="ar"):
    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    statement = (
        insert(User)
        .values(
            telegram_user_id=telegram.id,
            telegram_username=telegram.username,
            first_name=telegram.first_name,
            last_name=telegram.last_name,
            language=default,
            last_seen_at=now(),
        )
        .on_conflict_do_nothing(index_elements=["telegram_user_id"])
        .returning(User.id)
    )
    created = await session.scalar(statement)
    user = await session.scalar(select(User).where(User.telegram_user_id == telegram.id))
    user.telegram_username, user.first_name, user.last_name = (
        telegram.username,
        telegram.first_name,
        telegram.last_name,
    )
    user.last_seen_at = now()
    if created:
        audit(session, user.id, "USER_REGISTERED")
    return user


async def change_language(session, user, language):
    if language not in {"ar", "en"}:
        raise ValueError("Invalid locale")
    user.language = language
    audit(session, user.id, "LANGUAGE_CHANGED", language=language)
