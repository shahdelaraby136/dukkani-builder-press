import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("Dukani Marketing")


def api_request(path, method="GET", payload=None):
    base_url = os.environ.get("DUKANI_API_BASE_URL", "").rstrip("/")
    token = os.environ.get("DUKANI_API_TOKEN", "")
    if not base_url or not token:
        raise RuntimeError("DUKANI_API_BASE_URL and DUKANI_API_TOKEN are required")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}/{path.lstrip('/')}",
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError("Dukani API request failed") from error


@mcp.tool()
def get_store_context() -> dict:
    """Return the authenticated tenant context without exposing credentials."""
    return api_request("api/method/dukkani_marketing.api.get_current_tenant")


@mcp.tool()
def list_content_drafts(limit: int = 50) -> list:
    """List draft marketing content for the authenticated tenant."""
    safe_limit = min(max(int(limit), 1), 100)
    result = api_request(
        "api/method/dukkani_marketing.api.list_content_drafts",
        method="POST",
        payload={"limit": safe_limit},
    )
    return result.get("message", result)


@mcp.tool()
def create_content_draft(title: str, body: str, channel: str = "internal") -> dict:
    """Create a draft for review; this tool never publishes externally."""
    result = api_request(
        "api/method/dukkani_marketing.api.create_content_draft",
        method="POST",
        payload={"title": title, "body": body, "channel": channel},
    )
    return result.get("message", result)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
