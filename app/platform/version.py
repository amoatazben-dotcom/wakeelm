APP_VERSION = "0.8.0"
API_VERSION = "1"
AGENT_POLICY_VERSION = "policy-2"
ROUTING_POLICY_VERSION = "router-1"


def metadata(settings):
    return {
        "app_version": APP_VERSION,
        "api_version": API_VERSION,
        "agent_policy_version": AGENT_POLICY_VERSION,
        "routing_policy_version": ROUTING_POLICY_VERSION,
        "build_git_sha": settings.build_git_sha,
        "build_timestamp": settings.build_timestamp,
    }
