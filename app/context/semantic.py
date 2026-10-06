import math
from typing import Protocol

from sqlalchemy import delete, select

from app.core.exceptions import SafeError
from app.db.models.projects import ProjectChunk, ProjectEmbedding, ProjectFile


class EmbeddingProvider(Protocol):
    name: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    async def search(self, workspace_id, vector, limit): ...


def checked(vector):
    if (
        not isinstance(vector, list)
        or not 1 <= len(vector) <= 4096
        or any(
            not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
            for v in vector
        )
    ):
        raise SafeError("INVALID_RESPONSE")
    return vector


class DatabaseVectorStore:
    """Portable JSON vectors; a pgvector adapter may replace this for larger projects."""

    def __init__(self, workspaces):
        self.workspaces = workspaces

    async def search(self, workspace_id, vector, limit=10):
        checked(vector)
        await self.workspaces.owned(workspace_id)
        rows = await self.workspaces.session.execute(
            select(ProjectEmbedding, ProjectChunk)
            .join(ProjectChunk)
            .join(ProjectFile)
            .where(ProjectFile.workspace_id == workspace_id, ProjectFile.is_ignored.is_(False))
        )
        norm = math.sqrt(sum(x * x for x in vector)) or 1
        scores = []
        for embedding, chunk in rows:
            other = checked(embedding.vector_json)
            if len(other) != len(vector):
                continue
            similarity = sum(x * y for x, y in zip(vector, other)) / (
                norm * (math.sqrt(sum(x * x for x in other)) or 1)
            )
            scores.append((similarity, chunk))
        return [
            chunk for _, chunk in sorted(scores, key=lambda item: item[0], reverse=True)[:limit]
        ]


class SemanticIndex:
    def __init__(self, workspaces, provider):
        self.workspaces, self.provider = workspaces, provider
        self.store = DatabaseVectorStore(workspaces)

    async def build(self, workspace_id):
        await self.workspaces.owned(workspace_id)
        chunks = list(
            await self.workspaces.session.scalars(
                select(ProjectChunk)
                .join(ProjectFile)
                .where(ProjectFile.workspace_id == workspace_id)
            )
        )
        for start in range(0, len(chunks), 32):
            batch = chunks[start : start + 32]
            vectors = await self.provider.embed(
                [self.workspaces.secrets.decrypt(c.content_encrypted) for c in batch]
            )
            if len(vectors) != len(batch):
                raise SafeError("INVALID_RESPONSE")
            for chunk, vector in zip(batch, vectors):
                checked(vector)
                await self.workspaces.session.execute(
                    delete(ProjectEmbedding).where(ProjectEmbedding.chunk_id == chunk.id)
                )
                self.workspaces.session.add(
                    ProjectEmbedding(
                        chunk_id=chunk.id, model=self.provider.name, vector_json=vector
                    )
                )

    async def search(self, workspace_id, text, limit=10):
        await self.workspaces.owned(workspace_id)
        vectors = await self.provider.embed([text])
        if len(vectors) != 1:
            raise SafeError("INVALID_RESPONSE")
        return await self.store.search(workspace_id, vectors[0], limit)
