# Validation sandbox

`SANDBOX_BACKEND=disabled` is the safe default. Commands fail with SANDBOX_UNAVAILABLE; there is no local-host fallback. `docker` uses a prebuilt administrator-controlled image and the local Docker daemon. It never builds an uploaded Dockerfile, pulls images during a task, installs project dependencies over the network, or accepts model shell/argv.

Build the trusted Python image separately:

```sh
docker build -f docker/validation.Dockerfile -t wakeelm-validation:local .
# Operators may add offline dependencies/toolchains to a separately reviewed image.
```

The tested image contains Python 3.13, pytest, Ruff and mypy. Other registered commands require a corresponding trusted Node/Android/Flutter/Rust/Go toolchain and cached dependencies. Detection is project evidence, not a guarantee of an installed compiler. Missing dependencies fail visibly; they are not downloaded automatically. Fixed IDs: python_tests/python_lint/python_types; node_tests/node_lint/node_build (only existing root package scripts); android_tests/android_lint; flutter_tests/dart_analyze; rust_tests/rust_check; go_tests. Each maps to code-owned argv in `app/sandbox/commands.py`. Root project commands may need project-specific setup for monorepos.

For each approved run, bounded regular workspace files are copied into a disposable metadata directory. Only that copy is mounted at /workspace. Docker uses `--network=none`, read-only root, UID/GID 65534, no capabilities, no-new-privileges, default seccomp, 64 PIDs, 256 MB memory, one CPU and limited tmpfs home/tmp. Production env is never passed to the Docker client/container. A clean per-run Docker config prevents implicit proxy/credential injection. The socket and all source/other-user directories are absent from the container. Host `/etc/passwd` is not exposed; a container has its own normal filesystem. Container networking blocks provider APIs, host services and cloud metadata.

Timeout/cancellation forcibly removes the container and kills the bounded Docker client. First/last output is capped in memory with a truncation marker, encrypted in ValidationRun, and shown only to the owner. Temporary copies/config are deleted; test-generated changes never affect the live project. Commands may execute arbitrary uploaded test/build code **inside** this boundary, so approval and isolation are both mandatory.

Docker is a kernel-sharing isolation boundary, not a VM. Use a dedicated patched validation host; mounting a Docker socket into the API grants that trusted API host control. Do not deploy this socket configuration casually on a shared production host. Railway's normal app runtime has no local Docker daemon: keep sandbox disabled there until a separately authenticated isolated validation worker/backend is provisioned. Stage 5 must implement that hosted integration if command execution on Railway is required.

Real-container checks are opt-in:

```sh
TEST_SANDBOX_IMAGE=wakeelm-validation:local pytest tests/test_sandbox_integration.py -q
```

They verify no production env/proxy, no host file/socket, nonroot/read-only root, network/metadata blocked, copy isolation, timeout, cancellation, output bounds and fail→repair→pass with separate approvals. No real Telegram/provider credential is needed.
