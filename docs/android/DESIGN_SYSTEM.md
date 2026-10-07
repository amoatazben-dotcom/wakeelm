# Design system

Compose Material 3, restrained teal primary and blue secondary, tonal surfaces, rounded message/code surfaces, and system/light/dark palettes. Native system sans typography includes Arabic shaping; title/body/label hierarchy uses Material typography. Material controls provide labeled fields, semantics, and standard minimum interactive sizes. All action labels and statuses use resources.

Single activity supports edge-to-edge with Scaffold insets and an IME-aware composer. Compact screens use bottom navigation; widths at least 840 dp use a navigation rail with a bounded workspace. Projects/tasks remain placeholders. Loading, offline cache, empty, error, provider checking, generation, fallback and cancellation states are explicit.

Markdown uses native text/selection, bounded table cells with horizontal scrolling, and horizontal-scroll monospace fenced code forced LTR under either locale. Supported blocks: headings, ordered/unordered list text, fenced code, safe tables. Inline spans: bold, italic, inline code, HTTPS/HTTP links. Assistant HTML is plain text; there is no WebView or arbitrary HTML execution. Syntax colors and richer Markdown nesting are future polish, not claimed here.
