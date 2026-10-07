import re


class ToolRouter:
    """Routing limits schema exposure; it never grants permissions."""

    KEYWORDS = {
        "calendar": {"calendar", "meeting", "appointment", "اجتماع", "موعد", "تقويم"},
        "database": {"database", "schema", "table", "sql", "قاعدة", "جداول"},
        "github": {"github", "issue", "pull", "repository", "مستودع", "فرع"},
        "drive": {"drive", "document", "file", "مستند"},
        "slack": {"slack", "message", "رسالة"},
    }

    def relevant(self, request, server, tool, selected_servers=None):
        if selected_servers is not None:
            return server.id in selected_servers
        words = set(re.findall(r"[\w-]+", request.casefold()))
        keywords = self.KEYWORDS.get(tool.metadata_json.get("integration"), set())
        name_words = set(re.findall(r"[\w-]+", server.name.casefold()))
        return bool(words & (keywords | name_words))
