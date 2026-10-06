# Files and workspaces

Uploads are documents in private Telegram chats. Each workspace belongs to one database user and uses an opaque UUID under WORKSPACE_STORAGE_ROOT/<user-id>/<uuid>/{source,extracted,working,metadata}. Source is retained; working files are edited separately. Usernames and database root_path values never determine access paths.

Storage is an explicit protocol with a local-filesystem implementation. A persistent volume will be required before Railway deployment; local storage requires one storage-owning instance or a genuinely shared filesystem. An object-storage implementation is deferred. No Railway deployment is performed during staged construction.

Supported text/data/code extensions include the Stage 3 list, common build manifests and ignore files. Unknown binary uploads are retained but excluded from text context. ZIP, TAR, TAR.GZ, TGZ and meaningful single-file GZ uploads are supported. Nested archives are rejected. ZIP symlinks and TAR symlinks/hardlinks/devices are rejected, as are absolute paths, dot segments, backslashes, drive paths, duplicate members and encrypted archives. Limits apply before upload, per member, by total extracted bytes and by file count. Ordinary filenames may not contain control characters.

Text decoding prefers strict UTF-8, then BOM-marked UTF-16, then a conservative charset-normalizer confidence check. Ingestion never rewrites source bytes. PDF extraction is text-only, DOCX reads document XML with defusedxml, and XLSX reads cells/formulas as data without evaluating them or following external links. No OCR or macro execution is provided. Malformed parser results become unknown/binary without preventing unrelated files from being indexed. Parsing uses bounded input but is not a container security boundary.

Telegram provides upload/list/delete confirmation, workspace information, paginated directory-first browsing, file viewing/download and search. Navigation handles are scoped to the user's expiring Redis FSM. Each file lookup also verifies workspace ownership in SQL.
