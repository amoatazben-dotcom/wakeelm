import shutil
import stat
import uuid
from pathlib import Path

from app.core.exceptions import SafeError
from app.storage.archives import SafeArchiveExtractor
from app.storage.paths import atomic_write, read_bounded, safe_relative


class LocalWorkspaceStorage:
    def __init__(self, settings):
        self.settings = settings
        self.root = Path(settings.workspace_storage_root).absolute()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise SafeError("PATH_DENIED")

    def root_for(self, user_id, workspace_id, area="working"):
        if not isinstance(user_id, int) or user_id < 1:
            raise SafeError("PATH_DENIED")
        try:
            ident = str(uuid.UUID(str(workspace_id)))
        except ValueError:
            raise SafeError("PATH_DENIED") from None
        if area not in {"source", "extracted", "working", "metadata"}:
            raise SafeError("PATH_DENIED")
        root = self.root / str(user_id) / ident / area
        for part in [self.root, self.root / str(user_id), root.parent, root]:
            if part.is_symlink():
                raise SafeError("PATH_DENIED")
        return root

    def create_workspace(self, user_id, workspace_id):
        for area in ["source", "extracted", "working", "metadata"]:
            self.root_for(user_id, workspace_id, area).mkdir(
                parents=True, mode=0o700, exist_ok=False
            )
        return str(self.root_for(user_id, workspace_id).parent)

    def save_upload(self, user_id, workspace_id, filename, data):
        safe_relative(filename)
        if "/" in filename or len(filename) > 255:
            raise SafeError("PATH_DENIED")
        if len(data) > self.settings.max_upload_size_mb * 1024**2:
            raise SafeError("UPLOAD_TOO_LARGE")
        atomic_write(self.root_for(user_id, workspace_id, "source"), filename, data)

    def extract_archive(self, user_id, workspace_id, filename, data):
        result = SafeArchiveExtractor(self.settings).extract(
            data, filename, self.root_for(user_id, workspace_id, "extracted")
        )
        for path in self._files(self.root_for(user_id, workspace_id, "extracted")):
            content = read_bounded(
                self.root_for(user_id, workspace_id, "extracted"),
                path,
                self.settings.max_single_file_size_mb * 1024**2,
            )
            self.write_file(user_id, workspace_id, path, content)
        return result

    def _files(self, root):
        if not root.is_dir():
            raise SafeError("WORKSPACE_STORAGE_MISSING")
        files = []
        for path in root.rglob("*"):
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise SafeError("PATH_DENIED")
            if stat.S_ISREG(mode):
                files.append(path.relative_to(root).as_posix())
            if len(files) > self.settings.max_project_files:
                raise SafeError("TOO_MANY_FILES")
        return sorted(files)

    def list_files(self, user_id, workspace_id):
        return self._files(self.root_for(user_id, workspace_id))

    def read_file(self, user_id, workspace_id, path):
        return read_bounded(
            self.root_for(user_id, workspace_id),
            path,
            self.settings.max_single_file_size_mb * 1024**2,
        )

    def write_file(self, user_id, workspace_id, path, data):
        if len(data) > self.settings.max_single_file_size_mb * 1024**2:
            raise SafeError("FILE_TOO_LARGE")
        atomic_write(self.root_for(user_id, workspace_id), path, data)

    def remove_file(self, user_id, workspace_id, path):
        import os

        from app.storage.paths import open_parent

        parent, name = open_parent(self.root_for(user_id, workspace_id), path)
        try:
            if not stat.S_ISREG(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
                raise SafeError("PATH_DENIED")
            os.unlink(name, dir_fd=parent)
        finally:
            os.close(parent)

    def delete_workspace(self, user_id, workspace_id):
        root = self.root_for(user_id, workspace_id).parent
        if root.exists():
            shutil.rmtree(root)
