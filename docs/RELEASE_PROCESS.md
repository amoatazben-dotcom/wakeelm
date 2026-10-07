# Controlled release process

Stages 7/8 software is version 0.8.0; the final beta candidate belongs to stage 9. Keep app/API/agent/routing policy, build SHA/time and Alembic schema evidence together. Do not tag a beta because local tests passed while mandatory deployment/security gates remain blocked.

Run frozen Python/Node installs, lint/format, provider/integration/ownership/security/real-sandbox tests, fresh and previous-stage data migration, encrypted separate-target restore, rotation, browser Arabic/English/RTL and measured load. Scan dependencies, current source and full Git history and the actual runtime image. Triaged unresolved high-risk findings block the candidate.

CI uses read-only contents permissions and SHA-pinned actions. Python and admin pipelines include their real tests. PostgreSQL/Redis fixtures are isolated. Current GitHub hosted jobs may be blocked by account billing; local evidence is not a claimed hosted CI success.

Railway is explicitly deferred until construction/audit finish. Docker builds TypeScript once and serves assets in the Python service. PostgreSQL/Redis are private; one worker lease coordinates replicas; dedicated predeploy migrations use an advisory lock. Provision the persistent private volume with UID 10001 ownership and keep risky sandbox validation disabled until a genuinely isolated runtime exists. Configure the variables in `.env.example` through the platform secret store.

Only a reviewed main SHA may go to staging. Production requires all stage 9 gates and explicit release configuration/approval. This repository has no workflow deploying arbitrary branches and no release tag yet. After deployment verify HTTPS, OIDC MFA, readiness, version, lease failover, backups, webhook signatures and user read-only acceptance before enabling external writes.

Stage9 candidate: 0.9.0-beta.1, not tagged. See STAGE_9_FINAL_REPORT and BETA_RELEASE_CHECKLIST. Checks includes a checksum-pinned Trivy runtime HIGH/CRITICAL failure gate. The manual main-only deploy.yml is not triggered by push; successful exact-SHA Checks and protected environment configuration precede staging. Production requires a separately reviewed exact-SHA RELEASE_GATE_REPORT_JSON attestation covering A–J, so documentation commits cannot reuse older candidate evidence. No workflow has been dispatched.
