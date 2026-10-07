from pathlib import PurePosixPath

from app.core.exceptions import SafeError
from app.integrations.sanitizer import PATTERNS


class RepositorySafetyScanner:
    async def scan(self, workspaces, workspace_id, paths):
        findings = []
        for path in paths:
            name = PurePosixPath(path).name.lower()
            parts = {part.lower() for part in PurePosixPath(path).parts}
            if (
                name == ".env"
                or name.startswith(".env.")
                and name not in {".env.example", ".env.sample", ".env.template"}
                or name in {"credentials.json", "id_rsa", "id_ed25519", ".npmrc", ".pypirc"}
            ):
                findings.append({"path": path, "kind": "credential_file"})
            if parts & {"node_modules", "dist", "build", "target", ".git"} or name.endswith(
                (
                    ".apk",
                    ".aab",
                    ".sql",
                    ".dump",
                    ".zip",
                    ".tar",
                    ".gz",
                    ".7z",
                    ".rar",
                    ".p12",
                    ".pem",
                )
            ):
                findings.append({"path": path, "kind": "artifact"})
            try:
                data = await workspaces.read(workspace_id, path)
            except SafeError:
                # Deletions have no new content; deny all other errors.
                from app.storage.paths import exists_regular

                if not exists_regular(
                    workspaces.storage.root_for(workspaces.user_id, workspace_id), path
                ):
                    continue
                raise
            if len(data) > min(1000000, workspaces.settings.max_single_file_size_mb * 1024**2):
                findings.append({"path": path, "kind": "large_file"})
            text = data.decode("utf-8", errors="replace")
            for kind, pattern in PATTERNS:
                if pattern.search(text):
                    findings.append({"path": path, "kind": kind})
        return findings

    async def enforce(self, *args):
        findings = await self.scan(*args)
        if findings:
            raise SafeError("REPOSITORY_SECRET_OR_ARTIFACT")
        return {"passed": True}
