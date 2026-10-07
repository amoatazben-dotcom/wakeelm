# Scoped encrypted memory

`memory_items` has separate CONVERSATION, PROJECT, PREFERENCE, TASK, EXECUTION and KNOWLEDGE layers. Every row belongs to a user and, where applicable, an owned workspace/job. Cross-user, wrong-workspace and wrong-job references fail before reading or writing. Content is encrypted; clear search terms are not stored. Deduplication uses a scoped digest and a unique constraint.

Conversation capture retains at most twelve rows and progressively compacts older history with explicitly labelled extractive snippets. It does not invent verified decisions. Project/knowledge retrieval is integrated into ContextEngine and recent relevant conversation/preferences into chat. Task goals and completed policy-controlled steps are recorded separately. Existing encrypted plan, step, approval and change-set state remains the source of safe restart behavior.

MemoryCandidate validates layer, scope, provenance and confidence. Model-inferred permanent memory needs explicit approval and is capped at 0.5 confidence. Provider, GitHub and MCP credentials are rejected, including known opaque secret values. No model-facing tool writes permanent memory directly. Uploaded project documents retain exact indexed chunks; optional reusable knowledge can be admitted through validated candidates.

Retrieval uses exact ownership filters, expiry, bounded recent candidates, lexical relevance, recency and confidence. Every result retains source type/ID/path or URI, timestamp, trust and retrieval method. Memory always enters prompts as untrusted context, never SYSTEM_POLICY. Optional semantic indexing degrades to exact search.

ContextCompressor removes duplicates and selects bounded sections; exact edit context is never summarized. Existing iterative search, symbol indexes and hash-bound reads avoid sending a whole repository. Retention sweeps expire memories; account deletion clears memory and credentials and preserves minimal audit tombstones.
