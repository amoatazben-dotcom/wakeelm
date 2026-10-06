import json
import tomllib
from pathlib import PurePosixPath

import pathspec

IGNORED = {
    ".git",
    "node_modules",
    "build",
    "dist",
    ".gradle",
    ".idea",
    ".vscode",
    "target",
    "__pycache__",
    ".venv",
    "venv",
    "coverage",
    ".next",
    ".nuxt",
    "vendor",
}


class IgnoreRules:
    def __init__(self, files, reader):
        patterns = []
        for name in [".gitignore", ".dockerignore"]:
            if name in files:
                try:
                    patterns.extend(reader(name).decode("utf-8").splitlines())
                except (UnicodeError, OSError):
                    pass
        self.spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def ignored(self, path):
        return any(part in IGNORED for part in PurePosixPath(path).parts) or self.spec.match_file(
            path
        )


class ProjectScanner:
    def scan(self, name, files, texts):
        manifest = {
            "project_name": name,
            "languages": sorted({f.language for f in files if f.language and not f.is_ignored}),
            "frameworks": [],
            "build_systems": [],
            "package_managers": [],
            "test_frameworks": [],
            "databases": [],
            "containers": [],
            "ci_systems": [],
            "entrypoints": [],
            "important_files": [],
            "estimated_project_type": "UNKNOWN",
            "metadata": {"evidence": {}},
        }

        def add(key, value, path):
            if value not in manifest[key]:
                manifest[key].append(value)
            manifest["metadata"]["evidence"].setdefault(key + ":" + value, []).append(path)

        deps = {}
        for path, text in texts.items():
            filename = PurePosixPath(path).name
            if filename in {
                "pyproject.toml",
                "requirements.txt",
                "setup.py",
                "package.json",
                "pom.xml",
                "Cargo.toml",
                "go.mod",
                "pubspec.yaml",
                "build.gradle",
                "build.gradle.kts",
                "settings.gradle",
                "settings.gradle.kts",
                "AndroidManifest.xml",
                "Dockerfile",
                "docker-compose.yml",
                "compose.yaml",
            }:
                manifest["important_files"].append(path)
            try:
                if filename == "package.json":
                    data = json.loads(text)
                    deps.update(
                        {
                            key.lower(): path
                            for key in {
                                **data.get("dependencies", {}),
                                **data.get("devDependencies", {}),
                            }
                        }
                    )
                    add("package_managers", "npm", path)
                    add("build_systems", "Node", path)
                    if isinstance(data.get("main"), str):
                        add("entrypoints", str(PurePosixPath(path).parent / data["main"]), path)
                if filename == "pyproject.toml":
                    data = tomllib.loads(text)
                    deps.update(
                        {
                            dep.split("[")[0]
                            .split("=")[0]
                            .split(">")[0]
                            .split("<")[0]
                            .lower(): path
                            for dep in data.get("project", {}).get("dependencies", [])
                            if isinstance(dep, str)
                        }
                    )
                    for section in data.get("tool", {}):
                        if section in {"pytest", "ruff", "mypy"}:
                            add("test_frameworks", section, path)
                    add("package_managers", "pip", path)
                    add("build_systems", "Python", path)
                if filename == "requirements.txt":
                    for dep in text.splitlines():
                        token = (
                            dep.split("[")[0]
                            .split("=")[0]
                            .split(">")[0]
                            .split("<")[0]
                            .strip()
                            .lower()
                        )
                        if token and not token.startswith(("#", "-")):
                            deps[token] = path
                    add("package_managers", "pip", path)
            except (ValueError, TypeError, AttributeError):
                pass
            for marker, key, value in [
                ("pnpm-lock.yaml", "package_managers", "pnpm"),
                ("yarn.lock", "package_managers", "yarn"),
                ("uv.lock", "package_managers", "uv"),
                ("Cargo.toml", "build_systems", "Cargo"),
                ("go.mod", "build_systems", "Go"),
                ("pom.xml", "build_systems", "Maven"),
                ("build.gradle", "build_systems", "Gradle"),
                ("build.gradle.kts", "build_systems", "Gradle"),
                ("AndroidManifest.xml", "frameworks", "Android"),
                ("pubspec.yaml", "build_systems", "Dart"),
            ]:
                if filename == marker:
                    add(key, value, path)
            if filename == "pubspec.yaml" and "sdk: flutter" in text:
                add("frameworks", "Flutter", path)
            if filename in {"Dockerfile", "docker-compose.yml", "compose.yaml"}:
                add("containers", "Docker", path)
            if path.startswith(".github/workflows/"):
                add("ci_systems", "GitHub Actions", path)
            if filename in {"main.py", "app.py", "main.go", "main.rs", "index.js", "index.ts"}:
                add("entrypoints", path, path)
            if filename.startswith("test_") and filename.endswith(".py"):
                add("test_frameworks", "pytest", path)
        for key, path in deps.items():
            for technology in [
                "fastapi",
                "django",
                "flask",
                "react",
                "next",
                "vue",
                "svelte",
                "express",
            ]:
                if key == technology:
                    add("frameworks", technology, path)
            for technology in ["pytest", "vitest", "jest", "mocha"]:
                if key == technology:
                    add("test_frameworks", technology, path)
            for technology in ["asyncpg", "psycopg", "psycopg2", "redis", "pymongo", "sqlite"]:
                if key == technology:
                    add("databases", technology, path)
        if manifest["languages"]:
            manifest["estimated_project_type"] = "SOURCE_PROJECT"
        return manifest
