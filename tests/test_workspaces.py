import io
import json
import stat
import tarfile
import zipfile
from types import SimpleNamespace

import pytest

from app.context.engine import ContextEngine
from app.core.exceptions import SafeError
from app.indexing.parsers import decode_text
from app.services.search_service import SearchService
from app.services.workspace_service import WorkspaceService
from app.storage.paths import safe_relative


def config(tmp_path, **values):
    options = dict(
        workspace_storage_root=str(tmp_path / "workspaces"),
        max_upload_size_mb=2,
        max_archive_size_mb=2,
        max_extracted_size_mb=3,
        max_single_file_size_mb=1,
        max_archive_files=100,
        max_project_files=100,
        context_max_tokens=1500,
        context_safety_margin=0.2,
    )
    return SimpleNamespace(**(options | values))


def project_zip(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()


def service(stack, tmp_path, **options):
    return WorkspaceService(
        stack.session, stack.user.id, config(tmp_path, **options), stack.secrets
    )


async def test_project_scan_search_context_and_delete(stack, tmp_path):
    workspaces = service(stack, tmp_path)
    workspace = await workspaces.ingest(
        "project.zip",
        project_zip(
            {
                "app/auth.py": "TIMEOUT = 10\ndef authenticate(user):\n    return user\n",
                "pyproject.toml": '[project]\nname="test"\ndependencies=["fastapi","asyncpg"]\n',
                "node_modules/generated.js": "secret generated content",
                ".gitignore": "ignored.py\n",
                "ignored.py": "password",
            }
        ),
    )
    assert workspace.status == "READY" and workspace.file_count == 5
    manifest = await workspaces.manifest(workspace.id)
    assert "Python" in manifest["languages"] and "fastapi" in manifest["frameworks"]
    search = SearchService(workspaces)
    assert (await search.text(workspace.id, "authenticate"))[0]["path"] == "app/auth.py"
    assert (await search.symbols(workspace.id, "authenticate"))[0]["type"] == "function"
    assert await search.text(workspace.id, "secret generated") == []
    context = await ContextEngine(workspaces).retrieve(
        workspace.id, "Where is authenticate implemented?", {"context_length": 8000}
    )
    assert context.items and context.items[0]["path"] == "app/auth.py"
    assert context.token_estimate <= context.budget
    assert all(item["path"] != "ignored.py" for item in context.items)
    await workspaces.index(workspace.id)
    assert len(await search.symbols(workspace.id, "authenticate")) == 1
    await workspaces.delete(workspace.id)
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await workspaces.read(workspace.id, "app/auth.py")
    assert not workspaces.storage.root_for(stack.user.id, workspace.id).exists()


@pytest.mark.parametrize(
    "name",
    ["../evil.py", "/etc/passwd", "a/../../evil", "C:/windows", "a\\evil.py", "a/./b", "a//b"],
)
async def test_zip_slip(stack, tmp_path, name):
    with pytest.raises(SafeError, match="PATH_DENIED"):
        await service(stack, tmp_path).ingest("project.zip", project_zip({name: "bad"}))


async def test_symlink_archive_and_filesystem(stack, tmp_path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")
    ws = service(stack, tmp_path)
    with pytest.raises(SafeError, match="PATH_DENIED"):
        await ws.ingest("project.zip", output.getvalue())
    workspace = await ws.ingest("safe.py", b"x=1")
    root = ws.storage.root_for(stack.user.id, workspace.id)
    (root / "unsafe").symlink_to("/etc")
    with pytest.raises(SafeError, match="PATH_DENIED"):
        await ws.read(workspace.id, "unsafe/passwd")


async def test_tar_links_and_limits(stack, tmp_path):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        info = tarfile.TarInfo("link")
        info.type = tarfile.LNKTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    with pytest.raises(SafeError, match="PATH_DENIED"):
        await service(stack, tmp_path).ingest("project.tar", output.getvalue())
    with pytest.raises(SafeError, match="TOO_MANY_FILES"):
        await service(stack, tmp_path, max_archive_files=1).ingest(
            "many.zip", project_zip({"a.py": "x", "b.py": "x"})
        )
    with pytest.raises(SafeError, match="UPLOAD_TOO_LARGE"):
        await service(stack, tmp_path).ingest("large.txt", b"x" * (2 * 1024**2 + 1))
    with pytest.raises(SafeError, match="NESTED_ARCHIVE"):
        await service(stack, tmp_path).ingest("nested.zip", project_zip({"inside.zip": "x"}))
    with pytest.raises(SafeError):
        await service(stack, tmp_path).ingest(
            "bomb.zip", project_zip({"large.txt": b"x" * (2 * 1024**2)})
        )


async def test_ownership_binary_and_pagination(stack, tmp_path):
    ws = service(stack, tmp_path)
    workspace = await ws.ingest(
        "files.zip",
        project_zip(
            {f"a{n}.py": "print('safe')" for n in range(23)} | {"blob.bin": b"\x89PNG\x00binary"}
        ),
    )
    first, total = await ws.browse(workspace.id, page=0)
    third, _ = await ws.browse(workspace.id, page=2)
    assert total == 24 and len(first) == 10 and len(third) == 4
    file = next(f for f in await ws.files(workspace.id) if f.relative_path == "blob.bin")
    assert file.is_binary
    other = WorkspaceService(stack.session, 999, ws.settings, stack.secrets)
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await other.owned(workspace.id)
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await other.file(file.id)
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await other.delete(workspace.id)


def test_encoding_and_bad_paths():
    assert decode_text("مرحبا".encode())[0] == "مرحبا"
    assert decode_text("hello".encode("utf-16"))[0] == "hello"
    assert decode_text(b"\x00\x80binary") == (None, None)
    with pytest.raises(SafeError):
        safe_relative("/etc/passwd")


async def test_grounded_qa_citations(stack, tmp_path):
    ws = service(stack, tmp_path)
    workspace = await ws.ingest("auth.py", b"def authenticate(user):\n    return user\n")

    class Models:
        async def active(self):
            return SimpleNamespace(metadata_json={})

        async def completion(self, *args, **kwargs):
            return json.dumps(
                {"answer": "Authentication is in auth.py", "citations": ["auth.py"]}
            ), {}

    result = await ContextEngine(ws).answer(workspace.id, "authenticate", Models())
    assert result["citations"] == ["auth.py"]

    class BadModels(Models):
        async def completion(self, *args, **kwargs):
            return json.dumps({"answer": "invented", "citations": ["not-real.py"]}), {}

    with pytest.raises(SafeError, match="INVALID_RESPONSE"):
        await ContextEngine(ws).answer(workspace.id, "authenticate", BadModels())
