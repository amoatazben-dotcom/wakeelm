import time

from app.core.exceptions import SafeError
from app.db.base import now
from app.db.models import ModelHealthCheck
from app.platform.circuit import CircuitBreaker
from app.routing.budget import CostEstimator, ExecutionBudget
from app.routing.classifier import TaskClassifier
from app.routing.preferences import RoutingPreferences
from app.routing.router import ModelRouter
from app.routing.schemas import RoutingPolicy, RoutingRequest

FAILURES = {
    "AUTH_FAILED": "AUTH_FAILED",
    "RATE_LIMITED": "RATE_LIMITED",
    "PROVIDER_OFFLINE": "PROVIDER_OFFLINE",
    "TIMEOUT": "TIMEOUT",
    "UNSUPPORTED": "MODEL_UNAVAILABLE",
    "CONTEXT_TOO_LARGE": "CONTEXT_TOO_LARGE",
    "TOOL_UNSUPPORTED": "TOOL_UNSUPPORTED",
    "INVALID_RESPONSE": "INVALID_RESPONSE",
    "SAFETY_REJECTION": "SAFETY_REJECTION",
}
RETRYABLE = {
    "AUTH_FAILED",
    "RATE_LIMITED",
    "PROVIDER_OFFLINE",
    "TIMEOUT",
    "MODEL_UNAVAILABLE",
    "CONTEXT_TOO_LARGE",
    "TOOL_UNSUPPORTED",
    "INVALID_RESPONSE",
}


class RoutingGateway:
    def __init__(self, models):
        self.models = models
        self.last_decision = None
        self.fallbacks = []

    async def select(self, text, required=None, context_size=0, policy=None):
        prefs = await RoutingPreferences(self.models.session, self.models.user_id).get()
        from app.platform.flags import FeatureFlags

        if prefs["policy"] != "MANUAL_ONLY":
            await FeatureFlags(self.models.session, self.models.user_id).require(
                "experimental_router"
            )
        selected = RoutingPolicy(
            prefs["policy"] if prefs["policy"] == "MANUAL_ONLY" else (policy or prefs["policy"])
        )
        manual = await self.models.active() if selected == RoutingPolicy.MANUAL_ONLY else None
        classification = TaskClassifier().classify(text, context_size)
        request = RoutingRequest(
            task_type=classification.task_type,
            task_complexity=classification.complexity,
            required_capabilities=required or set(),
            context_size=context_size,
            policy=selected,
            manual_model_id=manual.id if manual else None,
            fallback_enabled=prefs["fallback_enabled"],
        )
        settings = getattr(self.models, "settings", None)
        self.last_decision = await ModelRouter(
            self.models.session, self.models.user_id, getattr(settings, "max_model_fallbacks", 2)
        ).route(request)
        from app.services.audit_service import audit

        audit(
            self.models.session,
            self.models.user_id,
            "MODEL_ROUTED",
            "model",
            self.last_decision.model_id,
            status=selected.value,
            routing_policy_version=self.last_decision.routing_policy_version,
            reason=self.last_decision.reason,
            confidence=self.last_decision.confidence,
            fallback_chain=self.last_decision.fallback_chain,
            required_capabilities=self.last_decision.required_capabilities,
            task_type=classification.task_type.value,
            classifier_version=classification.classifier_version,
        )
        return await self.models.owned.model(self.last_decision.model_id)

    async def execute(
        self,
        model,
        invoke,
        input_tokens=0,
        output_tokens=1800,
        budget=None,
        allow_fallback=True,
        record_health=True,
    ):
        budget = budget or getattr(self.models, "budget", None) or ExecutionBudget()
        decision = self.last_decision
        chain = [model.id] + (
            decision.fallback_chain
            if allow_fallback and decision and decision.model_id == model.id
            else []
        )
        excluded = set()
        last_error = None
        for ident in chain:
            candidate = await self.models.owned.model(ident)
            if candidate.provider_id in excluded:
                continue
            cost = CostEstimator.estimate(candidate.pricing_json or {}, input_tokens, output_tokens)
            from app.platform.flags import FeatureFlags
            from app.platform.usage import QuotaEngine

            await FeatureFlags(self.models.session, self.models.user_id).deny_if(
                f"disable_provider_{candidate.provider_id}"
            )
            budget.reserve(
                input_tokens + output_tokens,
                cost if cost is not None else __import__("decimal").Decimal("0.10"),
            )
            ledger = await QuotaEngine(
                self.models.session, self.models.user_id, getattr(self.models, "settings", None)
            ).reserve(
                "model",
                input_tokens,
                output_tokens,
                cost,
                candidate.provider_id,
                candidate.id,
                getattr(getattr(self.models, "job", None), "id", None),
            )
            await self.models.session.commit()
            breaker = CircuitBreaker(self.models.providers.limits.redis, f"model:{candidate.id}")
            from app.platform.telemetry import metric

            metric("model_calls")
            started = time.monotonic()
            error = None
            try:
                await breaker.before()
                job = getattr(self.models, "job", None)
                if job:
                    job.model_requests += 1
                result = await invoke(candidate)
                await breaker.success()
                usage = result[1]
                incoming = max(0, int(usage.get("prompt_tokens", 0) or 0))
                outgoing = max(0, int(usage.get("completion_tokens", 0) or 0))
                ledger.input_tokens, ledger.output_tokens = incoming, outgoing
                final_estimate = CostEstimator.estimate(
                    candidate.pricing_json or {}, incoming, outgoing
                )
                if final_estimate is not None:
                    ledger.estimated_cost = final_estimate
                ledger.pricing_status = "KNOWN" if final_estimate is not None else "UNKNOWN"
                ledger.status = "COMPLETED"
                metric("model_tokens", incoming + outgoing)
                if final_estimate is not None:
                    metric("model_cost", float(final_estimate))
                if job:
                    job.input_tokens += incoming
                    job.output_tokens += outgoing
                budget.account(
                    incoming + outgoing,
                    final_estimate
                    if final_estimate is not None
                    else __import__("decimal").Decimal("0.10"),
                )
                return result
            except SafeError as exc:
                error = exc
                ledger.status = "FAILED"
                failure = FAILURES.get(exc.code, "UNKNOWN")
                if failure not in RETRYABLE:
                    raise
                if failure == "AUTH_FAILED":
                    excluded.add(candidate.provider_id)
                await breaker.failure()
                metric("provider_errors")
                metric("fallback_count")
                self.fallbacks.append({"model_id": ident, "reason": failure})
                last_error = exc
            finally:
                metric("provider_latency", time.monotonic() - started, observe=True)
                ledger.duration_ms = int((time.monotonic() - started) * 1000)
                if record_health:
                    self.models.session.add(
                        ModelHealthCheck(
                            model_id=candidate.id,
                            status="FAILED" if error else "AVAILABLE",
                            error_code=error.code if error else None,
                            latency_ms=int((time.monotonic() - started) * 1000),
                            checked_at=now(),
                        )
                    )
                await self.models.session.commit()
        raise last_error or SafeError("NO_ACTIVE_MODEL")
