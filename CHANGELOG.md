# Changelog

## 0.9.0-beta.1 — candidate only, 2026-10-07

No Beta tag or release has been published. Release recommendation: NOT_READY_FOR_BETA.

- Integrate scoped routing, bounded fallback, specialist graphs, encrypted memory, durable usage/quota controls and shared circuits.
- Add OIDC/MFA admin authentication, scoped roles, audit, bilingual static operations UI, metadata-only views and emergency controls.
- Add encrypted backup/separate-target restore, transactional key rotation, retention and safe external write receipts.
- Fix missing workspace storage detection: retain indexed SQL data, mark the workspace MISSING and stop instead of reporting a successful empty reindex.
- Validate real sandbox kernel resource/privilege limits, migrations, preserved data, restored application readiness and key rotation.
- Add exact-source CI and manual deployment gates; fail image security checks on HIGH/CRITICAL findings.
- Update bilingual help and candidate version/build/schema metadata; freeze new features.

Known blockers: unresolved Debian image HIGH findings, hosted CI billing lock, production isolated validator and live configuration/acceptance, fresh Railway deployment and broader operational load certification.
