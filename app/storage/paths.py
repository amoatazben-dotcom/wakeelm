import os
import stat
from pathlib import PurePosixPath

from app.core.exceptions import SafeError


def safe_relative(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or any(ord(c) < 32 for c in value)
    ):
        raise SafeError("PATH_DENIED")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in {".", "..", ""} for p in value.split("/")):
        raise SafeError("PATH_DENIED")
    return str(path)


def open_parent(root, relative, create=False):
    parts = safe_relative(relative).split("/")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd, parts[-1]
    except OSError:
        os.close(fd)
        raise SafeError("PATH_DENIED") from None


def read_bounded(root, relative, limit):
    parent, name = open_parent(root, relative)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise SafeError("FILE_TOO_LARGE")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise SafeError("FILE_TOO_LARGE")
            return data
        finally:
            os.close(fd)
    except OSError:
        raise SafeError("PATH_DENIED") from None
    finally:
        os.close(parent)


def atomic_write(root, relative, data, create=True):
    import uuid

    parent, name = open_parent(root, relative, create)
    temp = ".write-" + uuid.uuid4().hex
    try:
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise SafeError("PATH_DENIED")
        except FileNotFoundError:
            pass
        fd = os.open(
            temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temp, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)


def exists_regular(root, relative):
    """Check absence without following symlinks, including absent parent directories."""
    parts = safe_relative(relative).split("/")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                return False
            os.close(fd)
            fd = next_fd
        try:
            info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(info.st_mode):
            raise SafeError("PATH_DENIED")
        return True
    except OSError:
        raise SafeError("PATH_DENIED") from None
    finally:
        os.close(fd)
