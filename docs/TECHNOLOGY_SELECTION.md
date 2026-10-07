# Technology selection for Stages 5/6

Decision: retain Python for orchestration, callbacks, Git control and MCP. Production targets Linux/Python 3.13 with trusted Git installed. The official MCP SDK is locked at 1.30.0. PostgreSQL and Redis remain the existing storage/queue/lease dependencies. Git is an external trusted native executable; it already supplies optimized clone/pack/diff without building another runtime.

| Candidate | Evidence / decision |
| --- | --- |
| Python async + official MCP SDK | Controlled SDK server passes discovery/tools/resources/prompts/OAuth/refresh and bounded transport tests; existing worker/policy/encryption are reused |
| Python + trusted Git argv | Real clone/fetch/status/branch/stage/commit/push fixture works under path/env/limits checks; Git already handles CPU-intensive object work |
| Rust repository runtime | No measured bottleneck demonstrating a benefit. Adds build/toolchain/IPC/schema duplication and another attack surface. Not implemented |
| TypeScript integration helper | No needed provider has demonstrated missing Python SDK/auth functionality. Adds Node deployment/secrets boundary and duplicated OAuth policy. Not implemented |
| Go or separate MCP orchestrator | No justified need; would fragment the existing job and approval authority. Not implemented |

The measurable evidence is functional verification, not a throughput benchmark. Do not claim performance gains without profiling. If clone/index throughput or a specific provider auth flow later establishes a benefit, isolate it behind GitService or the MCP/auth adapter, retain JSON-compatible contracts, user ownership, schema fingerprint and the single approval engine, add parity tests and document its benchmark/cost. Until then the fallback is the existing Python implementation and trusted Git. Fail closed when Git, approved tool policy, OAuth client or sandbox is unavailable.

Railway consequently needs one Python app service, PostgreSQL, Redis and a persistent private volume, with a future external isolated validator. No Rust/Node/Go sidecar, separate integration worker, second queue or deployment credential service is required by these stages.

## Stages 7/8

Python remains the authoritative router, coordinator, memory, quota, identity and operational API control plane. TypeScript/React is used for the admin web UI and browser tests, where typed components and RTL state directly benefit the operator. Vite produces static assets served by FastAPI; this avoids a second Node server, duplicated session authority and an unnecessary authenticated internal-service boundary. Node 24 is build/test only and is absent from the final Python runtime image. API contracts are typed in `admin-web/src/api.ts`; server RBAC/CSRF/OIDC remains authoritative.

Rust/Go and a TypeScript integration sidecar remain unimplemented because the measured bounded local load does not establish a benefit that outweighs another runtime and policy boundary. Native Git already provides repository operations. The fixture measurement is not a production benchmark. External observability and object storage may be provisioned later as operational services; no imaginary service is listed as deployed.
