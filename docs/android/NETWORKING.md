# Networking and streaming

Retrofit 3 + OkHttp + kotlinx.serialization use `BuildConfig.BACKEND_URL`. Set `-PbackendUrl=https://your-backend.example/`; HTTPS and the trailing slash are enforced at build configuration, cleartext is disabled in the manifest, redirects and automatic transport replay are disabled. No request/response logging interceptor exists. Authorization, pairing codes and provider tokens are never logged.

AuthInterceptor attaches the account access token. RefreshAuthenticator serializes refresh, detects a newer token from another request, rotates stored tokens with compare-and-set, and retries the original request once. A second 401 stops. Auth calls never recursively refresh. Transient errors leave an offline session available; an explicit invalid refresh clears it.

ChatStreamClient provides a Flow abstraction. The SSE implementation uses authenticated POST `/api/v1/chat/stream`; `started`, `delta`, `fallback`, `snapshot`, `done`, `error` are parsed into typed events. Callback delivery is bounded; overflow fails rather than silently dropping tokens. Cancellation closes the underlying EventSource and the server aborts its provider request. EOF without `done` is failure. There is no infinite retry.

Recover uses the same request UUID and reads the durable result without starting a second generation. Explicit Retry uses a new UUID. The backend locks one generation per user across replicas. Fallback resets partial text and displays a localized notice, using the existing owned routing chain and cost ledger. Gateway cost/usage estimates remain estimates when provider usage is absent.

The new provider SSE transport preserves public-only pinned DNS/SSRF checks, no environment proxies, no redirects, response/line bounds, no decompression, bounded connection/read/total time, and safe status errors. Providers that do not implement OpenAI-compatible SSE return a safe failure; a buffered response is never represented as streaming.
