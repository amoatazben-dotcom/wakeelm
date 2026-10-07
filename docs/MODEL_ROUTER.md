# Model router

`ModelRouter` selects only models joined to the requesting user's enabled providers. Routing is deterministic for the same catalog, health history and policy; model IDs break ties. The router uses four SQL queries instead of a query per candidate and caps the catalog at 1,000 models and health evidence at 20 checks/model.

Policies: AUTO, PREFER_FREE, PREFER_CHEAP, PREFER_FAST, PREFER_STRONGEST, PREFER_LONG_CONTEXT, PREFER_CODING, MANUAL_ONLY. Existing users retain MANUAL_ONLY and disabled fallback until they change their Telegram settings. Manual mode always preserves the user's selected model, including specialist calls. Automatic specialist routing can use long-context analysis, stronger review and cheaper documentation policies.

Scores combine observed availability, failure rate, latency, validated metadata, context capacity, known prices, coding/tool/reasoning/JSON capabilities and user cost/latency preference. Required capabilities exclude UNKNOWN and INFERRED evidence. TESTED maps to VERIFIED; PROVIDER_METADATA maps to PROVIDER_REPORTED. Model names never prove capabilities. Unknown context sizes cannot satisfy an explicit context requirement.

Optional user-confirmed probes support chat, bounded Python response syntax, JSON responses and actual native tool-call responses. Probes make one call, never execute code, retain a digest rather than response text, enforce a cooldown and expire after 24 hours. JSON response evidence does not prove every provider-specific JSON Schema mode. Vision/streaming/long-context probes are deliberately not sent without a suitable bounded test.

`RoutingGateway` serves real chat, project answers and planning. A bounded fallback chain considers other models/providers. AUTH_FAILED skips the rest of that provider; rate limits, timeouts, unavailable models, oversized context and invalid responses can fall back. Safety rejection, ownership/policy/quotas and unknown failures never trigger another billable call. Manual mode never falls back. Each attempt has a durable reservation, health latency and classified reason. Shared circuits prevent repeated calls to an unavailable endpoint.

Tests: `tests/test_routing.py`, existing gateway/service tests. The classifier is bilingual deterministic rules, not a claim of semantic perfection. Strongest is a capability score, not a benchmark ranking. Unknown prices remain unknown.
