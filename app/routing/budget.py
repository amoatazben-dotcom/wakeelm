import time
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.exceptions import SafeError
from app.routing.router import number


class CostEstimator:
    @staticmethod
    def estimate(pricing, input_tokens, output_tokens):
        if pricing.get("classification") in {"FREE_VERIFIED", "FREE_REPORTED"}:
            return Decimal(0)
        if "prompt" not in pricing or "completion" not in pricing:
            return None
        return (
            Decimal(str(number(pricing["prompt"]))) * input_tokens
            + Decimal(str(number(pricing["completion"]))) * output_tokens
        )


@dataclass
class ExecutionBudget:
    max_model_calls: int = 12
    max_agent_steps: int = 30
    max_total_tokens: int = 100000
    max_estimated_cost: Decimal = Decimal("1")
    max_duration: float = 300
    model_calls: int = 0
    agent_steps: int = 0
    total_tokens: int = 0
    estimated_cost: Decimal = Decimal(0)
    started: float = field(default_factory=time.monotonic)

    def reserve(self, tokens=0, cost=None, steps=0):
        if (
            self.model_calls + 1 > self.max_model_calls
            or self.agent_steps + steps > self.max_agent_steps
            or self.total_tokens + tokens > self.max_total_tokens
            or self.estimated_cost + (cost or 0) > self.max_estimated_cost
            or time.monotonic() - self.started > self.max_duration
        ):
            raise SafeError("AGENT_LIMIT")
        self.model_calls += 1
        self.agent_steps += steps

    def account(self, tokens, cost=None):
        self.total_tokens += tokens
        self.estimated_cost += cost or 0
        if (
            self.total_tokens > self.max_total_tokens
            or self.estimated_cost > self.max_estimated_cost
        ):
            raise SafeError("AGENT_LIMIT")
