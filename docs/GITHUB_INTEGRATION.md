# GitHub integration

Native GitHub is the authoritative path for repository writes. GitHub App is the recommended connection; a fine-grained `github_pat_` token limited to selected repositories is the fallback. Classic PATs are rejected. No GitHub CLI credential store is used by the application.

In a private Telegram chat: GitHub → connect → App (installation ID and private OAuth link) or scoped PAT → connection status → refresh repositories → search/paginated repositories → repository details → import. PAT/token messages are deleted when Telegram permits it and stored encrypted. App OAuth persists the user token encrypted; short-lived installation tokens remain in memory and are narrowed to the selected repository. Discovery uses the intersection of user access and App installation access, never the installation's full repository list as proof of user authorization. Permission is rechecked before import and GitHub actions.

Connections and repository workspace links belong to one application user. Revocation clears the encrypted connection token and disables all linked repositories. A revoked/removed repository cannot continue an existing job. GitHub repository IDs are compared with fresh API metadata, including archive/disabled state, before use. Repository discovery caps at 1,000 entries and branch checks cap at 1,000; larger sets fail closed.

Read APIs cover repository identity, branches/protection summaries, issues, pull requests, commits/comparisons, checks, Actions runs and statuses. Write APIs only create agent-branch commits/pushes, draft or explicit PRs and optionally issue/PR conversation comments. Merge, force push, workflow dispatch, releases, deletion, secrets, billing and administration are absent. All high-risk writes flow through the existing job/approval engine.

`POST /webhooks/github` validates HMAC-SHA256 over the bounded raw body and uses Redis delivery IDs to reject concurrent replay and acknowledge completed duplicates. Installation deletion/suspension revokes connections; removed repositories are disabled. Repository events update metadata; they cannot approve work or automatically merge/push. Configure the webhook secret before enabling this endpoint.

Tests use fixed GitHub API responses, a real local bare Git fixture, signed ASGI webhook requests, and simulated Telegram. A real GitHub App installation has not been exercised without the owner's App credentials; see GITHUB_APP.md for the remaining live check.
