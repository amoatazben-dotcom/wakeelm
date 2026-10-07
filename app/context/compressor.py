from app.core.exceptions import SafeError
from app.indexing.chunker import token_estimate


class ContextCompressor:
    """Drops duplicates, selects sections; exact edit context is never summarized."""

    def compress(self, items, max_tokens, exact_edit=False):
        selected, seen, used = [], set(), 0
        for item in items:
            text = item["text"]
            key = (item.get("path"), text)
            if key in seen:
                continue
            seen.add(key)
            size = token_estimate(text)
            if used + size > max_tokens:
                if exact_edit:
                    continue
                room = max_tokens - used - 30
                if room < 32:
                    continue
                text = text[:room] + "\n[TRUNCATED_UNTRUSTED_CONTEXT]"
                size = token_estimate(text)
            if used + size <= max_tokens:
                selected.append({**item, "text": text, "compressed": text != item["text"]})
                used += size
        if exact_edit and not selected and items:
            raise SafeError("CONTEXT_TOO_LARGE")
        return selected
