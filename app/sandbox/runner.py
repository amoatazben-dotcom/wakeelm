import asyncio
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.exceptions import SafeError
from app.sandbox.commands import ValidationCommandDetector


@dataclass
class CommandResult:
    exit_code: int | None
    duration_ms: int
    output: str
    truncated: bool
    status: str


class SandboxCommandRunner(Protocol):
    async def run(self, workspaces, job, command_id, cancelled): ...


class DisabledRunner:
    async def run(self, *args, **kwargs):
        raise SafeError("SANDBOX_UNAVAILABLE")


class OutputBuffer:
    def __init__(self, limit):
        self.limit = limit
        self.first = bytearray()
        self.last = bytearray()
        self.total = 0

    def append(self, data):
        self.total += len(data)
        half = self.limit // 2
        if len(self.first) < half:
            self.first.extend(data[: half - len(self.first)])
        self.last.extend(data)
        self.last = self.last[-half:]

    def render(self):
        truncated = self.total > self.limit
        if self.total <= self.limit:
            overlap = max(0, len(self.first) + len(self.last) - self.total)
            content = bytes(self.first) + bytes(self.last[overlap:])
        else:
            content = bytes(self.first) + b"\n[TRUNCATED]\n" + bytes(self.last)
        text = content.decode("utf-8", errors="replace")
        encoded = text.encode()
        if len(encoded) > self.limit:
            marker = b"\n[TRUNCATED]\n"
            half = (self.limit - len(marker)) // 2
            text = (
                encoded[:half].decode("utf-8", errors="ignore")
                + marker.decode()
                + encoded[-half:].decode("utf-8", errors="ignore")
            )
            truncated = True
        return text, truncated


class DockerSandboxRunner:
    def __init__(self, settings):
        self.settings = settings

    def docker_argv(self, name, mount, argv):
        image = self.settings.sandbox_image
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,250}", image):
            raise SafeError("SANDBOX_UNAVAILABLE")
        return [
            "docker",
            "--host=unix:///var/run/docker.sock",
            "run",
            "--rm",
            "--pull=never",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory=256m",
            "--cpus=1",
            "--user=65534:65534",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=64m,mode=1777",
            "--tmpfs=/home/sandbox:rw,nosuid,nodev,size=32m,mode=1777",
            "--mount",
            f"type=bind,src={mount},dst=/workspace",
            "--workdir=/workspace",
            "--env=HOME=/home/sandbox",
            "--env=PATH=/usr/local/bin:/usr/bin:/bin",
            "--env=LANG=C.UTF-8",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--env=PYTHONNOUSERSITE=1",
            "--env=GOPROXY=off",
            "--env=GOTOOLCHAIN=local",
            "--env=CARGO_NET_OFFLINE=true",
            image,
            *argv,
        ]

    def environment(self):
        return {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}

    async def _stop(self, name):
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "--host=unix:///var/run/docker.sock",
                "rm",
                "-f",
                name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=self.environment(),
            )
            await asyncio.wait_for(process.wait(), 5)
        except (OSError, TimeoutError):
            if process and process.returncode is None:
                process.kill()
                await process.wait()

    async def run(self, workspaces, job, command_id, cancelled):
        await workspaces.owned(job.workspace_id)
        manifest = await workspaces.manifest(job.workspace_id)
        argv = ValidationCommandDetector().resolve(command_id, manifest)
        if await cancelled():
            raise SafeError("JOB_CANCELLED")
        name = "wakeelm-" + uuid.uuid4().hex
        # Copy only bounded, no-symlink workspace files; never mount live project or host secrets.
        parent = workspaces.storage.root_for(workspaces.user_id, job.workspace_id, "metadata")
        root = Path(tempfile.mkdtemp(prefix="validation-", dir=parent))
        config = Path(tempfile.mkdtemp(prefix="docker-config-", dir=parent))
        (config / "config.json").write_text("{}")
        process = None
        reader_task = None
        started = time.monotonic()
        buffer = OutputBuffer(self.settings.max_command_output_bytes)
        try:
            for path in workspaces.storage.list_files(workspaces.user_id, job.workspace_id):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(
                    workspaces.storage.read_file(workspaces.user_id, job.workspace_id, path)
                )
                target.chmod(0o666)
            root.chmod(0o777)
            for directory in root.rglob("*"):
                if directory.is_dir():
                    directory.chmod(0o777)
            process = await asyncio.create_subprocess_exec(
                *["docker", "--config", str(config), *self.docker_argv(name, root, argv)[1:]],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=self.environment(),
                start_new_session=True,
            )

            async def drain():
                while chunk := await process.stdout.read(8192):
                    buffer.append(chunk)

            reader_task = asyncio.create_task(drain())
            wait_task = asyncio.create_task(process.wait())
            status = "COMPLETED"
            while process.returncode is None:
                if await cancelled():
                    status = "CANCELLED"
                    await self._stop(name)
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    break
                if time.monotonic() - started > self.settings.command_timeout:
                    status = "TIMEOUT"
                    await self._stop(name)
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    break
                try:
                    await asyncio.wait_for(asyncio.shield(wait_task), 0.2)
                except TimeoutError:
                    pass
            await process.wait()
            await reader_task
            output, truncated = buffer.render()
            if process.returncode == 125 and status == "COMPLETED":
                raise SafeError("SANDBOX_UNAVAILABLE")
            return CommandResult(
                process.returncode,
                int((time.monotonic() - started) * 1000),
                output,
                truncated,
                status,
            )
        except OSError:
            raise SafeError("SANDBOX_UNAVAILABLE") from None
        finally:
            if process and process.returncode is None:
                await self._stop(name)
                try:
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                except ProcessLookupError:
                    pass
                await process.wait()
            if reader_task and not reader_task.done():
                reader_task.cancel()
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(config, ignore_errors=True)


def runner_for(settings):
    return (
        DockerSandboxRunner(settings) if settings.sandbox_backend == "docker" else DisabledRunner()
    )
