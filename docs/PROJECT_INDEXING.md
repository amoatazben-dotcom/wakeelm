# Project indexing

Seven additional tables store workspaces, file manifests, project manifests, symbols, encrypted chunks, optional vectors and workspace events. SHA-256 identifies exact content and prevents repeated parsing of identical content with the same extension within one ingestion; paths remain distinct for provenance.

Generated directories and root .gitignore/.dockerignore patterns exclude files from context, not from stored uploads. Python AST extracts classes, functions, methods, test functions, imports and constants with line ranges. Other supported languages have text/language indexing; Tree-sitter and non-Python structural parsing are deferred. Parse failures fall back to text.

ProjectScanner uses manifest filenames and parsed dependency metadata as evidence for Python/Node/Android/Flutter/Rust/Go/Java build systems, frameworks, tests, databases, containers and CI. It does not claim technologies merely from directory names. Evidence paths are stored in the normalized project manifest.

Search supports literal case-insensitive text, optional file globs, path/filename search and extracted symbol search. There is no shell search endpoint. Results are bounded and exclude ignored/binary files by default. Re-indexing replaces old records through database cascades and creates a fresh manifest.
