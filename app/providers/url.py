import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from app.core.exceptions import SafeError


class BaseURLResolver:
    @staticmethod
    def normalize(value):
        try:
            parsed = urlsplit(value.strip())
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.port not in {None, 80, 443}
            ):
                raise ValueError()
            if any(c.isspace() for c in value) or "\\" in value or "%" in parsed.netloc:
                raise ValueError()
            path = parsed.path.rstrip("/")
            if any(part in {".", ".."} for part in path.split("/")):
                raise ValueError()
            return urlunsplit((parsed.scheme, parsed.netloc.lower(), path, "", ""))
        except ValueError:
            raise SafeError("INVALID_URL") from None

    @staticmethod
    def discovery_paths(base):
        return (
            [base + "/models"] if base.endswith("/v1") else [base + "/models", base + "/v1/models"]
        )


async def public_addresses(url):
    host = urlsplit(BaseURLResolver.normalize(url)).hostname
    if host == "localhost" or host.endswith(
        (".localhost", ".local", ".internal", ".railway.internal")
    ):
        raise SafeError("INVALID_URL")
    try:
        results = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM), 5
        )
        addresses = {r[4][0] for r in results}
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise SafeError("INVALID_URL")
        return addresses
    except (OSError, TimeoutError):
        raise SafeError("OFFLINE") from None
