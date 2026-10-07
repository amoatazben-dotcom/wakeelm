# MCP client

The implementation uses the official Python `mcp` SDK, locked at 1.30.0, inside the existing FastAPI/aiogram service. Only HTTPS Streamable HTTP is supported; the SDK negotiates a supported protocol and records the server's negotiated version. Legacy SSE transport, stdio, local commands and auto-installing MCP packages are rejected. The client is not a second orchestrator.

Telegram Tools/MCP → add server name and HTTPS URL → queued capability discovery → server status/tools/resources/prompts. Connect using explicitly scoped OAuth or a narrow bearer token when required. Server name/URL, status, auth type, counts and discovery timestamps are visible. Refresh, inspect, enable/disable tools, disable/remove server and start a task using that server are implemented. Removed servers clear tokens and credentials and disable all tools.

`initialize`, bounded paginated `tools/list`, `resources/list`, `prompts/list`, `tools/call`, `resources/read`, and `prompts/get` use SDK sessions. Prompts with arguments ask for a bounded JSON object, including required parameter checks. Only previously discovered resource URIs and prompt names may be requested. No sampling, roots, elicitation or server-originated execution callbacks are granted.

Discovery stores input/output JSON schemas, description, risk, metadata, enable state and a schema/description/output fingerprint. Tools start disabled. Inspect a tool's fingerprint; an operator must review its semantics and configure `MCP_TOOL_POLICIES` before the user can enable it. Material schema or description changes disable it and invalidate pending approvals until re-reviewed. Names/annotations such as read_only are insufficient proof.

Policy example (replace the fingerprint with the reviewed actual value):

```json
{"https://service.example/mcp#search_records":{"fingerprint":"<sha256>","capability":"SEARCH","integration":"drive","required_scopes":["read"]}}
```

Environment dict/list values use JSON. Exact URL + external tool name identify the policy. Do not wildcard remote tools. `ToolRouter` exposes at most eight enabled relevant MCP schemas to a request, based on integration/name keywords or explicit server selection. Native GitHub remains authoritative for writes; GitHub MCP writes are disabled.

Discovery, resource and prompt reads reuse the existing durable AgentJob queue. Dynamic tools execute through ToolRegistry → ToolPolicyEngine → MCPToolAdapter → MCPService, with existing mode, ownership, cancellation, deadline, call-count and approval controls. Integration maintenance does not require an active AI model; model-based tasks do.

Network/size/time failures produce safe codes. The controlled official-SDK test server verifies discovery, tools, resources/prompts, approvals, auth and refresh. Real external services require their own endpoints and approved policies; no Gmail/Calendar/etc connection is claimed by merely listing registry profiles.
