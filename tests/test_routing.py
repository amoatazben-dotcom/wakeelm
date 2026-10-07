from decimal import Decimal

import pytest
from sqlalchemy import select
from test_services import create

from app.core.exceptions import SafeError
from app.db.models import Model, ModelHealthCheck
from app.routing.budget import CostEstimator, ExecutionBudget
from app.routing.classifier import TaskClassifier
from app.routing.preferences import RoutingPreferences
from app.routing.router import ModelRouter
from app.routing.schemas import RoutingPolicy, RoutingRequest, TaskType
from app.services.model_service import ModelService


async def candidates(stack):
    provider = await create(stack)
    stack.http.data = {"data": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
    await stack.service.discover(provider.id)
    await stack.session.flush()
    rows = list(await stack.session.scalars(select(Model).order_by(Model.id)))
    rows[0].pricing_json = {"classification": "PAID", "prompt": "0.00001", "completion": "0.00002"}
    rows[1].pricing_json = {"classification": "FREE_REPORTED"}
    rows[2].capabilities_json = {"coding": {"state": "SUPPORTED", "source": "TESTED"}}
    rows[2].metadata_json = {"context_length": 100000}
    for row, latency in zip(rows, [50, 1000, 500]):
        stack.session.add(ModelHealthCheck(model_id=row.id, status="AVAILABLE", latency_ms=latency))
    await stack.session.flush()
    return rows


@pytest.mark.parametrize(
    "policy,index",
    [
        ("PREFER_FREE", 1),
        ("PREFER_CHEAP", 1),
        ("PREFER_FAST", 0),
        ("PREFER_CODING", 2),
        ("PREFER_LONG_CONTEXT", 2),
        ("PREFER_STRONGEST", 2),
    ],
)
async def test_routing_policies(stack, policy, index):
    rows = await candidates(stack)
    request = RoutingRequest(policy=policy)
    router = ModelRouter(stack.session, stack.user.id)
    result = await router.route(request)
    assert result.model_id == rows[index].id
    assert result == await router.route(request)
    assert len(result.fallback_chain) <= 2
    with pytest.raises(SafeError):
        await ModelRouter(stack.session, 999).route(request)


async def test_evidence_context_and_manual(stack):
    rows = await candidates(stack)
    rows[0].display_name = "super-coding-tool-vision"
    rows[0].capabilities_json = {"coding": {"state": "SUPPORTED", "source": "INFERRED"}}
    router = ModelRouter(stack.session, stack.user.id)
    assert (await router.route(RoutingRequest(required_capabilities={"coding"}))).model_id == rows[
        2
    ].id
    with pytest.raises(SafeError, match="CAPABILITY_MISMATCH"):
        await router.route(RoutingRequest(required_capabilities={"vision"}))
    assert (await router.route(RoutingRequest(context_size=40000))).model_id == rows[2].id
    with pytest.raises(SafeError):
        await router.route(RoutingRequest(context_size=100000))
    result = await router.route(
        RoutingRequest(policy=RoutingPolicy.MANUAL_ONLY, manual_model_id=rows[1].id)
    )
    assert result.model_id == rows[1].id and result.fallback_chain == []
    assert (await router.route(RoutingRequest(task_type=TaskType.CODE_EDIT))).model_id == rows[2].id


@pytest.mark.parametrize(
    "code", ["TIMEOUT", "RATE_LIMITED", "CONTEXT_TOO_LARGE", "INVALID_RESPONSE"]
)
async def test_bounded_real_gateway_fallback(stack, code):
    rows = await candidates(stack)
    models = ModelService(stack.service)
    await RoutingPreferences(stack.session, stack.user.id).set(policy="AUTO", fallback_enabled=True)
    chosen = await models.route("hello")
    calls = []

    async def invoke(model):
        calls.append(model.id)
        if model.id == chosen.id:
            raise SafeError(code)
        return "fallback OK", {"prompt_tokens": 2, "completion_tokens": 3}

    assert (await models.routing.execute(chosen, invoke))[0] == "fallback OK"
    assert len(calls) == 2
    assert models.routing.fallbacks[-1]["reason"] == code
    assert all(ident in {r.id for r in rows} for ident in calls)


async def test_no_fallback_on_safety_and_manual(stack):
    rows = await candidates(stack)
    models = ModelService(stack.service)
    await models.activate(rows[0].id)
    chosen = await models.route("hello")
    calls = []

    async def reject(model):
        calls.append(model.id)
        raise SafeError("SAFETY_REJECTION")

    with pytest.raises(SafeError, match="SAFETY_REJECTION"):
        await models.routing.execute(chosen, reject)
    assert calls == [chosen.id]


def test_classifier_and_budget():
    assert TaskClassifier().classify("إصلاح خطأ").task_type == TaskType.DEBUGGING
    assert TaskClassifier().classify("read", 64000).task_type == TaskType.LONG_CONTEXT_REVIEW
    assert CostEstimator.estimate({"classification": "UNKNOWN"}, 10, 20) is None
    budget = ExecutionBudget(max_model_calls=1)
    budget.reserve()
    with pytest.raises(SafeError, match="AGENT_LIMIT"):
        budget.reserve()
    with pytest.raises(SafeError):
        ExecutionBudget(max_estimated_cost=Decimal("0.01")).reserve(cost=Decimal("1"))
    with pytest.raises(SafeError):
        ExecutionBudget(max_total_tokens=10).account(11)
