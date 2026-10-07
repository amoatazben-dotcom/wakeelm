from dataclasses import dataclass

CAPABILITIES = {
    "READ",
    "SEARCH",
    "CREATE",
    "UPDATE",
    "DELETE",
    "SEND",
    "EXECUTE",
    "DEPLOY",
    "ADMIN",
    "SECRETS",
}


@dataclass(frozen=True)
class IntegrationProfile:
    name: str
    backend: str
    permitted: frozenset
    implemented: bool = False


class IntegrationRegistry:
    def __init__(self):
        self.profiles = {
            name: IntegrationProfile(
                name,
                "native" if name == "GitHub" else "MCP",
                frozenset(
                    {"READ", "SEARCH"}
                    if name in {"GitHub MCP", "Supabase", "Railway", "Cloudflare", "Vercel"}
                    else {"READ", "SEARCH", "CREATE", "UPDATE", "SEND"}
                ),
                name == "GitHub",
            )
            for name in (
                "GitHub",
                "GitHub MCP",
                "Supabase",
                "Google Drive",
                "Gmail",
                "Google Calendar",
                "Slack",
                "Notion",
                "Linear",
                "Jira",
                "Railway",
                "Cloudflare",
                "Vercel",
            )
        }
        self.profiles["GitHub"] = IntegrationProfile(
            "GitHub", "native", frozenset({"READ", "SEARCH", "CREATE", "UPDATE"}), True
        )

    def describe(self):
        return "\n".join(
            profile.name + " · " + profile.backend + " · " + ", ".join(sorted(profile.permitted))
            for profile in self.profiles.values()
        )
