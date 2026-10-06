# Context engine

ContextEngine ranks filename, symbol and literal text matches plus known manifests/entrypoints. It fetches relevant structural chunks and provides path, line range, selection reason and retrieval method. It never includes the whole workspace by default. Chunks are encrypted at rest with the existing SecretManager.

The budget uses model context_length when available, a configurable safety margin, conservative multilingual UTF-8 byte estimates and explicit reservations for the request, recent conversation, instructions/tools/output. Context is trimmed to the budget and at most twelve items; truncation is marked. Token estimates are conservative approximations, not provider tokenizer counts.

Project Q&A uses the existing active provider/model. Uploaded context is explicitly untrusted and cannot grant permissions. Answers must be JSON containing answer/citations; citations are accepted only when they match retrieved paths. This verifies citation provenance, not the factual accuracy of arbitrary generated prose. Providers that return malformed JSON fail safely.

Optional semantic retrieval follows Chunker → EmbeddingProvider → VectorStore. The portable store persists validated finite JSON vectors and computes bounded cosine rankings scoped to the workspace. Embeddings are not required or requested automatically. A provider implementation can be injected programmatically; there is no paid embedding onboarding UI or pgvector dependency in this stage. The exact-search path works independently.
