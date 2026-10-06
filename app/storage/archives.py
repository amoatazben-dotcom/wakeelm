import gzip
import io
import stat
import tarfile
import zipfile
from pathlib import PurePosixPath

from app.core.exceptions import SafeError
from app.storage.paths import atomic_write, safe_relative

ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".gz")


class SafeArchiveExtractor:
    def __init__(self, settings):
        self.settings = settings

    def extract(self, data, filename, root):
        if len(data) > self.settings.max_archive_size_mb * 1024**2:
            raise SafeError("ARCHIVE_TOO_LARGE")
        maximum = self.settings.max_extracted_size_mb * 1024**2
        single = self.settings.max_single_file_size_mb * 1024**2
        count, total, seen = 0, 0, set()

        def save(name, stream, size):
            nonlocal count, total
            path = safe_relative(name.rstrip("/"))
            if path in seen:
                raise SafeError("INVALID_ARCHIVE")
            seen.add(path)
            count += 1
            if count > self.settings.max_archive_files:
                raise SafeError("TOO_MANY_FILES")
            if size > single:
                raise SafeError("FILE_TOO_LARGE")
            if total + size > maximum:
                raise SafeError("EXTRACTED_TOO_LARGE")
            # Nested archives are rejected, never recursively extracted.
            if path.lower().endswith(ARCHIVE_SUFFIXES):
                raise SafeError("NESTED_ARCHIVE")
            content = stream.read(min(single, maximum - total) + 1)
            if len(content) > single or total + len(content) > maximum:
                raise SafeError("EXTRACTED_TOO_LARGE")
            total += len(content)
            if len(content) != size:
                raise SafeError("INVALID_ARCHIVE")
            atomic_write(root, path, content)

        try:
            if filename.lower().endswith(".zip"):
                if not data.startswith(b"PK"):
                    raise SafeError("INVALID_ARCHIVE")
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    members = archive.infolist()
                    if len(members) > self.settings.max_archive_files:
                        raise SafeError("TOO_MANY_FILES")
                    for member in members:
                        safe_relative(member.filename.rstrip("/"))
                        mode = member.external_attr >> 16
                        if stat.S_ISLNK(mode) or (
                            stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                        ):
                            raise SafeError("PATH_DENIED")
                        if member.is_dir():
                            continue
                        if member.flag_bits & 1:
                            raise SafeError("INVALID_ARCHIVE")
                        if member.file_size > max(1024**2, member.compress_size * 1000):
                            raise SafeError("EXTRACTED_TOO_LARGE")
                        with archive.open(member) as stream:
                            save(member.filename, stream, member.file_size)
            elif filename.lower().endswith((".tar", ".tar.gz", ".tgz")):
                with tarfile.open(fileobj=io.BytesIO(data), mode="r|*") as archive:
                    members = 0
                    for member in archive:
                        members += 1
                        if members > self.settings.max_archive_files:
                            raise SafeError("TOO_MANY_FILES")
                        safe_relative(member.name.rstrip("/"))
                        if member.isdir():
                            continue
                        if not member.isfile() or member.issym() or member.islnk():
                            raise SafeError("PATH_DENIED")
                        with archive.extractfile(member) as stream:
                            save(member.name, stream, member.size)
            elif filename.lower().endswith(".gz"):
                name = PurePosixPath(filename).name[:-3]
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                    content = stream.read(min(single, maximum) + 1)
                    save(name, io.BytesIO(content), len(content))
            else:
                raise SafeError("INVALID_ARCHIVE")
        except (OSError, EOFError, ValueError, zipfile.BadZipFile, tarfile.TarError, RuntimeError):
            raise SafeError("INVALID_ARCHIVE") from None
        return count, total
