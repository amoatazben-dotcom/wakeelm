# Tool registry and policy

All tool names are an explicit allowlist. Pydantic input schemas reject extra fields; file paths use the descriptor-based storage boundary. Execution verifies job, workspace and user ownership, mode, cancellation, tool-count budget, approval binding and a timeout. Outputs are bounded before entering model observations. Persistent logs contain redacted summaries only. A model cannot grant approval, change modes, provide arbitrary argv/shell, select a host path, deploy, push Git, access MCP or run host administration.

| Tool | Input | Modes | Risk/approval |
| --- | --- | --- | --- |
| workspace.list_files | empty | all | low |
| workspace.read_file | relative path, line range | all | low; max 400 lines/24 KB |
| workspace.file_info | relative path | all | low |
| project.search_text | literal query, optional glob, max_results | all | low; max 100 |
| project.search_files | query, max_results | all | low |
| project.search_symbols | query, max_results | all | low |
| project.get_manifest | empty | all | low |
| workspace.propose_patch | bounded edits with expected SHA256 | SUGGEST/WORKSPACE | medium; encrypted proposal, no writes |
| workspace.apply_patch | change_set_id | WORKSPACE | approval for deletion, >3 files, >200 changed lines or REQUIRE_EDIT_APPROVAL |
| workspace.restore_file | change_set_id | WORKSPACE | high; approval |
| project.diff | change_set_id | all | low; owned encrypted diff |
| validation.detect_commands | empty | all | low |
| validation.run | detected command_id only | WORKSPACE | high; always approval |
| agent.request_approval | known tool_name + schema-valid arguments | WORKSPACE | explicit approval wrapper; executes the exact bound action after approval |

`$last_patch` is resolved from the owned job's last proposal immediately before execution. An approval binds the resolved arguments, not a model-supplied assertion. Unknown/critical actions have no registry entry and are denied. READ_ONLY cannot propose, modify or run commands; SUGGEST cannot apply, restore or execute commands.

Patch kinds: exact single-occurrence replacement, validated line range, exact-context single-file unified diff, justified full replacement, new file, deletion. Every existing file requires its current SHA256. No wildcard patch application, fuzzy search/replace, shell redirects or binary rewrites. New-file absence checks reject symlink parents. A batch checks all hashes before writing, commits encrypted snapshots/APPLYING first, then atomically replaces each file and reindexes. Errors restore all originals; persistent snapshots cover process crashes. Rollback refuses files changed after application. Source uploads/extracted originals are kept separate from working edits.

Users can explicitly apply a completed SUGGEST diff; this switches that owned job to WORKSPACE and queues an apply step. Sensitive/configured edits still pause for a bound approval. User rollback is a separate two-click action on an exact change set, checks ownership/idle workspace/hashes and records an audit.

Stages 5/6 extend ToolRegistry through the shared ToolPolicyEngine and MCPToolAdapter. Only enabled/reviewed/relevant MCP tools are hydrated. Raw git/shell flags, force/merge/deploy/admin/secrets APIs and GitHub MCP write paths are absent. Native high-risk writes and reviewed MCP mutations use persisted exact approvals; service methods additionally reject missing approval. See GIT_SECURITY.md and MCP_SECURITY.md for the full policy.
