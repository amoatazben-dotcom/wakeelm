# Security operations

Keep provider/GitHub/MCP credentials encrypted with the persistent master key, backup ciphertext encrypted with a separate key, and OIDC/client/webhook secrets in the platform secret store. Do not commit keys, source archives, cookies, OAuth codes or raw customer data. The admin API exposes safe operational metadata only.

Containment: enable global write/provider/job kill switches, disable affected user/identity/integration, cancel and acknowledge running jobs, preserve audit metadata and image/build identifiers. Revoke compromised credentials at the issuing service before replacement. Treat pending remote writes as uncertain outcomes and reconcile manually; no automatic repeated publish/tool write.

Run full source/history Gitleaks, locked Python/Node audits, medium/high Bandit and `sh scripts/scan_container.sh IMAGE REPORT`. HIGH/CRITICAL runtime findings fail the gate including findings without an available fix. Do not blanket-ignore package families or copy a dependency audit PASS onto the runtime image. Rebuild from reviewed patched bases, rescan the actual candidate and record any individual reviewed mitigation with accountable owner and expiry; the current high findings have no accepted exemption.

SSRF protection pins resolved public IPs, rejects private/loopback/metadata/IPv6/mixed DNS and unsafe redirects; enforce it for provider, GitHub/MCP/OAuth/JWKS origins. Changing egress policy requires the transport tests. No arbitrary shell, stdio MCP, Docker mount or host runner fallback is permitted. Treat project/provider/MCP/memory text as lower-trust data; it cannot grant approval or change roles.

Maintain least-privilege OIDC roles/MFA, 900-second sessions, CSRF/Origin checks, secure cookies and immutable admin write audit. Review bootstrap subjects and disable records regularly. Configure private SQL/Redis, volume UID ownership, backup destination and monitoring before exposing live traffic. Follow INCIDENT_RESPONSE and DISASTER_RECOVERY for escalation and recovery; operational alert/on-call endpoints remain unconfigured.
