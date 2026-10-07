# Final security audit — 2026-10-07

Result: **FAIL for release / NOT_READY_FOR_BETA**. Local security regression tests pass; this does not override the runtime image gate.

## Findings and triage

| ID | Priority/status | Evidence | Required resolution |
| --- | --- | --- | --- |
| SEC-001 | P1 OPEN, release blocker | Trivy actual Debian runtime: 55 HIGH package findings, 16 distinct CVEs, 0 CRITICAL, no reported fixed version; see release-evidence/stage9-container-audit.json | Rebuild with patched packages/base or individually reviewed effective mitigation; rescan, no blanket suppression |
| OPS-001 | P1 BLOCKED | GitHub run 37556062529 jobs never started: account locked due to a billing issue | Resolve owner account lock and obtain successful hosted Checks for the final SHA |
| OPS-002 | P1 BLOCKED | No fresh Railway environment, real secrets, OIDC enrollment, external isolated validator or remote backup destination | Configure staging after build completion; run live acceptance and restoration before release |
| OPS-003 | P2 OPEN, release capacity gate | Only local controlled-provider 100-request/10-concurrency load exists | Execute broader deployment-specific queue/Telegram/admin/integration load or obtain an explicit bounded Beta capacity acceptance |
| UX-001 | P3 OPEN | Browser RTL/LTR passes; no real Telegram client/device accessibility review | Record live bilingual callback/help/approval flows and keyboard/mobile review |
| TEST-001 | P3 OPEN | Starlette warns about future httpx2 TestClient migration | Track upstream compatibility without unreviewed dependency replacement |

SEC-001 covers CVE-2025-69720; CVE-2026-12064, -16742, -54369, -66046, -76642, -76956, -76957, -78408, -78409, -78410, -8286, -8458, -8927, -93990 and -9538 in ncurses/curl/systemd/acl/expat/util-linux/perl. They are package-level scanner findings; exploitability has not been certified away. Non-root/no-capability execution reduces some exposure but is not an accepted security waiver.

## Validated controls

245 backend/service/integration tests pass with real PostgreSQL, Redis and Docker enabled (no skips), including tenant ownership, callback approval binding/expiry/replay, hashed stale edits, native/MCP roles, quota reservations, routing failover, secret redaction and encrypted memory. Real TLS transport tests cover redirects/origins/deadlines. SSRF tests cover public DNS pinning, rebinding/mixed answers, private/metadata/IPv6 and protocol restrictions.

OIDC signature/issuer/audience/nonce/MFA, admin roles/disabled identity, metadata filtering, CSRF/Origin and audited controls are tested through the actual API. Sandbox tests check network/secrets/host path isolation, readonly rootfs, nobody, no effective caps, no-new-privileges, actual cgroup memory256MiB/pids64/cpu1, timeout/cancellation/output and approved repair. Git clone/commit/push uses controlled local repositories; remote GitHub and MCP flows use controlled transports/SDK fixtures, not claims of a real external account test.

Python/npm dependency audits report no known findings; Bandit has no medium/high findings. Gitleaks current source and full Git history have no leaks. Raw private prompts and secrets are not included in reports. Live provider/OIDC/GitHub App/MCP issuer and production Docker/network isolation still require configured acceptance.

No Beta tag, live Railway deployment or production-stable claim is authorized by this audit result.

Actual Stage9 image: sha256:5c9a5137d9b34d4b9c8698c63dfce8543095870b8ef93ceafd47b3aeeeeb3186. Trivy0.75.0 returned exit1 with HIGH/CRITICAL gating. Python runtime package findings are zero after removing pip/build-tool vendors. A temporary alternative-base build was investigated but its package repository could not be resolved here; it was not adopted or counted as a passing runtime artifact.
