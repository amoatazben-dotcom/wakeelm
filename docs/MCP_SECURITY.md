# MCP security

Public HTTPS URLs only: reject loopback, localhost, RFC1918, link-local/metadata, reserved/non-global IPs, Railway/private internal domains, credentials in URL, odd ports, fragments and traversal. Validate DNS on admission and again on every connection, then pin the socket resolver to those checked addresses with cache disabled. TLS verification stays enabled. Redirects and compressed responses are denied. Bearer auth is bound to the original MCP origin; issuer tokens travel only to the reviewed issuer endpoint.

Per-request connect/read/deadline and cumulative byte bounds apply to the SDK HTTP stream. Pagination/cardinality and schema/argument size/depth are bounded. Remote `$ref`, dynamic references and regular-expression schema features are rejected to prevent network dereferencing and regex abuse. Schema validation uses jsonschema Draft 2020-12. Output structuredContent is validated when an output schema is supplied.

| Class | Behavior |
| --- | --- |
| Reviewed READ/SEARCH | LOW; eligible in READ_ONLY, SUGGEST or WORKSPACE |
| Reviewed CREATE/UPDATE/SEND | HIGH; WORKSPACE plus exact approval |
| Unknown or materially changed | Disabled; operator review required |
| Shell/SSH/arbitrary execute, secrets/admin/billing, production deploy | CRITICAL; unavailable |
| Database | Reviewed structured read only; raw SQL/query/command and mutation denied |
| GitHub MCP | Read only; native GitHub handles approved writes |
| Railway/Cloudflare/Vercel MCP | Read only; no deploy tool permission |

Approval binds user/job/step/server/tool/schema fingerprint/arguments and expiry. It is rechecked at invocation, together with current ownership, enablement, mode, scope and operator policy. A user cannot change the admin policy from Telegram. Tool-name matching is a conservative additional deny filter, not the basis of granting trust.

`ExternalToolOutputSanitizer` applies response limits and redacts recognizable keys/tokens/private keys/cookies/passwords, sensitive structured fields and known application/server secrets. Resource/prompt/tool messages are serialized as UNTRUSTED data with origin labels. Even a prompt-provided system role remains template data, never a system instruction. Unsafe secret-bearing schemas are sanitized and made CRITICAL. Secret heuristics cannot identify every arbitrary string; never configure credential-returning tools.

Audits record connection/auth/discovery/enablement/resource/prompt/call and approval outcomes without raw tokens or arguments containing secrets. MCP SDK internal logger is suppressed to avoid raw protocol content. Cancellation propagates to the SDK and cleanup, with a worker-level task deadline. Removing/disablement/permission/schema changes invalidate execution even for queued jobs.
