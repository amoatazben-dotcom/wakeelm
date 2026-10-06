import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_workspaces import config, project_zip

from app.agent.approvals import ApprovalService
from app.agent.orchestrator import AgentOrchestrator
from app.agent.patches import PatchEngine
from app.agent.schemas import AgentPlan, ToolRequest
from app.core.exceptions import SafeError
from app.core.limits import Limits
from app.db.base import now
from app.db.models.agent import AgentStep, FileSnapshot, ToolCall
from app.sandbox.runner import CommandResult, DockerSandboxRunner, OutputBuffer
from app.services.agent_service import AgentService
from app.services.user_service import ensure_user
from app.services.workspace_service import WorkspaceService
from app.tools.registry import ApprovalPending, ToolRegistry


class Models:
    async def active(self):
        return SimpleNamespace(metadata_json={}, capabilities_json={})


class Planner:
    def __init__(self, *plans):
        self.plans = list(plans)
        self.calls = 0

    async def plan(self, job, registry, observations=None):
        self.calls += 1
        value = self.plans.pop(0)
        if isinstance(value, Exception):
            raise value
        return AgentPlan.model_validate(value)


def plan(*steps, complete=True):
    return {
        "goal": "Make requested change",
        "steps": [{"tool_name": tool, "arguments": args} for tool, args in steps],
        "complete": complete,
    }


async def setup(stack, tmp_path, mode="WORKSPACE", **settings):
    cfg = config(
        tmp_path,
        max_models=1000,
        max_agent_steps=12,
        max_tool_calls=20,
        max_replans=2,
        max_repair_attempts=1,
        max_task_duration=10,
        max_command_output_bytes=1024,
        command_timeout=1,
        sandbox_backend="disabled",
        sandbox_image="wakeelm-validation:local",
        require_edit_approval=False,
        max_patch_files=10,
        approval_ttl_seconds=60,
        **settings,
    )
    w = WorkspaceService(stack.session, stack.user.id, cfg, stack.secrets, Limits(stack.redis))
    workspace = await w.ingest(
        "project.zip",
        project_zip(
            {
                "main.py": "VALUE = 1\n",
                "test_main.py": "from main import VALUE\ndef test_value():\n    assert VALUE == 2\n",
            }
        ),
    )
    agents = AgentService(w, Models())
    job = await agents.create(workspace.id, mode, "Change VALUE to 2", 123)
    await stack.session.commit()
    return w, agents, job


async def edits(w, job, **values):
    content = await w.read(job.workspace_id, "main.py")
    return {
        "edits": [
            dict(
                path="main.py",
                kind="exact",
                expected_sha256=hashlib.sha256(content).hexdigest(),
                old_text="VALUE = 1",
                new_text="VALUE = 2",
                **values,
            )
        ]
    }


async def never():
    return False


async def test_patch_diff_apply_snapshot_rollback(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path)
    engine = PatchEngine(w, job)
    proposal = await engine.propose(await edits(w, job))
    ident = proposal["change_set_id"]
    assert "+VALUE = 2" in (await engine.diff(ident))["diff"]
    await engine.apply(ident)
    assert await w.read(job.workspace_id, "main.py") == b"VALUE = 2\n"
    snapshot = await stack.session.scalar(select(FileSnapshot))
    assert "VALUE" not in snapshot.content_encrypted
    assert await engine.rollback(ident) == {"change_set_id": ident, "restored": 1}
    assert await w.read(job.workspace_id, "main.py") == b"VALUE = 1\n"


@pytest.mark.parametrize(
    "mode,tool",
    [
        ("READ_ONLY", "workspace.propose_patch"),
        ("READ_ONLY", "workspace.apply_patch"),
        ("SUGGEST", "workspace.apply_patch"),
        ("READ_ONLY", "validation.run"),
        ("SUGGEST", "workspace.restore_file"),
    ],
)
async def test_mode_denials(stack, tmp_path, mode, tool):
    w, _, job = await setup(stack, tmp_path, mode)
    registry = ToolRegistry(w, job, never)
    with pytest.raises(SafeError, match="POLICY_DENIED"):
        await registry.execute(ToolRequest(tool_name=tool, arguments={}))
    assert job.tool_calls_count == 0


@pytest.mark.parametrize(
    "tool,args",
    [
        ("shell.run", {"command": "curl evil"}),
        ("workspace.read_file", {"path": "/etc/passwd"}),
        ("workspace.read_file", {"path": "../main.py"}),
        ("validation.run", {"command_id": "python_tests;rm -rf /"}),
        ("validation.run", {"command_id": "python_tests", "command": "echo secret"}),
        ("workspace.list_files", {"unexpected": 1}),
    ],
)
async def test_unknown_tools_paths_commands_rejected(stack, tmp_path, tool, args):
    w, _, job = await setup(stack, tmp_path)
    with pytest.raises(SafeError):
        await ToolRegistry(w, job, never).execute(ToolRequest(tool_name=tool, arguments=args))
    assert job.tool_calls_count == 0


async def test_stale_patch_cannot_overwrite(stack, tmp_path):
    w, _, job = await setup(stack, tmp_path)
    engine = PatchEngine(w, job)
    proposal = await engine.propose(await edits(w, job))
    w.storage.write_file(w.user_id, job.workspace_id, "main.py", b"VALUE = 9\n")
    with pytest.raises(SafeError, match="STALE_FILE"):
        await engine.apply(proposal["change_set_id"])
    assert await w.read(job.workspace_id, "main.py") == b"VALUE = 9\n"


async def test_new_file_symlink_parent_and_rollback(stack, tmp_path):
    w, _, job = await setup(stack, tmp_path)
    root = w.storage.root_for(w.user_id, job.workspace_id)
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    engine = PatchEngine(w, job)
    with pytest.raises(SafeError, match="PATH_DENIED"):
        await engine.propose(
            {"edits": [{"path": "escape/new.py", "kind": "new", "new_text": "PASS = True\n"}]}
        )
    (root / "escape").unlink()
    proposal = await engine.propose(
        {"edits": [{"path": "nested/new.py", "kind": "new", "new_text": "PASS = True\n"}]}
    )
    await engine.apply(proposal["change_set_id"])
    await engine.rollback(proposal["change_set_id"])
    assert not (root / "nested/new.py").exists()


async def test_batch_failure_compensates_and_reindexes(stack, tmp_path, monkeypatch):
    w, _, job = await setup(stack, tmp_path)
    engine = PatchEngine(w, job)
    data = await edits(w, job)
    data["edits"].append({"path": "new.py", "kind": "new", "new_text": "OK = True\n"})
    proposal = await engine.propose(data)
    original = w.storage.write_file

    def fail(user, workspace, path, data):
        if path == "new.py":
            raise OSError("simulated disk failure")
        original(user, workspace, path, data)

    monkeypatch.setattr(w.storage, "write_file", fail)
    with pytest.raises(OSError):
        await engine.apply(proposal["change_set_id"])
    assert await w.read(job.workspace_id, "main.py") == b"VALUE = 1\n"
    assert (await engine.proposal(proposal["change_set_id"])).status == "ROLLED_BACK"
    assert (await w.files(job.workspace_id))[0].sha256 == hashlib.sha256(b"VALUE = 1\n").hexdigest()


async def test_approval_ownership_binding_expiry_replay(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path)
    registry = ToolRegistry(w, job, never)
    request = ToolRequest(tool_name="validation.run", arguments={"command_id": "python_tests"})
    with pytest.raises(ApprovalPending):
        await registry.execute(request)
    approval = (await agents.pending(job.id))[0]
    other = await ensure_user(
        stack.session, SimpleNamespace(id=456, username="other", first_name="Other", last_name=None)
    )
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await ApprovalService(stack.session, other.id, w.settings).decide(approval.id, True)
    await agents.approvals.decide(approval.id, True)
    assert await agents.approvals.approved(job, "validation.run", {"command_id": "python_tests"})
    assert not await agents.approvals.approved(job, "validation.run", {"command_id": "python_lint"})
    job.current_step += 1
    assert not await agents.approvals.approved(
        job, "validation.run", {"command_id": "python_tests"}
    )
    with pytest.raises(SafeError, match="STALE_APPROVAL"):
        await agents.approvals.decide(approval.id, True)
    job.current_step = 0
    approval.status = "PENDING"
    job.status = "WAITING_APPROVAL"
    approval.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(SafeError, match="EXPIRED_APPROVAL"):
        await agents.approvals.decide(approval.id, True)
    assert job.status == "FAILED"


async def test_high_risk_delete_requires_approval(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path)
    original = await w.read(job.workspace_id, "main.py")
    proposal = await PatchEngine(w, job).propose(
        {
            "edits": [
                {
                    "path": "main.py",
                    "kind": "delete",
                    "expected_sha256": hashlib.sha256(original).hexdigest(),
                }
            ]
        }
    )
    req = ToolRequest(
        tool_name="workspace.apply_patch", arguments={"change_set_id": proposal["change_set_id"]}
    )
    registry = ToolRegistry(w, job, never)
    with pytest.raises(ApprovalPending):
        await registry.execute(req)
    assert await w.read(job.workspace_id, "main.py") == original
    await agents.approvals.decide((await agents.pending(job.id))[0].id, True)
    await registry.execute(req)
    assert not (w.storage.root_for(w.user_id, job.workspace_id) / "main.py").exists()


async def test_orchestrator_persists_and_resumes_exact_step(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path)
    data = await edits(w, job)
    planner = Planner(
        plan(
            ("workspace.read_file", {"path": "main.py"}),
            ("workspace.propose_patch", data),
            ("workspace.apply_patch", {"change_set_id": "$last_patch"}),
            ("validation.run", {"command_id": "python_tests"}),
        )
    )

    class Runner:
        async def run(self, *args):
            return CommandResult(0, 12, "1 passed", False, "COMPLETED")

    runtime = AgentOrchestrator(w, Models(), planner, Runner())
    await runtime.run(job.id)
    assert job.status == "WAITING_APPROVAL" and job.current_step == 3 and job.tool_calls_count == 3
    await agents.approvals.decide((await agents.pending(job.id))[0].id, True)
    await runtime.run(job.id)
    assert job.status == "COMPLETED" and job.current_step == 4 and planner.calls == 1
    assert job.result_json["verification"]["passed"]
    assert len(list(await stack.session.scalars(select(ToolCall)))) == 4
    assert len(list(await stack.session.scalars(select(AgentStep)))) == 4
    assert "VALUE" not in json.dumps(job.plan_json)


async def test_cancel_busy_delete_and_no_execution(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path)
    with pytest.raises(SafeError, match="WORKSPACE_BUSY"):
        await w.delete(job.workspace_id)
    await agents.cancel(job.id)
    with pytest.raises(SafeError, match="JOB_CANCELLED"):
        await ToolRegistry(w, job, never).patches.propose(await edits(w, job))
    planner = Planner(plan(("workspace.list_files", {})))
    await AgentOrchestrator(w, Models(), planner).run(job.id)
    assert planner.calls == 0 and job.status == "CANCELLED"


async def test_limits_and_invalid_plan_bounded(stack, tmp_path):
    w, _, job = await setup(stack, tmp_path)
    planner = Planner(
        SafeError("INVALID_PLAN"), SafeError("INVALID_PLAN"), SafeError("INVALID_PLAN")
    )
    await AgentOrchestrator(w, Models(), planner).run(job.id)
    assert job.status == "FAILED" and job.replan_count == 2 and planner.calls == 3


async def test_suggest_explicit_apply_and_user_rollback(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path, "SUGGEST")
    await AgentOrchestrator(
        w, Models(), Planner(plan(("workspace.propose_patch", await edits(w, job))))
    ).run(job.id)
    assert job.status == "COMPLETED" and await w.read(job.workspace_id, "main.py") == b"VALUE = 1\n"
    ident = job.result_json["last_patch"]
    await agents.accept_change(ident)
    await AgentOrchestrator(w, Models(), Planner()).run(job.id)
    assert job.status == "COMPLETED" and await w.read(job.workspace_id, "main.py") == b"VALUE = 2\n"
    await agents.restore(ident)
    assert await w.read(job.workspace_id, "main.py") == b"VALUE = 1\n"


async def test_validation_failure_one_repair_then_stop(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path)
    planner = Planner(
        plan(("validation.run", {"command_id": "python_tests"})),
        plan(("validation.run", {"command_id": "python_tests"})),
    )

    class Runner:
        async def run(self, *args):
            return CommandResult(1, 12, "assert failed", False, "COMPLETED")

    runtime = AgentOrchestrator(w, Models(), planner, Runner())
    for _ in range(3):
        await runtime.run(job.id)
        if job.status != "WAITING_APPROVAL":
            break
        await agents.approvals.decide((await agents.pending(job.id))[0].id, True)
    assert (
        job.status == "FAILED"
        and job.failure_code == "VALIDATION_FAILED"
        and job.repair_count == 1
        and planner.calls == 2
    )


@pytest.mark.parametrize("data", [b"abc", b"a" * 100, b"a" * 600, b"a" * 2000])
def test_output_first_last_bound(data):
    buffer = OutputBuffer(1024)
    for index in range(0, len(data), 17):
        buffer.append(data[index : index + 17])
    output, truncated = buffer.render()
    assert truncated == (len(data) > 1024)
    assert len(output.encode()) <= 1037
    if not truncated:
        assert output.encode() == data


def test_sandbox_fixed_argv_and_no_host_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret")
    monkeypatch.setenv("HTTP_PROXY", "http://secret-proxy")
    runner = DockerSandboxRunner(SimpleNamespace(sandbox_image="test:local"))
    args = runner.docker_argv("wakeelm-test", "/tmp/copy", ["python", "-m", "pytest"])
    assert "--network=none" in args and "--read-only" in args and "--cap-drop=ALL" in args
    assert all("secret" not in value for value in args)
    assert runner.environment() == {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}


async def test_planner_native_and_strict_json_fallback(stack, tmp_path):
    from app.agent.planner import AgentPlanner

    w, _, job = await setup(stack, tmp_path)

    class ModelGateway(Models):
        def __init__(self, native):
            self.native = native
            self.tools = None

        async def active(self):
            return SimpleNamespace(
                metadata_json={"context_length": 16000},
                capabilities_json={
                    "tool_calling": {"state": "SUPPORTED" if self.native else "UNKNOWN"}
                },
            )

        async def agent_completion(self, model, messages, tools=None):
            self.tools = tools
            assert messages[0]["role"] == "system"
            return json.dumps(
                plan(
                    ("workspace.propose_patch", await edits(w, job)),
                    ("workspace.apply_patch", {"change_set_id": "$last_patch"}),
                )
            ), {"prompt_tokens": 10, "completion_tokens": 20}

    registry = ToolRegistry(w, job, never)
    for native in (True, False):
        models = ModelGateway(native)
        result = await AgentPlanner(models, w).plan(job, registry)
        assert len(result.steps) == 2 and bool(models.tools) == native
    assert job.input_tokens == 20 and job.output_tokens == 40


async def test_native_tool_response_normalization():
    from app.providers.adapters.openai import OpenAICompatibleAdapter

    class HTTP:
        async def request(self, *args):
            assert args[3]["tools"] and not args[3]["parallel_tool_calls"]
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "workspace__read_file",
                                        "arguments": '{"path":"main.py"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            }

    adapter = OpenAICompatibleAdapter("https://api.example.com/v1", "token", {}, HTTP())
    content, _ = await adapter.create_agent_completion(
        "model", [{"role": "user", "content": "task"}], [{"type": "function"}]
    )
    result = AgentPlan.model_validate_json(content)
    assert result.steps[0].tool_name == "workspace.read_file" and not result.complete


async def test_replanning_observes_reads_and_limits_tools(stack, tmp_path):
    w, _, job = await setup(stack, tmp_path)

    class Followup(Planner):
        async def plan(self, job, registry, observations=None):
            if self.calls:
                assert "VALUE = 1" in observations[0]["result"]
            return await super().plan(job, registry, observations)

    planner = Followup(
        plan(("workspace.read_file", {"path": "main.py"}), complete=False),
        plan(("workspace.file_info", {"path": "main.py"})),
    )
    await AgentOrchestrator(w, Models(), planner).run(job.id)
    assert job.status == "COMPLETED" and job.replan_count == 1 and planner.calls == 2
    job.status = "RUNNING"
    job.tool_calls_count = w.settings.max_tool_calls
    with pytest.raises(SafeError, match="AGENT_LIMIT"):
        await ToolRegistry(w, job, never).execute(ToolRequest(tool_name="workspace.list_files"))


async def test_cross_user_job_changes_approvals_denied(stack, tmp_path):
    w, _, job = await setup(stack, tmp_path)
    ident = (await PatchEngine(w, job).propose(await edits(w, job)))["change_set_id"]
    other = await ensure_user(
        stack.session, SimpleNamespace(id=456, username="other", first_name="Other", last_name=None)
    )
    alien = AgentService(
        WorkspaceService(stack.session, other.id, w.settings, stack.secrets, w.limits), Models()
    )
    for operation in (
        alien.owned.job(job.id),
        alien.owned.change_set(ident),
        alien.cancel(job.id),
        alien.changes(job.workspace_id),
    ):
        with pytest.raises(SafeError, match="NOT_FOUND"):
            await operation


@pytest.mark.parametrize(
    "kind,options",
    [
        ("lines", {"start_line": 1, "end_line": 1, "new_text": "VALUE = 2\n"}),
        (
            "unified",
            {"new_text": "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n"},
        ),
        (
            "full",
            {"new_text": "VALUE = 2\n", "justification": "Small single-line module replacement"},
        ),
    ],
)
async def test_controlled_patch_variants(stack, tmp_path, kind, options):
    w, _, job = await setup(stack, tmp_path)
    raw = await w.read(job.workspace_id, "main.py")
    engine = PatchEngine(w, job)
    value = await engine.propose(
        {
            "edits": [
                {
                    "path": "main.py",
                    "expected_sha256": hashlib.sha256(raw).hexdigest(),
                    "kind": kind,
                    **options,
                }
            ]
        }
    )
    await engine.apply(value["change_set_id"])
    assert await w.read(job.workspace_id, "main.py") == b"VALUE = 2\n"


async def test_approval_rejection_prevents_execution(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path)
    registry = ToolRegistry(w, job, never)
    with pytest.raises(ApprovalPending):
        await registry.execute(
            ToolRequest(tool_name="validation.run", arguments={"command_id": "python_tests"})
        )
    await agents.approvals.decide((await agents.pending(job.id))[0].id, False)
    await AgentOrchestrator(w, Models(), Planner()).run(job.id)
    assert job.status == "FAILED" and job.tool_calls_count == 0


@pytest.mark.parametrize("interrupted_status", ["RUNNING", "FAILED"])
async def test_worker_recovers_partial_batch(stack, tmp_path, interrupted_status):
    from app.agent.worker import AgentWorker
    from app.db.models.agent import WorkspaceChangeSet

    w, _, job = await setup(stack, tmp_path)
    proposal = await PatchEngine(w, job).propose(await edits(w, job))
    value = await stack.session.get(WorkspaceChangeSet, proposal["change_set_id"])
    stack.session.add(
        FileSnapshot(
            change_set_id=value.id,
            relative_path="main.py",
            original_sha256=hashlib.sha256(b"VALUE = 1\n").hexdigest(),
            resulting_sha256=hashlib.sha256(b"VALUE = 2\n").hexdigest(),
            content_encrypted=stack.secrets.encrypt("VALUE = 1\n"),
            existed=True,
        )
    )
    value.status = "APPLYING"
    job.status = interrupted_status
    w.storage.write_file(w.user_id, job.workspace_id, "main.py", b"VALUE = 2\n")
    await stack.session.commit()
    worker = AgentWorker(stack.sessions, stack.secrets, stack.http, w.limits, w.settings)
    await worker.recover()
    await stack.session.refresh(job)
    await stack.session.refresh(value)
    assert (
        job.status == "FAILED"
        and job.failure_code == "WORKER_INTERRUPTED"
        and value.status == "ROLLED_BACK"
    )
    assert await w.read(job.workspace_id, "main.py") == b"VALUE = 1\n"


async def test_explicit_approval_wrapper_bound_action(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path)
    registry = ToolRegistry(w, job, never)
    req = ToolRequest(
        tool_name="agent.request_approval",
        arguments={"tool_name": "workspace.read_file", "arguments": {"path": "main.py"}},
    )
    with pytest.raises(ApprovalPending):
        await registry.execute(req)
    await agents.approvals.decide((await agents.pending(job.id))[0].id, True)
    assert (await registry.execute(req))["text"] == "VALUE = 1"
    invalid = ToolRequest(
        tool_name="agent.request_approval",
        arguments={"tool_name": "shell.run", "arguments": {"command": "whoami"}},
    )
    with pytest.raises(SafeError, match="POLICY_DENIED"):
        await registry.execute(invalid)


async def test_model_output_bound_preserves_validation_status(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path)

    class Runner:
        async def run(self, *args):
            return CommandResult(1, 1, "x" * 50000, True, "COMPLETED")

    registry = ToolRegistry(w, job, never, Runner())
    req = ToolRequest(tool_name="validation.run", arguments={"command_id": "python_tests"})
    with pytest.raises(ApprovalPending):
        await registry.execute(req)
    await agents.approvals.decide((await agents.pending(job.id))[0].id, True)
    result = await registry.execute(req)
    assert (
        result["status"] == "FAILED"
        and result["truncated"]
        and len(result["preview"].encode()) <= 24000
    )


async def test_cancel_running_keeps_workspace_busy_until_ack(stack, tmp_path):
    w, agents, job = await setup(stack, tmp_path)
    job.status = "RUNNING"
    await stack.session.commit()
    await agents.cancel(job.id)
    assert job.status == "CANCEL_REQUESTED"
    with pytest.raises(SafeError, match="WORKSPACE_BUSY"):
        await w.delete(job.workspace_id)
    await AgentOrchestrator(w, Models(), Planner(plan(("workspace.list_files", {})))).run(job.id)
    assert job.status == "CANCELLED" and job.tool_calls_count == 0
