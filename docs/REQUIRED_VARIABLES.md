# Required deployment configuration — values are not provisioned

Configure these privately after the audit blockers are resolved. No real secret values are stored here or requested in chat.

| Variable | Required value/source |
| --- | --- |
| TELEGRAM_BOT_TOKEN | BotFather bot token |
| DATABASE_URL | Private Railway PostgreSQL reference |
| REDIS_URL | Private Railway Redis reference |
| MASTER_ENCRYPTION_KEY | Persistent Fernet key; back up privately, never regenerate on restart |
| WORKSPACE_STORAGE_ROOT | Persistent private volume path owned by UID10001 |
| APP_ENV | production for live service |
| PUBLIC_BASE_URL | Application HTTPS URL |
| BOT_MODE | polling initially with one replica, or configured webhook |
| WEBHOOK_SECRET | Random Telegram webhook secret when webhook mode is enabled |
| INTEGRATIONS_CALLBACK_BASE_URL | HTTPS callback base matching registered integrations |
| ADMIN_OIDC_ISSUER | Trusted issuer HTTPS URL |
| ADMIN_OIDC_AUTHORIZE_URL / ADMIN_OIDC_TOKEN_URL / ADMIN_OIDC_JWKS_URL | Issuer endpoints, approved public HTTPS origins |
| ADMIN_OIDC_CLIENT_ID / ADMIN_OIDC_AUDIENCE | Registered OIDC client/audience |
| ADMIN_OIDC_CLIENT_SECRET | Issuer secret when client requires one |
| ADMIN_REQUIRE_MFA | true; enroll reviewed admin subjects with issuer MFA |
| ADMIN_SUPER_SUBJECTS | JSON list of reviewed initial admin subject identifiers |
| BUILD_GIT_SHA / BUILD_TIMESTAMP | Exact reviewed source SHA and build timestamp; never unknown for release |
| BACKUP_ENCRYPTION_KEY | Separate persistent Fernet key in backup runner, not a user token |

Set SANDBOX_BACKEND=disabled until an isolated production validator is available; validation-required publication must remain blocked. Keep writes off until acceptance. Configure private remote encrypted backup destination, workspace snapshot/schedule and alert/exporter destinations; these operational resources are not provisioned.

GitHub App/OAuth requires GITHUB_APP_* / GITHUB_CLIENT_* and GITHUB_WEBHOOK_SECRET as appropriate; MCP OAuth clients/policies require explicit reviewed JSON. User provider/PAT/MCP credentials are added in private user flows and encrypted in SQL; they are not shared global deployment variables.

For the unused manual CI deployment workflow, protect staging/production GitHub environments and configure secret RAILWAY_TOKEN plus RAILWAY_SERVICE_ID, RAILWAY_ENVIRONMENT_ID, APP_PUBLIC_URL. Production needs reviewed RELEASE_GATE_REPORT_JSON covering its exact SHA and all A–J gates PASS. Automatic Railway GitHub deployment must not bypass this workflow. See .env.example and OPERATIONS.
