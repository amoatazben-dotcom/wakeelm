import asyncio
import difflib
import hashlib
import json
import uuid

from sqlalchemy import select
from unidiff import PatchSet

from app.agent.ownership import AgentOwnership
from app.agent.schemas import ProposePatchInput
from app.core.exceptions import SafeError
from app.db.models.agent import FileSnapshot, WorkspaceChangeSet
from app.services.audit_service import audit
from app.storage.paths import exists_regular


class PatchEngine:
    def __init__(self, workspaces, job):
        self.workspaces, self.job = workspaces, job
        self.session, self.user_id, self.secrets, self.settings = (
            workspaces.session,
            workspaces.user_id,
            workspaces.secrets,
            workspaces.settings,
        )
        self.owned = AgentOwnership(self.session, self.user_id)

    async def _job(self, write=False):
        job = await self.owned.job(self.job.id)
        if job.workspace_id != self.job.workspace_id:
            raise SafeError("POLICY_DENIED")
        if job.status in {"CANCELLED", "FAILED", "LIMIT_REACHED"}:
            raise SafeError("JOB_CANCELLED")
        if write and job.mode != "WORKSPACE":
            raise SafeError("POLICY_DENIED")
        return job

    async def _current(self, path, missing=False):
        await self.workspaces.owned(self.job.workspace_id)
        root = self.workspaces.storage.root_for(self.user_id, self.job.workspace_id)
        if missing and not await asyncio.to_thread(exists_regular, root, path):
            return None
        return await self.workspaces.read(self.job.workspace_id, path)

    def unified(self, path, original, diff):
        try:
            patch = PatchSet(diff)
            if len(patch) != 1 or patch[0].is_added_file or patch[0].is_removed_file:
                raise ValueError()
            file = patch[0]
            if (
                file.source_file.removeprefix("a/") != path
                or file.target_file.removeprefix("b/") != path
            ):
                raise ValueError()
            source = original.splitlines(keepends=True)
            output = []
            cursor = 0
            for hunk in file:
                begin = max(0, hunk.source_start - 1)
                if begin < cursor or begin > len(source):
                    raise ValueError()
                output.extend(source[cursor:begin])
                cursor = begin
                for line in hunk:
                    if line.line_type == "\\":
                        continue
                    if line.is_context or line.is_removed:
                        if cursor >= len(source) or source[cursor] != line.value:
                            raise ValueError()
                        if line.is_context:
                            output.append(source[cursor])
                        cursor += 1
                    elif line.is_added:
                        output.append(line.value)
            output.extend(source[cursor:])
            return "".join(output)
        except Exception:
            raise SafeError("INVALID_PATCH") from None

    async def propose(self, data):
        await self._job()
        if self.job.mode == "READ_ONLY":
            raise SafeError("POLICY_DENIED")
        data = ProposePatchInput.model_validate(data)
        if len(data.edits) > self.settings.max_patch_files:
            raise SafeError("PATCH_TOO_LARGE")
        paths = [edit.path for edit in data.edits]
        if len(set(paths)) != len(paths):
            raise SafeError("INVALID_PATCH")
        proposal = []
        diffs = []
        added = removed = 0
        deleted = []
        created = []
        for edit in data.edits:
            original = await self._current(edit.path, missing=edit.kind == "new")
            sha = hashlib.sha256(original).hexdigest() if original is not None else None
            if edit.kind == "new":
                if original is not None or edit.expected_sha256 is not None:
                    raise SafeError("STALE_FILE")
                old = ""
                new = edit.new_text
                created.append(edit.path)
            else:
                if original is None or edit.expected_sha256 != sha:
                    raise SafeError("STALE_FILE")
                try:
                    old = original.decode("utf-8")
                except UnicodeError:
                    raise SafeError("BINARY_FILE") from None
                if edit.kind == "exact":
                    if not edit.old_text or old.count(edit.old_text) != 1:
                        raise SafeError("INVALID_PATCH")
                    new = old.replace(edit.old_text, edit.new_text, 1)
                elif edit.kind == "lines":
                    lines = old.splitlines(keepends=True)
                    if (
                        edit.start_line is None
                        or edit.end_line is None
                        or not 1 <= edit.start_line <= edit.end_line <= len(lines)
                    ):
                        raise SafeError("INVALID_PATCH")
                    new = (
                        "".join(lines[: edit.start_line - 1])
                        + edit.new_text
                        + "".join(lines[edit.end_line :])
                    )
                elif edit.kind == "unified":
                    new = self.unified(edit.path, old, edit.new_text)
                elif edit.kind == "full":
                    if len(edit.justification.strip()) < 10:
                        raise SafeError("INVALID_PATCH")
                    new = edit.new_text
                elif edit.kind == "delete":
                    new = None
                    deleted.append(edit.path)
                else:
                    raise SafeError("INVALID_PATCH")
            if (
                new is not None
                and len(new.encode()) > self.settings.max_single_file_size_mb * 1024**2
            ):
                raise SafeError("FILE_TOO_LARGE")
            change = list(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    (new or "").splitlines(keepends=True),
                    fromfile="a/" + edit.path,
                    tofile="b/" + edit.path,
                )
            )
            added += sum(line.startswith("+") and not line.startswith("+++") for line in change)
            removed += sum(line.startswith("-") and not line.startswith("---") for line in change)
            diffs.extend(change)
            proposal.append(
                {
                    "path": edit.path,
                    "original_sha256": sha,
                    "new_text": new,
                    "new_sha256": hashlib.sha256(new.encode()).hexdigest()
                    if new is not None
                    else None,
                }
            )
        summary = {
            "files": paths,
            "added_lines": added,
            "removed_lines": removed,
            "new_files": created,
            "deleted_files": deleted,
            "risk": "HIGH" if deleted or len(paths) > 3 or added + removed > 200 else "MEDIUM",
        }
        ident = str(uuid.uuid4())
        value = WorkspaceChangeSet(
            id=ident,
            workspace_id=self.job.workspace_id,
            job_id=self.job.id,
            status="PROPOSED",
            proposal_encrypted=self.secrets.encrypt(json.dumps(proposal, ensure_ascii=False)),
            diff_encrypted=self.secrets.encrypt("".join(diffs)),
            summary_json=summary,
        )
        self.session.add(value)
        await self.session.flush()
        audit(
            self.session, self.user_id, "FILE_PATCH_PROPOSED", "change_set", ident, count=len(paths)
        )
        return {"change_set_id": ident, "summary": summary}

    async def proposal(self, ident):
        value = await self.owned.change_set(ident)
        if value.workspace_id != self.job.workspace_id or value.job_id != self.job.id:
            raise SafeError("POLICY_DENIED")
        return value

    async def diff(self, ident):
        value = await self.owned.change_set(ident)
        if value.workspace_id != self.job.workspace_id:
            raise SafeError("POLICY_DENIED")
        return {
            "change_set_id": value.id,
            "status": value.status,
            "summary": value.summary_json,
            "diff": self.secrets.decrypt(value.diff_encrypted),
        }

    async def apply(self, ident, approved=False):
        await self._job(True)
        value = await self.proposal(ident)
        if value.status != "PROPOSED":
            raise SafeError("STALE_FILE")
        if (
            value.summary_json["risk"] == "HIGH" or self.settings.require_edit_approval
        ) and not approved:
            raise SafeError("APPROVAL_REQUIRED")
        async with self.workspaces.limits.lock(
            "edit:" + self.job.workspace_id, self.settings.max_task_duration + 60
        ):
            changes = json.loads(self.secrets.decrypt(value.proposal_encrypted))
            snapshots = []
            for change in changes:
                original = await self._current(
                    change["path"], missing=change["original_sha256"] is None
                )
                sha = hashlib.sha256(original).hexdigest() if original is not None else None
                if sha != change["original_sha256"]:
                    raise SafeError("STALE_FILE")
                snapshot = FileSnapshot(
                    change_set_id=value.id,
                    relative_path=change["path"],
                    original_sha256=sha,
                    resulting_sha256=change["new_sha256"],
                    content_encrypted=self.secrets.encrypt(original.decode("utf-8"))
                    if original is not None
                    else None,
                    existed=original is not None,
                )
                self.session.add(snapshot)
                snapshots.append(snapshot)
            value.status = "APPLYING"
            await self.session.commit()
            try:
                for change in changes:
                    if change["new_text"] is None:
                        await asyncio.to_thread(
                            self.workspaces.storage.remove_file,
                            self.user_id,
                            self.job.workspace_id,
                            change["path"],
                        )
                    else:
                        await asyncio.to_thread(
                            self.workspaces.storage.write_file,
                            self.user_id,
                            self.job.workspace_id,
                            change["path"],
                            change["new_text"].encode(),
                        )
                await self.workspaces.index(self.job.workspace_id, agent_job_id=self.job.id)
                value.status = "APPLIED"
                audit(
                    self.session,
                    self.user_id,
                    "FILE_PATCH_APPLIED",
                    "change_set",
                    value.id,
                    count=len(changes),
                )
                await self.session.commit()
            except BaseException:
                # Compensate the whole batch; persistent snapshots also permit crash recovery.
                for snapshot in snapshots:
                    await self._restore(snapshot)
                await self.workspaces.index(self.job.workspace_id, agent_job_id=self.job.id)
                value.status = "ROLLED_BACK"
                await self.session.commit()
                raise
        return {"change_set_id": value.id, "summary": value.summary_json}

    async def _restore(self, snapshot):
        if snapshot.existed:
            await asyncio.to_thread(
                self.workspaces.storage.write_file,
                self.user_id,
                self.job.workspace_id,
                snapshot.relative_path,
                self.secrets.decrypt(snapshot.content_encrypted).encode(),
            )
        else:
            if await self._current(snapshot.relative_path, missing=True) is None:
                return
            try:
                await asyncio.to_thread(
                    self.workspaces.storage.remove_file,
                    self.user_id,
                    self.job.workspace_id,
                    snapshot.relative_path,
                )
            except FileNotFoundError:
                pass

    async def rollback(self, ident, recovery=False):
        value = await self.owned.change_set(ident)
        if value.workspace_id != self.job.workspace_id:
            raise SafeError("POLICY_DENIED")
        if value.status not in ({"APPLYING"} if recovery else {"APPLIED"}):
            raise SafeError("STALE_FILE")
        async with self.workspaces.limits.lock(
            "edit:" + self.job.workspace_id, self.settings.max_task_duration + 60
        ):
            snapshots = list(
                await self.session.scalars(
                    select(FileSnapshot).where(FileSnapshot.change_set_id == value.id)
                )
            )
            for snapshot in snapshots:
                original = await self._current(snapshot.relative_path, missing=True)
                sha = hashlib.sha256(original).hexdigest() if original is not None else None
                allowed = (
                    {snapshot.resulting_sha256, snapshot.original_sha256}
                    if recovery
                    else {snapshot.resulting_sha256}
                )
                if sha not in allowed:
                    raise SafeError("STALE_FILE")
            for snapshot in snapshots:
                await self._restore(snapshot)
            value.status = "ROLLED_BACK"
            await self.workspaces.index(self.job.workspace_id, agent_job_id=self.job.id)
            audit(
                self.session,
                self.user_id,
                "FILE_ROLLBACK",
                "change_set",
                value.id,
                count=len(snapshots),
            )
            await self.session.commit()
        return {"change_set_id": value.id, "restored": len(snapshots)}
