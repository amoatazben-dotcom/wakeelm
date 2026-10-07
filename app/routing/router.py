import math

from sqlalchemy import func, select

from app.core.exceptions import SafeError
from app.db.models import Model, ModelHealthCheck, Provider
from app.routing.schemas import RoutingDecision, RoutingPolicy, TaskType

EVIDENCE = {
    "TESTED": "VERIFIED",
    "VERIFIED": "VERIFIED",
    "PROVIDER_METADATA": "PROVIDER_REPORTED",
    "PROVIDER_REPORTED": "PROVIDER_REPORTED",
    "INFERRED": "INFERRED",
}


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else default
    except (TypeError, ValueError):
        return default


def capability(model, name):
    value = (model.capabilities_json or {}).get(name, {})
    from app.db.base import now

    if value.get("probe_expires_at") and value["probe_expires_at"] <= now().isoformat():
        return False
    return value.get("state") == "SUPPORTED" and EVIDENCE.get(value.get("source")) in {
        "VERIFIED",
        "PROVIDER_REPORTED",
    }


class ModelRouter:
    def __init__(self, session, user_id, max_fallbacks=2):
        self.session, self.user_id = session, user_id
        self.max_fallbacks = min(5, max(0, max_fallbacks))

    async def route(self, request):
        rows = list(
            await self.session.execute(
                select(Model, Provider)
                .join(Provider)
                .where(
                    Provider.user_id == self.user_id,
                    Provider.status != "DISABLED",
                    Model.status != "UNSUPPORTED",
                )
                .order_by(Model.id)
                .limit(1000)
            )
        )
        health_rank = (
            select(
                ModelHealthCheck.id,
                func.row_number()
                .over(partition_by=ModelHealthCheck.model_id, order_by=ModelHealthCheck.id.desc())
                .label("position"),
            )
            .where(ModelHealthCheck.model_id.in_([model.id for model, _ in rows]))
            .subquery()
        )
        health = list(
            await self.session.scalars(
                select(ModelHealthCheck)
                .join(health_rank, ModelHealthCheck.id == health_rank.c.id)
                .where(health_rank.c.position <= 20)
            )
        )
        histories = {}
        for check in health:
            histories.setdefault(check.model_id, []).append(check)
        ranked = []
        for model, provider in rows:
            if provider.id in request.excluded_providers:
                continue
            if request.policy == RoutingPolicy.MANUAL_ONLY and model.id != request.manual_model_id:
                continue
            if any(not capability(model, cap) for cap in request.required_capabilities):
                continue
            window = number((model.metadata_json or {}).get("context_length"))
            if request.context_size and (not window or request.context_size > window * 0.8):
                continue
            history = histories.get(model.id, [])
            failure_rate = sum(h.error_code is not None for h in history) / max(1, len(history))
            latency = (
                sum(h.latency_ms for h in history) / max(1, len(history)) if history else 30000
            )
            healthy = provider.status not in {"AUTH_FAILED", "OFFLINE"}
            price = model.pricing_json or {}
            free = price.get("classification") in {"FREE_VERIFIED", "FREE_REPORTED"}
            known_price = free or ("prompt" in price and "completion" in price)
            cost = number(price.get("prompt"), 1) + number(price.get("completion"), 1)
            cheap = 1 if free else (1 / (1 + cost * 1000000) if known_price else 0)
            fast = 1 / (1 + latency / 1000)
            strong = (
                sum(capability(model, c) for c in ["reasoning", "coding", "structured_output"]) / 3
            )
            score = 3 * healthy + 2 * (1 - failure_rate) + float(model.is_available)
            score += fast * request.latency_preference + cheap * request.cost_preference
            policy = request.policy
            if policy == RoutingPolicy.PREFER_FREE:
                score += 20 * free
            elif policy == RoutingPolicy.PREFER_CHEAP:
                score += 10 * cheap
            elif policy == RoutingPolicy.PREFER_FAST:
                score += 10 * fast
            elif policy == RoutingPolicy.PREFER_STRONGEST:
                score += 10 * strong
            elif policy == RoutingPolicy.PREFER_LONG_CONTEXT:
                score += 10 * min(1, window / 200000)
            if policy == RoutingPolicy.PREFER_CODING or request.task_type in {
                TaskType.CODE_EDIT,
                TaskType.CODE_QA,
                TaskType.DEBUGGING,
                TaskType.REFACTOR,
                TaskType.TESTING,
                TaskType.REPOSITORY_TASK,
                TaskType.GITHUB_ACTION,
            }:
                score += 10 * capability(model, "coding")
            if policy == RoutingPolicy.AUTO:
                score += request.task_complexity * strong
            ranked.append((score, model))
        if not ranked:
            raise SafeError("NO_ACTIVE_MODEL" if not rows else "CAPABILITY_MISMATCH")
        ranked.sort(key=lambda pair: (-pair[0], pair[1].id))
        model = ranked[0][1]
        chain = (
            []
            if request.policy == RoutingPolicy.MANUAL_ONLY or not request.fallback_enabled
            else [m.id for _, m in ranked[1 : self.max_fallbacks + 1]]
        )
        return RoutingDecision(
            provider_id=model.provider_id,
            model_id=model.id,
            reason=f"{request.policy}:{request.task_type}:capability-and-health-score",
            confidence=0.9 if model.is_available else 0.5,
            fallback_chain=chain,
            estimated_cost_class=(model.pricing_json or {}).get("classification", "UNKNOWN"),
            required_capabilities=sorted(request.required_capabilities),
        )
