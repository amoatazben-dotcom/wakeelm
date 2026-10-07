# Beta release checklist

Current decision: **NOT_READY_FOR_BETA**. Version strings identify a candidate, not a released tag.

- [x] Freeze features; integrate stage 7/8 and preserve existing contracts.
- [x] Locked dependencies; lint/format; 245 backend tests without skips; 3 client tests; 2 real Chromium tests.
- [x] Zero-to-head and prior-stage data migrations; no schema drift; serialized migration locking.
- [x] Separate encrypted database restore and restored application startup; transactional old/new key rotation.
- [x] Callback/ownership/RBAC/CSRF/SSRF/injection/tool/real sandbox regressions; bounded routing/fallback/memory/accounting.
- [x] Arabic/English dictionaries/help and browser RTL/LTR controls; metadata API review.
- [x] Version/build/schema endpoints, changelog, operator/admin/security runbooks, triaged release evidence.
- [x] Source/history/SAST and Python/npm dependency checks; actual runtime image scanned.
- [ ] Resolve SEC-001 HIGH runtime image findings and obtain security PASS.
- [ ] Hosted Checks successful for the exact final SHA; fix GitHub billing lock first.
- [ ] Provision fresh isolated Railway staging, private DB/Redis/volume and production-compatible sandbox validation.
- [ ] Configure real bot/OIDC/provider/App/MCP and remote backups/monitoring; validate credentials in private UI only.
- [ ] Live Telegram/provider/admin/integration end-to-end smoke and mobile/accessibility review.
- [ ] Broader deployment load/worker failover/Redis loss/remote backup restore drill, or explicit reviewed Beta capacity limit.
- [ ] Protect GitHub environments, configure scoped tokens and exact-SHA gate attestation; test controlled staging deployment.
- [ ] All A–J gates PASS, exact commit/image recorded, tag/release only then.

See STAGE_9_FINAL_REPORT, FINAL_SECURITY_AUDIT and release-evidence/stage9-gates.json. Never check a box merely because a mock exists or a job was skipped.
