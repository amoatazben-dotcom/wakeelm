import asyncio
import hashlib
import uuid
from pathlib import PurePosixPath

from sqlalchemy import delete, func, select

from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models.projects import (
    ProjectChunk,
    ProjectEmbedding,
    ProjectFile,
    ProjectManifest,
    ProjectSymbol,
    Workspace,
    WorkspaceEvent,
)
from app.indexing.chunker import Chunker
from app.indexing.parsers import ParserRegistry
from app.indexing.scanner import IgnoreRules, ProjectScanner
from app.services.audit_service import audit
from app.storage.archives import ARCHIVE_SUFFIXES
from app.storage.local import LocalWorkspaceStorage
from app.storage.paths import safe_relative


class WorkspaceService:
    def __init__(self, session, user_id, settings, secrets, limits=None):
        self.session, self.user_id, self.settings, self.secrets, self.limits = (
            session,
            user_id,
            settings,
            secrets,
            limits,
        )
        self.storage = LocalWorkspaceStorage(settings)
        self.parsers = ParserRegistry(settings)

    async def owned(self, workspace_id, for_update=False):
        query = select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.user_id == self.user_id,
            Workspace.status != "DELETED",
        )
        if for_update:
            query = query.with_for_update()
        workspace = await self.session.scalar(query)
        if workspace is None:
            raise SafeError("NOT_FOUND")
        return workspace

    def event(self, workspace, action, **metadata):
        safe = {k: v for k, v in metadata.items() if k in {"count", "status", "bytes"}}
        self.session.add(
            WorkspaceEvent(
                workspace_id=workspace.id, user_id=self.user_id, action=action, metadata_json=safe
            )
        )
        audit(self.session, self.user_id, action, "workspace", workspace.id, **safe)

    async def ingest(self, filename, data, mime=None):
        from app.platform.flags import FeatureFlags
        from app.platform.usage import QuotaEngine

        await FeatureFlags(self.session, self.user_id).deny_if("disable_uploads")
        quotas = QuotaEngine(self.session, self.user_id)
        limits = await quotas.limits()
        if len(data) > limits["max_upload_bytes"]:
            raise SafeError("UPLOAD_TOO_LARGE")
        await quotas.resource("storage_bytes", len(data))
        safe_relative(filename)
        if "/" in filename or len(filename) > 255:
            raise SafeError("PATH_DENIED")
        if len(data) > self.settings.max_upload_size_mb * 1024**2:
            raise SafeError("UPLOAD_TOO_LARGE")
        ident = str(uuid.uuid4())
        archive = filename.lower().endswith(ARCHIVE_SUFFIXES)
        root = await asyncio.to_thread(self.storage.create_workspace, self.user_id, ident)
        workspace = Workspace(
            id=ident,
            user_id=self.user_id,
            name=filename,
            root_path=root,
            type="ARCHIVE_PROJECT" if archive else "SINGLE_FILE",
            source_type="TELEGRAM_UPLOAD",
            source_filename=filename,
            status="CREATING",
            metadata_json={"declared_mime": (mime or "unknown")[:100]},
        )
        self.session.add(workspace)
        await self.session.flush()
        try:
            await asyncio.to_thread(self.storage.save_upload, self.user_id, ident, filename, data)
            self.event(workspace, "WORKSPACE_CREATED")
            self.event(workspace, "FILE_UPLOADED", bytes=len(data))
            if archive:
                count, size = await asyncio.to_thread(
                    self.storage.extract_archive, self.user_id, ident, filename, data
                )
                self.event(workspace, "ARCHIVE_EXTRACTED", count=count, bytes=size)
            else:
                await asyncio.to_thread(
                    self.storage.write_file, self.user_id, ident, filename, data
                )
            await self.index(ident)
            return workspace
        except BaseException:
            await asyncio.to_thread(self.storage.delete_workspace, self.user_id, ident)
            await self.session.delete(workspace)
            raise

    async def idle(self, workspace_id, agent_job_id=None):
        from app.agent.approvals import TERMINAL
        from app.db.models.agent import AgentJob, WorkspaceChangeSet

        query = select(AgentJob.id).where(
            AgentJob.workspace_id == workspace_id, AgentJob.status.not_in(TERMINAL)
        )
        if agent_job_id:
            query = query.where(AgentJob.id != agent_job_id)
        if await self.session.scalar(query):
            raise SafeError("WORKSPACE_BUSY")
        changes = select(WorkspaceChangeSet.id).where(
            WorkspaceChangeSet.workspace_id == workspace_id, WorkspaceChangeSet.status == "APPLYING"
        )
        if agent_job_id:
            changes = changes.where(WorkspaceChangeSet.job_id != agent_job_id)
        if await self.session.scalar(changes):
            raise SafeError("RECOVERY_REQUIRES_REVIEW")

    async def index(self, workspace_id, agent_job_id=None):
        workspace = await self.owned(workspace_id, True)
        await self.idle(workspace_id, agent_job_id)
        workspace.status = "INDEXING"
        paths = await asyncio.to_thread(self.storage.list_files, self.user_id, workspace.id)

        def reader(path):
            return self.storage.read_file(self.user_id, workspace.id, path)

        rules = await asyncio.to_thread(IgnoreRules, paths, reader)
        file_ids = select(ProjectFile.id).where(ProjectFile.workspace_id == workspace.id)
        chunk_ids = select(ProjectChunk.id).where(ProjectChunk.file_id.in_(file_ids))
        await self.session.execute(
            delete(ProjectEmbedding).where(ProjectEmbedding.chunk_id.in_(chunk_ids))
        )
        await self.session.execute(delete(ProjectChunk).where(ProjectChunk.file_id.in_(file_ids)))
        await self.session.execute(delete(ProjectSymbol).where(ProjectSymbol.file_id.in_(file_ids)))
        await self.session.execute(
            delete(ProjectFile).where(ProjectFile.workspace_id == workspace.id)
        )
        # Explicit child deletes keep tests and SQLite consistent with PostgreSQL cascades.
        await self.session.flush()
        records, texts, total = [], {}, 0
        parsed_cache = {}
        for path in paths:
            raw = await asyncio.to_thread(reader, path)
            total += len(raw)
            if total > self.settings.max_extracted_size_mb * 1024**2:
                raise SafeError("EXTRACTED_TOO_LARGE")
            sha = hashlib.sha256(raw).hexdigest()
            ignored = rules.ignored(path)
            key = (sha, PurePosixPath(path).suffix.lower())
            parsed = parsed_cache.get(key)
            if parsed is None:
                parsed = await asyncio.to_thread(self.parsers.parse, path, raw)
                parsed_cache[key] = parsed
            file = ProjectFile(
                workspace_id=workspace.id,
                relative_path=path,
                file_name=PurePosixPath(path).name,
                extension=PurePosixPath(path).suffix,
                mime_type=parsed.mime,
                size_bytes=len(raw),
                encoding=parsed.encoding,
                sha256=sha,
                language=parsed.language,
                is_binary=parsed.text is None,
                is_generated=any(
                    p in {"build", "dist", "node_modules", "target"}
                    for p in PurePosixPath(path).parts
                ),
                is_ignored=ignored,
            )
            self.session.add(file)
            await self.session.flush()
            records.append(file)
            if parsed.text is not None and not ignored:
                texts[path] = parsed.text
                for symbol in parsed.symbols:
                    self.session.add(ProjectSymbol(file_id=file.id, **symbol))
                for chunk in Chunker().chunks(parsed.text, parsed.symbols):
                    content = chunk.pop("content")
                    self.session.add(
                        ProjectChunk(
                            file_id=file.id,
                            content_encrypted=self.secrets.encrypt(content),
                            metadata_json={
                                "path": path,
                                "method": "STRUCTURAL" if parsed.symbols else "TEXT",
                            },
                            **chunk,
                        )
                    )
        manifest = ProjectScanner().scan(workspace.name, records, texts)
        manifest["workspace_id"] = workspace.id
        stored = await self.session.scalar(
            select(ProjectManifest).where(ProjectManifest.workspace_id == workspace.id)
        )
        if stored:
            stored.manifest_json = manifest
        else:
            self.session.add(ProjectManifest(workspace_id=workspace.id, manifest_json=manifest))
        workspace.file_count, workspace.size_bytes, workspace.status, workspace.last_accessed_at = (
            len(paths),
            total,
            "READY",
            now(),
        )
        self.event(workspace, "PROJECT_INDEXED", count=len(paths))
        await self.session.flush()
        return manifest

    async def list(self, page=0):
        if page < 0:
            raise SafeError("INVALID_INPUT")
        query = select(Workspace).where(
            Workspace.user_id == self.user_id,
            Workspace.status != "DELETED",
            Workspace.type != "INTEGRATION_CONTROL",
        )
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        return list(
            await self.session.scalars(
                query.order_by(Workspace.created_at.desc()).offset(page * 10).limit(10)
            )
        ), total

    async def files(self, workspace_id):
        await self.owned(workspace_id)
        return list(
            await self.session.scalars(
                select(ProjectFile)
                .where(ProjectFile.workspace_id == workspace_id)
                .order_by(ProjectFile.relative_path)
            )
        )

    async def file(self, file_id):
        file = await self.session.scalar(
            select(ProjectFile)
            .join(Workspace)
            .where(
                ProjectFile.id == file_id,
                Workspace.user_id == self.user_id,
                Workspace.status != "DELETED",
            )
        )
        if file is None:
            raise SafeError("NOT_FOUND")
        return file

    async def read(self, workspace_id, path):
        await self.owned(workspace_id)
        safe_relative(path)
        return await asyncio.to_thread(self.storage.read_file, self.user_id, workspace_id, path)

    async def manifest(self, workspace_id):
        await self.owned(workspace_id)
        value = await self.session.scalar(
            select(ProjectManifest).where(ProjectManifest.workspace_id == workspace_id)
        )
        if value is None:
            raise SafeError("NOT_FOUND")
        return value.manifest_json

    async def delete(self, workspace_id):
        workspace = await self.owned(workspace_id, True)
        await self.idle(workspace_id)
        await asyncio.to_thread(self.storage.delete_workspace, self.user_id, workspace_id)
        workspace.status = "DELETED"
        self.event(workspace, "WORKSPACE_DELETED")

    async def browse(self, workspace_id, directory="", page=0):
        if directory:
            safe_relative(directory)
        if page < 0:
            raise SafeError("INVALID_INPUT")
        prefix = directory.rstrip("/") + "/" if directory else ""
        directories = set()
        files = []
        for file in await self.files(workspace_id):
            if not file.relative_path.startswith(prefix):
                continue
            rest = file.relative_path[len(prefix) :]
            if "/" in rest:
                directories.add(prefix + rest.split("/")[0])
            else:
                files.append({"kind": "file", "path": file.relative_path, "id": file.id})
        items = [{"kind": "directory", "path": path} for path in sorted(directories)] + files
        return items[page * 10 : page * 10 + 10], len(items)
