from sqlalchemy import select

from app.core.exceptions import SafeError
from app.db.models import Model, Provider


class OwnedRepository:
    def __init__(self, session, user_id):
        self.session, self.user_id = session, user_id

    async def provider(self, provider_id, for_update=False):
        query = select(Provider).where(Provider.id == provider_id, Provider.user_id == self.user_id)
        if for_update:
            query = query.with_for_update()
        value = await self.session.scalar(query.execution_options(populate_existing=True))
        if value is None:
            raise SafeError("NOT_FOUND")
        return value

    async def model(self, model_id):
        value = await self.session.scalar(
            select(Model)
            .join(Provider)
            .where(Model.id == model_id, Provider.user_id == self.user_id)
        )
        if value is None:
            raise SafeError("NOT_FOUND")
        return value
