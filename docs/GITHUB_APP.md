# GitHub App setup

Create a GitHub App owned by the intended account/organization, and install it on selected repositories. Enable the user authorization flow and register exactly `https://<bot-domain>/integrations/github/callback`. Use the installation ID shown by GitHub in the Telegram App connection flow. The callback obtains the user identity and proves that the selected installation belongs to that user and this configured App.

| Repository permission | Setting |
| --- | --- |
| Metadata | Read |
| Contents | Read; Write only when agent publishing is enabled |
| Pull requests | Read; Write for PR creation |
| Issues | Read; Write only for explicitly enabled comments |
| Actions, Checks, Commit statuses | Read |
| Administration, Workflows, Secrets, Environments, Deployments | No permission |

Select installation/installation repositories, push, issues and pull request events for the webhook. The webhook endpoint is `https://<bot-domain>/webhooks/github`.

Set `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` (actual multiline PEM), `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_WEBHOOK_SECRET`, and `INTEGRATIONS_CALLBACK_BASE_URL` in private service variables. Do not place the private key or client secret in a repository workspace. Leave `GITHUB_WRITE_ENABLED=false` and `GITHUB_COMMENTS_ENABLED=false` until those paths are needed. Installation token requests are short-lived RS256 App JWTs and explicitly request only the configured permission set. A repository operation also sends `repository_ids` to narrow its installation token.

OAuth links are short-lived, private, single use tickets bound to the Telegram user and installation. Browser state and a secure HttpOnly SameSite=Lax nonce cookie bind the callback; PKCE S256 binds the authorization code. Tokens are encrypted with the existing master key. Expired/revoked App user tokens require reconnecting; automatic refresh of expiring GitHub App user tokens is not implemented. Installation tokens are created fresh, expire checked and never persisted.

For PAT fallback create a fine-grained token with an expiry, selected repositories and equivalent minimal permissions. The application can verify identity/access, but GitHub does not expose a reliable introspection API to prove the token's complete grant breadth; least-privilege token creation remains an account-owner setup step.

Live acceptance after credentials: authorize the App, list only accessible installed repositories, import a disposable repository, edit/validate, approve commit, approve push to `agent/*`, approve a draft PR, revoke installation and verify access fails. No production deployment is part of that acceptance.
