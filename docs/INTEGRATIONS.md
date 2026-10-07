# Integration registry

`IntegrationRegistry` defines language-neutral capability categories READ, SEARCH, CREATE, UPDATE, DELETE, SEND, EXECUTE, DEPLOY, ADMIN and SECRETS. Categories describe policy potential, not a connection or a permission grant. GitHub is the implemented native integration. GitHub MCP, Supabase, Drive, Gmail, Calendar, Slack, Notion, Linear, Jira, Railway, Cloudflare and Vercel are policy profiles for user-provided MCP endpoints; no provider-specific OAuth helper or account connection is bundled for those services.

Deployment/cloud/database profiles remain read only. A reviewed server/tool schema is still required. The generic MCP client can interact with a compatible endpoint, but it does not make every listed provider compatible with this restricted OAuth/discovery profile. Native GitHub alone handles repository writes.

All integration data has user-owned SQL records and encrypted credentials. Long discovery/import/auth follow-up operations reuse AgentJob and the existing worker lease, workspace lock, cancellation, notification, job-status UI and time bounds. There is no integration-specific orchestrator or ungoverned execution engine. FastAPI only implements bounded OAuth callback/webhook work and enqueues follow-up discovery; Telegram does not block on clone/discovery/model execution.
