import ast
import hashlib
import json
from datetime import timedelta

from app.core.exceptions import SafeError
from app.db.base import now
from app.routing.budget import ExecutionBudget


class ModelCapabilityProbe:
    """Explicit, one-call probes with a 24-hour evidence TTL; never execute generated code."""

    ALLOWED = {"chat", "coding", "tool_calling", "structured_output"}

    def __init__(self, models):
        self.models = models

    async def run(self, model_id, capability):
        if capability not in self.ALLOWED:
            raise SafeError("INVALID_INPUT")
        model = await self.models.owned.model(model_id)
        evidence = (model.capabilities_json or {}).get(capability, {})
        if evidence.get("probe_expires_at", "") > now().isoformat():
            return evidence
        await self.models.providers.limits.cooldown(f"probe:{self.models.user_id}", 60)
        prompts = {
            "chat": "Reply with OK.",
            "coding": "Return ONLY Python code: a function add(a, b) that returns a+b. No fences.",
            "structured_output": 'Return ONLY JSON: {"probe_ok": true}',
            "tool_calling": "Call the supplied probe_ok tool with ok=true. Do not execute anything.",
        }
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "probe_ok",
                    "description": "Read-only evidence probe; no execution",
                    "parameters": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                },
            }
        ]

        async def invoke(candidate):
            if capability == "tool_calling":
                return await self.models._agent_completion(
                    candidate, [{"role": "user", "content": prompts[capability]}], tools
                )
            return await self.models._completion(candidate, prompts[capability], max_tokens=128)

        content, usage = await self.models.routing.execute(
            model,
            invoke,
            input_tokens=50,
            output_tokens=128,
            budget=ExecutionBudget(max_model_calls=1),
            allow_fallback=False,
        )
        supported = False
        try:
            if capability == "chat":
                supported = bool(content.strip())
            elif capability == "coding":
                tree = ast.parse(content)
                supported = any(
                    isinstance(node, ast.FunctionDef) and node.name == "add" for node in tree.body
                )
            elif capability == "structured_output":
                supported = json.loads(content) == {"probe_ok": True}
            else:
                supported = usage.get("_native_tool_calls") == 1
        except (ValueError, SyntaxError, TypeError):
            pass
        evidence = {
            "state": "SUPPORTED" if supported else "UNKNOWN",
            "source": "TESTED" if supported else "NOT_TESTED",
            "evidence_type": "BOUNDED_RESPONSE_PROBE",
            "probe_expires_at": (now() + timedelta(hours=24)).isoformat(),
            "response_digest": hashlib.sha256(content.encode()).hexdigest(),
        }
        # A response-format probe is evidence of bounded JSON output, not every JSON Schema format.
        model.capabilities_json = {**model.capabilities_json, capability: evidence}
        await self.models.session.commit()
        return evidence
