# Repository agent workflow

Repository import is a background `AgentJob` operation. A canonical GitHub HTTPS URL and current authorization are verified; a shallow clone of the default branch is fetched into private metadata and checked for symlinks, submodules, traversal and size/count limits before checkout. The working tree is indexed by the Stage 3 pipeline, with its existing encrypted context and ignore rules. Git objects/config/hooks/askpass are outside the editable tree.

A READ_ONLY task reads without creating a branch. SUGGEST or WORKSPACE prepares a unique `agent/task-<job>-<random>` branch before the existing Stage 4 planner runs. Base SHA is fixed at import, and a fetch checks it before preparation and writes. If the base changes, the job fails `STALE_REPOSITORY`; there is no automatic merge/rebase. A workspace branch belongs to one job. To start an independent task import a fresh workspace; publishing actions resume the same completed job through `AgentService.enqueue_action`.

The existing patch, diff, approval, rollback and isolated validation tools perform the edits. The repository detail card provides commit, push and PR actions. The commit asks for a message, computes an exact file set, and requires a successful validation for the current workspace digest. Commit, push and PR each present separate persisted approvals bound to repository/connection/branch/head/base and exact arguments. Full approval details can be downloaded, avoiding Telegram truncation. PR title/body/draft and MCP arguments are included in review details.

Push must reference the same committed SHA, a clean tree and the recorded digest, and pass a fresh secret/artifact scan. It uses exactly `HEAD:refs/heads/agent/...`, without force. PR creation needs that same pushed SHA and targets the current default branch. UI-created PRs are drafts. There is no merge button or auto-merge implementation.

An explicit `issue #123` task loads its title/body with `GITHUB_ISSUE` + `UNTRUSTED` labels. Native issue/PR reads and all tool observations have lower trust; an instruction embedded in them cannot approve actions or change tool policy.

On a normal Railway app the command sandbox remains disabled. Repository publishing consequently cannot satisfy the default validation requirement until a trusted external validator is available. Disabling `GIT_REQUIRE_VALIDATION` is an explicit operator override, used only in controlled Git fixtures, and weakens the production policy.

PR bodies generate the required Summary/Changes/Validation/Risks sections from the user summary, committed files and stored validation statuses. Approval cards include a downloadable diff against the recorded base, so committed changes remain visible at push approval. Stale-base failures offer explicit import of the current base for review.
