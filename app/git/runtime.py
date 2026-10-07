import asyncio
import os
import re
import resource
import signal
import uuid
from contextlib import suppress
from pathlib import Path

from app.core.exceptions import SafeError
from app.github.schemas import full_name
from app.storage.paths import safe_relative

REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,200}$")


def ref(value):
    if (
        not isinstance(value, str)
        or not REF.fullmatch(value)
        or ".." in value
        or "//" in value
        or "@{" in value
        or value.endswith(("/", ".", ".lock"))
        or any(x.startswith(".") for x in value.split("/"))
    ):
        raise SafeError("INVALID_REF")
    return value


def agent_branch(slug):
    slug = re.sub(r"[^a-z0-9]+", "-", str(slug).lower()).strip("-")[:50] or "task"
    return "agent/" + slug + "-" + uuid.uuid4().hex[:8]


class ControlledGitService:
    def __init__(self, workspaces, workspace_id):
        self.w, self.workspace_id = workspaces, workspace_id
        self.root = workspaces.storage.root_for(workspaces.user_id, workspace_id)
        self.metadata = workspaces.storage.root_for(workspaces.user_id, workspace_id, "metadata")
        self.gitdir = self.metadata / "repository.git"
        self.home = self.metadata / "git-home"
        self.home.mkdir(mode=0o700, exist_ok=True)
        self.hooks = self.metadata / "empty-hooks"
        self.hooks.mkdir(mode=0o700, exist_ok=True)

    def environment(self, token=None):
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
        # Proxy transport is operational config, not project env. Never inherit production keys.
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
            "SSL_CERT_FILE",
        ):
            if os.environ.get(key):
                env[key] = os.environ[key]
        if token:
            helper = self.metadata / "askpass"
            helper.write_text(
                "#!/bin/sh\nexec /usr/local/bin/python "
                + str(Path(__file__).with_name("askpass.py"))
                + ' "$@"\n'
            )
            helper.chmod(0o700)
            env.update(GIT_ASKPASS=str(helper), WAKEELM_GIT_CREDENTIAL=token)
        return env

    def metadata_size(self):
        total = 0
        for path in self.gitdir.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue  # Git may atomically replace a lock/temporary object during observation.
        return total

    async def _run(self, *args, token=None):
        await self.w.owned(self.workspace_id)
        if self.gitdir.is_symlink() or self.root.is_symlink():
            raise SafeError("PATH_DENIED")
        command = [
            "git",
            "--no-pager",
            "-c",
            "credential.helper=",
            "-c",
            f"core.hooksPath={self.hooks}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.attributesFile=/dev/null",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.https.allow=always",
            "-c",
            "http.followRedirects=false",
            "-c",
            "http.sslVerify=true",
            "-c",
            "fetch.fsckObjects=true",
            "-c",
            "transfer.fsckObjects=true",
            "-c",
            "submodule.recurse=false",
            "--git-dir=" + str(self.gitdir),
            "--work-tree=" + str(self.root),
            *args,
        ]
        process = None
        monitor = None
        try:
            async with asyncio.timeout(self.w.settings.git_timeout_seconds):
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=self.root,
                    env=self.environment(token),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )

                try:
                    memory = self.w.settings.git_max_memory_mb * 1024**2
                    resource.prlimit(process.pid, resource.RLIMIT_AS, (memory, memory))
                    resource.prlimit(
                        process.pid,
                        resource.RLIMIT_FSIZE,
                        (
                            self.w.settings.git_max_repository_bytes,
                            self.w.settings.git_max_repository_bytes,
                        ),
                    )
                    resource.prlimit(
                        process.pid,
                        resource.RLIMIT_CPU,
                        (
                            self.w.settings.git_timeout_seconds,
                            self.w.settings.git_timeout_seconds + 1,
                        ),
                    )
                except ProcessLookupError:
                    pass  # The command already exited; output/exit-code checks still apply.

                async def bounded(stream):
                    content = bytearray()
                    while chunk := await stream.read(8192):
                        content.extend(chunk)
                        if len(content) > self.w.settings.git_max_output_bytes:
                            raise SafeError("RESPONSE_TOO_LARGE")
                        size = self.metadata_size() if self.gitdir.exists() else 0
                        if size > self.w.settings.git_max_repository_bytes:
                            raise SafeError("REPOSITORY_TOO_LARGE")
                    return bytes(content)

                async def monitor_disk():
                    while process.returncode is None:
                        size = self.metadata_size() if self.gitdir.exists() else 0
                        if size > self.w.settings.git_max_repository_bytes:
                            raise SafeError("REPOSITORY_TOO_LARGE")
                        await asyncio.sleep(0.1)

                monitor = asyncio.create_task(monitor_disk())
                io_task = asyncio.gather(bounded(process.stdout), bounded(process.stderr))
                wait_task = asyncio.create_task(process.wait())
                try:
                    done, _ = await asyncio.wait(
                        [io_task, monitor], return_when=asyncio.FIRST_COMPLETED
                    )
                    if monitor in done:
                        await monitor
                    stdout, stderr = await io_task
                    done, _ = await asyncio.wait(
                        [wait_task, monitor], return_when=asyncio.FIRST_COMPLETED
                    )
                    if monitor in done:
                        await monitor
                    await wait_task
                finally:
                    for task in (io_task, wait_task):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(io_task, wait_task, return_exceptions=True)
                if process.returncode:
                    raise SafeError("GIT_FAILED")
                return stdout
        except TimeoutError:
            raise SafeError("TIMEOUT") from None
        except OSError:
            raise SafeError("GIT_UNAVAILABLE") from None
        finally:
            if monitor:
                monitor.cancel()
                with suppress(asyncio.CancelledError, SafeError, OSError):
                    await monitor
            if process and process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()

    async def clone_repository(self, url, base_ref, token):
        expected = "https://github.com/"
        if not url.startswith(expected) or not url.endswith(".git"):
            raise SafeError("INVALID_REPOSITORY")
        full_name(url[len(expected) : -4])
        ref(base_ref)
        if self.gitdir.exists():
            raise SafeError("STALE_REPOSITORY")
        await self._run("init", "--initial-branch=" + base_ref)
        await self._run("remote", "add", "origin", url)
        await self._run(
            "fetch",
            "--no-tags",
            "--depth=1",
            "origin",
            f"refs/heads/{base_ref}:refs/remotes/origin/{base_ref}",
            token=token,
        )
        await self.validate_tree("refs/remotes/origin/" + base_ref)
        await self._run("checkout", "-b", base_ref, "refs/remotes/origin/" + base_ref)
        return await self.head()

    async def validate_tree(self, tree="HEAD"):
        records = (await self._run("ls-tree", "-r", "-z", ref(tree))).split(b"\0")
        count = total = 0
        for record in records:
            if not record:
                continue
            metadata, path = record.split(b"\t", 1)
            mode, kind, sha = metadata.decode().split()
            path = safe_relative(path.decode("utf-8"))
            if (
                mode not in {"100644", "100755"}
                or kind != "blob"
                or ".git" in [x.lower() for x in path.split("/")]
            ):
                raise SafeError("PATH_DENIED")
            count += 1
            size = int((await self._run("cat-file", "-s", sha)).strip())
            total += size
            if (
                count > self.w.settings.max_project_files
                or size > self.w.settings.max_single_file_size_mb * 1024**2
                or total > self.w.settings.max_extracted_size_mb * 1024**2
            ):
                raise SafeError("REPOSITORY_TOO_LARGE")
        return {"files": count, "bytes": total}

    async def fetch(self, token):
        info = await self.get_remote_info()
        base = ref(info["base_ref"])
        await self._run(
            "fetch",
            "--no-tags",
            "origin",
            f"refs/heads/{base}:refs/remotes/origin/{base}",
            token=token,
        )
        return await self.remote_sha(base)

    async def head(self):
        return (await self._run("rev-parse", "HEAD")).decode().strip()

    async def remote_sha(self, branch):
        return (await self._run("rev-parse", "refs/remotes/origin/" + ref(branch))).decode().strip()

    async def status(self):
        raw = (await self._run("status", "--porcelain=v1", "-z", "--untracked-files=all")).split(
            b"\0"
        )
        result = []
        index = 0
        while index < len(raw):
            row = raw[index]
            index += 1
            if not row:
                continue
            code = row[:2].decode()
            path = safe_relative(row[3:].decode("utf-8"))
            result.append({"status": code, "path": path})
            if "R" in code or "C" in code:
                if index >= len(raw):
                    raise SafeError("INVALID_RESPONSE")
                result[-1]["old_path"] = safe_relative(raw[index].decode())
                index += 1
        return result

    async def current_branch(self):
        return (await self._run("symbolic-ref", "--short", "HEAD")).decode().strip()

    async def list_branches(self):
        return (
            (
                await self._run(
                    "for-each-ref",
                    "--format=%(refname:short)",
                    "refs/heads/",
                    "refs/remotes/origin/",
                )
            )
            .decode()
            .splitlines()
        )

    async def create_branch(self, branch):
        branch = ref(branch)
        if not branch.startswith("agent/"):
            raise SafeError("PROTECTED_BRANCH")
        await self._run("checkout", "-b", branch)
        return branch

    async def checkout(self, branch):
        branch = ref(branch)
        if not branch.startswith("agent/"):
            raise SafeError("PROTECTED_BRANCH")
        await self.validate_tree(branch)
        await self._run("checkout", branch)

    async def diff(self):
        return (await self._run("diff", "--no-ext-diff", "--no-textconv", "HEAD", "--")).decode(
            "utf-8", errors="replace"
        )

    async def log(self):
        return (await self._run("log", "-10", "--format=%H %s")).decode("utf-8", errors="replace")

    async def get_changed_files(self):
        return sorted({row["path"] for row in await self.status()})

    async def stage_paths(self, paths):
        if not paths or len(paths) > 100:
            raise SafeError("INVALID_INPUT")
        clean = [safe_relative(p) for p in paths]
        await self._run("add", "--", *clean)
        return clean

    async def commit(self, message):
        if not message.strip() or len(message) > 200 or any(ord(c) < 32 for c in message):
            raise SafeError("INVALID_INPUT")
        await self._run(
            "-c",
            "user.name=" + self.w.settings.github_bot_name,
            "-c",
            "user.email=" + self.w.settings.github_bot_email,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--no-verify",
            "-m",
            message,
        )
        return await self.head()

    async def push_branch(self, branch, token):
        branch = ref(branch)
        if not branch.startswith("agent/") or await self.current_branch() != branch:
            raise SafeError("PROTECTED_BRANCH")
        await self._run("push", "--porcelain", "origin", f"HEAD:refs/heads/{branch}", token=token)
        return await self.head()

    async def restore_paths(self, paths):
        await self._run(
            "restore",
            "--source=HEAD",
            "--staged",
            "--worktree",
            "--",
            *[safe_relative(p) for p in paths],
        )

    async def get_remote_info(self):
        url = (await self._run("remote", "get-url", "origin")).decode().strip()
        if not url.startswith("https://github.com/") or not url.endswith(".git"):
            raise SafeError("INVALID_REPOSITORY")
        full_name(url[len("https://github.com/") : -4])
        # Exactly one canonical remote, no credential/helper/hook config can persist in this metadata.
        config = (await self._run("config", "--local", "--list")).decode()
        allowed_keys = {
            "core.repositoryformatversion",
            "core.filemode",
            "core.bare",
            "core.logallrefupdates",
            "core.worktree",
            "remote.origin.url",
            "remote.origin.fetch",
        }
        worktree = (await self._run("config", "--local", "--get", "core.worktree")).decode().strip()
        if Path(worktree).resolve() != self.root.resolve():
            raise SafeError("UNSAFE_GIT_CONFIG")
        keys = [line.split("=", 1)[0] for line in config.splitlines()]
        if (
            any(
                key not in allowed_keys
                and not re.fullmatch(r"branch\.[A-Za-z0-9_./-]+\.(remote|merge)", key)
                for key in keys
            )
            or "@github.com" in config
            or len((await self._run("remote")).splitlines()) != 1
        ):
            raise SafeError("UNSAFE_GIT_CONFIG")
        from sqlalchemy import select

        from app.db.models.integrations import RepositoryWorkspace

        link = await self.w.session.scalar(
            select(RepositoryWorkspace).where(
                RepositoryWorkspace.workspace_id == self.workspace_id,
                RepositoryWorkspace.user_id == self.w.user_id,
            )
        )
        if not link:
            raise SafeError("NOT_FOUND")
        return {"url": url, "remote": "origin", "base_ref": link.base_ref}

    async def staged_paths(self):
        return [
            safe_relative(path.decode())
            for path in (await self._run("diff", "--cached", "--name-only", "-z", "--")).split(
                b"\0"
            )
            if path
        ]
