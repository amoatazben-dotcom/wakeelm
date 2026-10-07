import hashlib
import json
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from app.core.exceptions import SafeError

CRITICAL = re.compile(
    r"(?i)(?:\bshell\b|\bssh\b|terminal|docker.?exec|kubectl.?exec|kubernetes.?exec|production.?deploy|deploy.?production|\bsecrets?\b|password|credentials?|billing|privilege|administrat|delete.?account|destructive|\bdrop\b|\btruncate\b)"
)
DATABASE_WRITES = re.compile(
    r"(?i)\b(?:DROP|TRUNCATE|ALTER|DELETE|UPDATE|INSERT|MERGE|GRANT|REVOKE|CALL|EXECUTE|COPY|VACUUM|DO)\b"
)


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def check_schema(schema):
    if not isinstance(schema, dict) or len(json.dumps(schema).encode()) > 64000:
        raise SafeError("INVALID_SCHEMA")

    def visit(node, depth=0):
        if depth > 20:
            raise SafeError("INVALID_SCHEMA")
        if isinstance(node, dict):
            if any(key in node for key in ("$ref", "$dynamicRef", "pattern", "patternProperties")):
                raise SafeError("INVALID_SCHEMA")
            for value in node.values():
                visit(value, depth + 1)
        elif isinstance(node, list):
            if len(node) > 100:
                raise SafeError("INVALID_SCHEMA")
            for value in node:
                visit(value, depth + 1)

    visit(schema)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        raise SafeError("INVALID_SCHEMA") from None
    return schema


def validate_arguments(schema, arguments):
    check_schema(schema)
    if not isinstance(arguments, dict) or len(json.dumps(arguments).encode()) > 32000:
        raise SafeError("INVALID_TOOL_ARGUMENTS")
    try:
        Draft202012Validator(schema).validate(arguments)
    except (ValidationError, RecursionError):
        raise SafeError("INVALID_TOOL_ARGUMENTS") from None


class MCPRiskPolicy:
    def __init__(self, settings):
        self.settings = settings

    def classify(self, server, tool):
        text = " ".join(
            [
                tool.get("name", ""),
                tool.get("description", ""),
                json.dumps(tool.get("inputSchema", {})),
            ]
        )
        if CRITICAL.search(text.replace("_", " ").replace("-", " ")):
            return {
                "risk": "CRITICAL",
                "reviewed": False,
                "approval": True,
                "capability": "EXECUTE",
            }
        identity = server.server_url + "#" + tool["name"]
        value = self.settings.mcp_tool_policies.get(identity)
        expected = fingerprint(
            {
                "schema": tool.get("inputSchema", {}),
                "description": tool.get("description", ""),
                "output": tool.get("outputSchema"),
            }
        )
        if not isinstance(value, dict) or value.get("fingerprint") != expected:
            return {"risk": "HIGH", "reviewed": False, "approval": True, "capability": "UNKNOWN"}
        capability = value.get("capability")
        if (
            capability not in {"READ", "SEARCH", "CREATE", "UPDATE", "SEND"}
            or value.get("integration") == "github"
            and capability not in {"READ", "SEARCH"}
            or value.get("integration") in {"railway", "vercel", "cloudflare"}
            and capability not in {"READ", "SEARCH"}
            or value.get("integration") == "database"
            and capability not in {"READ", "SEARCH"}
        ):
            return {
                "risk": "CRITICAL",
                "reviewed": False,
                "approval": True,
                "capability": capability,
            }
        risk = "LOW" if capability in {"READ", "SEARCH"} else "HIGH"
        return {
            "risk": risk,
            "reviewed": True,
            "approval": risk != "LOW",
            "capability": capability,
            "required_scopes": value.get("required_scopes", []),
            "integration": value.get("integration", "generic"),
            "fingerprint": expected,
        }

    def enforce(self, tool, arguments, mode):
        if (
            not tool.is_enabled
            or not tool.metadata_json.get("reviewed")
            or tool.risk_level == "CRITICAL"
        ):
            raise SafeError("TOOL_DISABLED")
        if mode != "WORKSPACE" and tool.risk_level != "LOW":
            raise SafeError("POLICY_DENIED")
        validate_arguments(tool.input_schema_json, arguments)
        # Arbitrary SQL is blocked in this stage; known, schema-reviewed structured read tools are supported.
        if tool.metadata_json.get("integration") == "database":
            text = json.dumps(arguments)
            if DATABASE_WRITES.search(text) or any(
                key.lower() in {"sql", "query", "command"} for key in arguments
            ):
                raise SafeError("DATABASE_WRITE_DENIED")
