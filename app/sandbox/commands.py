from app.core.exceptions import SafeError

COMMANDS = {
    "python_tests": ("python", "-m", "pytest", "-q", "-p", "no:cacheprovider"),
    "python_lint": ("ruff", "check", "."),
    "python_types": ("mypy", "."),
    "node_tests": ("npm", "test"),
    "node_lint": ("npm", "run", "lint"),
    "node_build": ("npm", "run", "build"),
    "android_tests": ("sh", "./gradlew", "test", "--offline", "--no-daemon"),
    "android_lint": ("sh", "./gradlew", "lint", "--offline", "--no-daemon"),
    "flutter_tests": ("flutter", "test", "--no-pub"),
    "dart_analyze": ("dart", "analyze"),
    "rust_tests": ("cargo", "test", "--offline"),
    "rust_check": ("cargo", "check", "--offline"),
    "go_tests": ("go", "test", "./..."),
}


class ValidationCommandDetector:
    def detect(self, manifest):
        commands = []
        languages = set(manifest.get("languages", []))
        builds = set(manifest.get("build_systems", []))
        tests = set(manifest.get("test_frameworks", []))
        frameworks = set(manifest.get("frameworks", []))
        if "Python" in languages:
            if "pytest" in tests:
                commands.append("python_tests")
            if "ruff" in tests:
                commands.append("python_lint")
            if "mypy" in tests:
                commands.append("python_types")
        if "Node" in builds:
            mapping = {"test": "node_tests", "lint": "node_lint", "build": "node_build"}
            commands.extend(
                mapping[name] for name in manifest.get("validation_scripts", []) if name in mapping
            )
        if "Android" in frameworks or "Gradle" in builds:
            commands.extend(["android_tests", "android_lint"])
        if "Flutter" in frameworks:
            commands.append("flutter_tests")
        if "Dart" in languages:
            commands.append("dart_analyze")
        if "Rust" in languages or "Cargo" in builds:
            commands.extend(["rust_tests", "rust_check"])
        if "Go" in languages:
            commands.append("go_tests")
        return [
            {
                "command_id": key,
                "argv": list(COMMANDS[key]),
                "requires_approval": True,
                "network": "DISABLED",
            }
            for key in dict.fromkeys(commands)
        ]

    def resolve(self, command_id, manifest):
        if command_id not in {item["command_id"] for item in self.detect(manifest)}:
            raise SafeError("COMMAND_DENIED")
        return list(COMMANDS[command_id])
