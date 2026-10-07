import pytest
from sqlalchemy import select

from app.agent.schemas import ToolRequest
from app.agent.specialists import role_allows
from app.context.compressor import ContextCompressor
from app.core.exceptions import SafeError
from app.db.models.platform import MemoryItem
from app.memory.service import MemoryCandidate, MemoryService


async def test_memory_tenant_scope_secret_provenance_dedup(stack, tmp_path):
    from test_workspaces import service

    w = service(stack, tmp_path)
    workspace = await w.ingest("main.py", b"print('hello')")
    memories = MemoryService(stack.session, stack.user.id, stack.secrets)
    candidate = MemoryCandidate(
        layer="PROJECT",
        content="Project uses pytest for tests",
        workspace_id=workspace.id,
        source_type="PROJECT_FILE",
        source_id="README.md",
        confidence=0.9,
    )
    item = await memories.write(candidate)
    assert (await memories.write(candidate)).id == item.id
    assert "pytest" not in item.content_encrypted and item.search_terms == []
    result = await memories.retrieve("pytest", workspace_id=workspace.id)
    assert result[0]["provenance"]["source_id"] == "README.md"
    assert await memories.retrieve("pytest") == []
    other = MemoryService(stack.session, 999, stack.secrets)
    with pytest.raises(SafeError, match="NOT_FOUND"):
        await other.retrieve("pytest", workspace_id=workspace.id)
    assert await other.retrieve("pytest") == []
    for text in ["password=supersecret", "sk-abcdefghijklmnopqrstuv"]:
        with pytest.raises(SafeError, match="MEMORY_SECRET_DENIED"):
            await memories.write(candidate.model_copy(update={"content": text}))
    with pytest.raises(SafeError, match="POLICY_DENIED"):
        await memories.write(candidate.model_copy(update={"source_type": "MODEL_INFERENCE"}))


async def test_progressive_history_bounded(stack):
    service = MemoryService(stack.session, stack.user.id, stack.secrets)
    for index in range(30):
        await service.conversation(f"decision number {index}", str(index))
    rows = list(await stack.session.scalars(select(MemoryItem)))
    assert len(rows) <= 12
    assert any("EXTRACTIVE_HISTORY" in stack.secrets.decrypt(row.content_encrypted) for row in rows)


@pytest.mark.parametrize(
    "role",
    [
        "CodeAnalysisAgent",
        "ReviewAgent",
        "SecurityReviewAgent",
        "CoordinatorAgent",
        "ResearchAgent",
    ],
)
def test_role_rejects_remote_writes_and_patches(role):
    for name in [
        "git.push_branch",
        "github.create_pull_request",
        "workspace.apply_patch",
        "validation.run",
    ]:
        with pytest.raises(SafeError, match="POLICY_DENIED"):
            role_allows(role, ToolRequest(tool_name=name))


def test_docs_and_test_role_boundaries_and_compression():
    role_allows(
        "DocumentationAgent",
        ToolRequest(
            tool_name="workspace.propose_patch", arguments={"edits": [{"path": "docs/a.md"}]}
        ),
    )
    with pytest.raises(SafeError):
        role_allows(
            "DocumentationAgent",
            ToolRequest(
                tool_name="workspace.propose_patch", arguments={"edits": [{"path": "app/auth.py"}]}
            ),
        )
    role_allows("TestAgent", ToolRequest(tool_name="validation.run"))
    items = [{"path": "a.py", "text": "print(1)", "provenance": {"source": "a.py"}}] * 2
    compressed = ContextCompressor().compress(items, 100)
    assert len(compressed) == 1 and compressed[0]["provenance"] == items[0]["provenance"]
    with pytest.raises(SafeError):
        ContextCompressor().compress([{"text": "x" * 10000}], 10, exact_edit=True)


async def test_specialist_real_tool_evidence_persisted_dag_and_no_replay(stack, tmp_path):
    import json

    from test_agent import never, setup
    from test_routing import candidates

    from app.agent.specialists import CoordinatorAgent
    from app.db.models.platform import AgentGraphNode
    from app.tools.registry import ToolRegistry

    rows = await candidates(stack)
    w, _, job = await setup(stack, tmp_path)
    registry = ToolRegistry(w, job, never)
    result = {"status": "COMPLETED", "summary": "Observed project files", "confidence": 0.9}

    class Models:
        calls = 0

        async def route(self, text):
            return rows[0]

        async def agent_completion(self, model, messages):
            self.calls += 1
            if self.calls == 1:
                return json.dumps(
                    {"result": result, "tool_requests": [{"tool_name": "workspace.list_files"}]}
                ), {}
            assert "main.py" in messages[1]["content"]
            return json.dumps(result), {}

    models = Models()
    coordinator = CoordinatorAgent(w, models, job, registry)
    output = await coordinator.run_role("CodeAnalysisAgent")
    assert output.tool_calls_used == 1 and output.model_used == rows[0].id
    assert models.calls == 2
    assert (await coordinator.run_role("CodeAnalysisAgent")).summary == output.summary
    assert models.calls == 2
    with pytest.raises(SafeError, match="AGENT_GRAPH_INVALID"):
        await coordinator.run_role("ReviewAgent", dependencies=["missing-node"])
    graph = list(await stack.session.scalars(select(AgentGraphNode)))
    assert len(graph) == 1 and graph[0].status == "COMPLETED"
    assert "main.py" not in graph[0].result_encrypted


async def test_real_multi_agent_orchestrator_uses_bounded_graph_and_approved_executor(
    stack, tmp_path
):
    import json

    from test_agent import setup
    from test_routing import candidates

    from app.agent.orchestrator import AgentOrchestrator
    from app.db.models.platform import AgentGraphNode
    from app.routing.preferences import RoutingPreferences
    from app.services.model_service import ModelService

    rows = await candidates(stack)
    models = ModelService(stack.service)
    await models.activate(rows[0].id)
    await RoutingPreferences(stack.session, stack.user.id).set(agent_mode="MULTI_AGENT")
    w, _, job = await setup(stack, tmp_path)
    result = {"status": "COMPLETED", "summary": "Bounded evidence review", "confidence": 0.8}
    responses = [
        {"result": result, "tool_requests": []},
        {
            "goal": "Read exact project evidence",
            "steps": [{"tool_name": "workspace.read_file", "arguments": {"path": "main.py"}}],
            "answer": "Observed VALUE = 1",
            "complete": True,
        },
        {"result": result, "tool_requests": []},
        {"result": result, "tool_requests": []},
    ]

    async def request(method, url, headers, payload=None):
        assert responses
        return {
            "choices": [{"message": {"content": json.dumps(responses.pop(0))}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

    stack.http.request = request
    completed = await AgentOrchestrator(w, models).run(job.id)
    assert completed.status == "COMPLETED" and completed.model_requests == 4
    assert completed.tool_calls_count == 1 and not responses
    nodes = list(await stack.session.scalars(select(AgentGraphNode)))
    assert len(nodes) == 4 and all(node.status == "COMPLETED" for node in nodes)
    assert {node.role for node in nodes} == {
        "CodeAnalysisAgent",
        "ImplementationAgent",
        "TestAgent",
        "ReviewAgent",
    }


async def test_high_risk_plan_triggers_security_gate_before_any_tool(stack, tmp_path):
    import json

    from test_agent import setup
    from test_routing import candidates

    from app.agent.orchestrator import AgentOrchestrator
    from app.services.model_service import ModelService

    rows = await candidates(stack)
    models = ModelService(stack.service)
    await models.activate(rows[0].id)
    w, _, job = await setup(stack, tmp_path)
    responses = [
        {
            "goal": "Review authentication change",
            "steps": [],
            "risk": "HIGH",
            "answer": "Pending security review",
        },
        {
            "result": {
                "status": "NEEDS_REVIEW",
                "summary": "Unverified authorization change",
                "risks": ["Authorization needs evidence"],
                "confidence": 0.8,
            },
            "tool_requests": [],
        },
    ]

    async def request(method, url, headers, payload=None):
        return {
            "choices": [{"message": {"content": json.dumps(responses.pop(0))}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

    stack.http.request = request
    completed = await AgentOrchestrator(w, models).run(job.id)
    assert completed.failure_code == "SECURITY_REVIEW_REQUIRED"
    assert completed.tool_calls_count == 0 and completed.model_requests == 2
    assert not responses
