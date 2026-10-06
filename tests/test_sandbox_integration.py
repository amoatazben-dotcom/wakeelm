"""Opt-in tests exercise real Docker isolation, not a fake subprocess runner."""

import asyncio
import os
import time

import pytest
from test_agent import never, setup

from app.sandbox.runner import DockerSandboxRunner

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_SANDBOX_IMAGE"),
    reason="Set TEST_SANDBOX_IMAGE to a prebuilt trusted validation image",
)


async def sandbox(stack, tmp_path, code, timeout=10):
    w, agents, job = await setup(stack, tmp_path)
    w.settings.sandbox_backend = "docker"
    w.settings.sandbox_image = os.environ["TEST_SANDBOX_IMAGE"]
    w.settings.command_timeout = timeout
    w.storage.write_file(w.user_id, job.workspace_id, "test_main.py", code.encode())
    await w.index(job.workspace_id, agent_job_id=job.id)
    return w, job, DockerSandboxRunner(w.settings)


async def test_real_container_network_secrets_and_host_paths(stack, tmp_path, monkeypatch):
    secret = tmp_path / "host-secret.txt"
    secret.write_text("host-only-secret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "production-secret")
    monkeypatch.setenv("MASTER_ENCRYPTION_KEY", "production-key")
    monkeypatch.setenv("HTTP_PROXY", "http://production-proxy")
    code = f"""import os,socket,pathlib

def test_isolation():
    for key in ('TELEGRAM_BOT_TOKEN','DATABASE_URL','REDIS_URL','MASTER_ENCRYPTION_KEY','HTTP_PROXY','HTTPS_PROXY'):
        assert key not in os.environ
    assert not pathlib.Path({str(secret)!r}).exists()
    assert not pathlib.Path('/var/run/docker.sock').exists()
    assert os.getuid()==65534
    for target in ('169.254.169.254','1.1.1.1'):
        connection=socket.socket();connection.settimeout(.3)
        try:connection.connect((target,80))
        except OSError:pass
        else:raise AssertionError('network allowed')
        finally:connection.close()
    try:pathlib.Path('/etc/host-write').write_text('bad')
    except OSError:pass
    else:raise AssertionError('root filesystem writable')
    pathlib.Path('main.py').write_text('changed only inside disposable copy')
"""
    w, job, runner = await sandbox(stack, tmp_path, code)
    result = await runner.run(w, job, "python_tests", never)
    assert result.status == "COMPLETED" and result.exit_code == 0, result.output
    assert await w.read(job.workspace_id, "main.py") == b"VALUE = 1\n"


async def test_real_container_timeout_and_output_limit(stack, tmp_path):
    code = "import time\nprint('X'*10000,flush=True)\ndef test_wait():\n    time.sleep(30)\n"
    w, job, runner = await sandbox(stack, tmp_path, code, timeout=10)
    # pytest -q captures import output; failure emits it while timeout still bounds runtime.
    code = "import time\ndef test_wait():\n    print('X'*10000,flush=True)\n    assert False\n"
    w.storage.write_file(w.user_id, job.workspace_id, "test_main.py", code.encode())
    result = await runner.run(w, job, "python_tests", never)
    assert result.exit_code == 1 and result.truncated and len(result.output.encode()) <= 1037
    w.storage.write_file(
        w.user_id,
        job.workspace_id,
        "test_main.py",
        b"import time\ndef test_wait():\n    time.sleep(30)\n",
    )
    w.settings.command_timeout = 2
    started = time.monotonic()
    result = await runner.run(w, job, "python_tests", never)
    assert result.status == "TIMEOUT" and time.monotonic() - started < 10


async def test_real_container_cancel_terminates(stack, tmp_path):
    w, job, runner = await sandbox(
        stack, tmp_path, "import time\ndef test_wait():\n    time.sleep(30)\n"
    )
    stop = False

    async def cancelled():
        return stop

    task = asyncio.create_task(runner.run(w, job, "python_tests", cancelled))
    await asyncio.sleep(0.7)
    stop = True
    result = await asyncio.wait_for(task, 8)
    assert result.status == "CANCELLED"


async def test_real_job_failed_test_repair_and_pass(stack, tmp_path):
    import hashlib

    from test_agent import Models, plan

    from app.agent.orchestrator import AgentOrchestrator
    from app.agent.schemas import AgentPlan
    from app.services.agent_service import AgentService

    w, job, runner = await sandbox(
        stack, tmp_path, "from main import VALUE\ndef test_value():\n    assert VALUE == 3\n"
    )
    agents = AgentService(w, Models())

    class RepairPlanner:
        calls = 0

        async def plan(self, job, registry, observations=None):
            self.calls += 1
            old = "VALUE = 1" if self.calls == 1 else "VALUE = 2"
            new = "VALUE = 2" if self.calls == 1 else "VALUE = 3"
            data = {
                "edits": [
                    {
                        "path": "main.py",
                        "kind": "exact",
                        "expected_sha256": hashlib.sha256(
                            await w.read(job.workspace_id, "main.py")
                        ).hexdigest(),
                        "old_text": old,
                        "new_text": new,
                    }
                ]
            }
            if self.calls > 1:
                assert observations[0]["status"] == "FAILED"
            return AgentPlan.model_validate(
                plan(
                    ("workspace.propose_patch", data),
                    ("workspace.apply_patch", {"change_set_id": "$last_patch"}),
                    ("validation.run", {"command_id": "python_tests"}),
                )
            )

    planner = RepairPlanner()
    runtime = AgentOrchestrator(w, Models(), planner, runner)
    for _ in range(3):
        await runtime.run(job.id)
        if job.status != "WAITING_APPROVAL":
            break
        await agents.approvals.decide((await agents.pending(job.id))[0].id, True)
    assert job.status == "COMPLETED", job.failure_code
    assert job.repair_count == 1 and job.tool_calls_count == 6 and planner.calls == 2
    assert await w.read(job.workspace_id, "main.py") == b"VALUE = 3\n"
