# Client API v1

These routes did not exist in the platform; this branch implements an authenticated native compatibility layer over the existing services, not a second provider/agent engine. Deploy this backend branch and apply migration before Android end-to-end use. The currently deployed main backend is not assumed to expose these endpoints.

Bearer access token required except exchange, refresh, and client health. Errors contain a safe `error`/`detail` code; client UI maps codes to resources. Validation 422 never includes raw submitted input.

| Method | Route | Shape/behavior |
| --- | --- | --- |
| POST | `/api/v1/auth/exchange` | `{value: pairing_code}` → `{access_token,refresh_token,expires_in}` |
| POST | `/api/v1/auth/refresh` | `{value: refresh_token}` → rotated token pair |
| POST | `/api/v1/auth/logout` | revoke session family |
| GET | `/api/v1/me` | `{id,name,language}` shared Telegram user |
| GET | `/api/v1/health/client` | `{status,api_version,streaming}` |
| GET/POST | `/api/v1/providers` | list/add owned providers; add uses existing `ProviderInput` |
| PUT/DELETE | `/api/v1/providers/{id}` | edit/delete owned provider |
| POST | `/api/v1/providers/{id}/test` | backend discovery + persisted provider status |
| POST | `/api/v1/providers/{id}/models` | refresh discovery |
| GET | `/api/v1/models` | owned metadata/capabilities/pricing/status (bounded 5000) |
| GET | `/api/v1/models/{id}` | owned model details |
| POST | `/api/v1/models/{id}/select` | durable active model selection |
| GET/PUT | `/api/v1/routing/preferences` | policy, fallback; GET includes active model/automatic feature flag |
| GET/POST | `/api/v1/conversations` | list (bounded 200)/create `{title}` |
| GET | `/api/v1/conversations/{id}/messages` | ordered cache snapshot (bounded 500) |
| POST | `/api/v1/chat/stream` | `{conversation_id,request_id,text}`; authenticated SSE |

Provider DTO: `id,name,base_url,status,token_hint`. Model DTO: `id,provider_id,name,external_id,status,pricing,capabilities,metadata`. Message DTO: `id,conversation_id,request_id,role,content,status`.

SSE `started {id,model_id}`, `delta {text}`, `fallback {model_id}`, `snapshot {MessageDto}`, `done {status}`, `error {code}`. `: keepalive` comments are sent during upstream waits. Terminal statuses: COMPLETED/FAILED/CANCELLED; local intermediate statuses SENDING/STREAMING. Reusing request_id recovers a stored assistant result. Retry generation must deliberately use a new ID.

Routing policies: AUTO/PREFER_FREE/PREFER_FAST/PREFER_CHEAP/PREFER_STRONGEST/PREFER_CODING/MANUAL_ONLY (platform also supports long context). Automatic policies respect `experimental_router`. Capability/price filters use reported metadata; speed is not inferred from names. Provider tests are model discovery, not a paid completion. Unknown capability/context/price stays unknown.
