"""
Shared webhook bridge logic — used by the Docker HTTP server and AWS Lambda.
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping, MutableMapping, Optional, Tuple, Union
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import Request, urlopen

Headers = Mapping[str, str]
JsonDict = MutableMapping[str, Any]
ResponseBody = Union[JsonDict, str]


class UnsupportedContentType(ValueError):
    """Raised when the request Content-Type is not supported."""


def check_auth(headers: Headers, shared_secret: Optional[str] = None) -> bool:
    """Return True if the request is allowed.

    When SHARED_SECRET is unset, all requests are allowed.
    Otherwise require X-Bridge-Token or Authorization: Bearer to match.
    """
    secret = shared_secret if shared_secret is not None else os.environ.get("SHARED_SECRET")
    if not secret:
        return True

    # Header lookup is case-insensitive for HTTP, but Lambda events may be mixed.
    lowered = {k.lower(): v for k, v in headers.items()}

    bridge_token = lowered.get("x-bridge-token")
    if bridge_token == secret:
        return True

    auth_header = lowered.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == secret:
            return True

    return False


def parse_body(content_type: str, body_bytes: bytes) -> JsonDict:
    """Parse an incoming body into a JSON-serializable dict (pass-through fields)."""
    body = body_bytes.decode("utf-8")
    content_type = (content_type or "").lower().split(";")[0].strip()

    if content_type == "application/json" or content_type.endswith("+json"):
        try:
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except json.JSONDecodeError:
            return {"text": body}

    if content_type == "application/x-www-form-urlencoded":
        parsed = parse_qs(body, keep_blank_values=True)
        return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

    if content_type == "text/plain" or content_type == "":
        # Empty content-type: try JSON, else wrap as text (common for simple clients).
        try:
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except json.JSONDecodeError:
            return {"text": body}

    raise UnsupportedContentType(f"Unsupported content type: {content_type or '(missing)'}")


def parse_upstream_headers(raw: Optional[str] = None) -> dict[str, str]:
    """Parse UPSTREAM_HEADERS JSON object into a string header map.

    Example: {"X-Custom":"abc","X-OpenBot-Key":"…"}
    Empty / unset → no extra headers.
    """
    value = raw if raw is not None else os.environ.get("UPSTREAM_HEADERS", "")
    if value is None or not str(value).strip():
        return {}

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"UPSTREAM_HEADERS must be a JSON object: {e}") from e

    if not isinstance(parsed, dict):
        raise ValueError("UPSTREAM_HEADERS must be a JSON object of string keys to string values")

    headers: dict[str, str] = {}
    for key, val in parsed.items():
        if val is None:
            continue
        headers[str(key)] = val if isinstance(val, str) else json.dumps(val)
    return headers


def forward_to_upstream(
    payload: JsonDict,
    *,
    upstream_url: Optional[str] = None,
    upstream_bearer: Optional[str] = None,
    upstream_auth_header: Optional[str] = None,
    upstream_headers: Optional[Mapping[str, str]] = None,
    timeout: float = 10.0,
) -> Tuple[int, JsonDict]:
    """POST payload as application/json to UPSTREAM_URL."""
    url = upstream_url if upstream_url is not None else os.environ.get("UPSTREAM_URL")
    if not url:
        return 500, {"error": "UPSTREAM_URL not configured"}

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "webhook-bridge/1.0",
    }

    try:
        extra = (
            dict(upstream_headers)
            if upstream_headers is not None
            else parse_upstream_headers()
        )
    except ValueError as e:
        return 500, {"error": str(e)}

    # Extra headers apply next; dedicated auth env vars still win for Authorization.
    headers.update(extra)

    auth_header = (
        upstream_auth_header
        if upstream_auth_header is not None
        else os.environ.get("UPSTREAM_AUTH_HEADER")
    )
    bearer = (
        upstream_bearer if upstream_bearer is not None else os.environ.get("UPSTREAM_BEARER")
    )

    if auth_header:
        headers["Authorization"] = auth_header
    elif bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    json_data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=json_data, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            return response.status, {"status": response.status, "response": response_body}
    except HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        return e.code, {"status": e.code, "error": error_body}
    except URLError as e:
        return 502, {"error": f"Upstream connection failed: {str(e.reason)}"}
    except Exception as e:
        return 500, {"error": f"Request failed: {str(e)}"}


def handle_post(
    path: str,
    content_type: str,
    body_bytes: bytes,
    headers: Headers,
) -> Tuple[int, JsonDict]:
    """Process a POST to / or /hook. Returns (status_code, response_body)."""
    normalized = path.split("?")[0].rstrip("/") or "/"
    if normalized not in ("/", "/hook"):
        return 404, {"error": "Not found"}

    if not check_auth(headers):
        return 401, {"error": "Unauthorized"}

    try:
        payload = parse_body(content_type, body_bytes)
    except UnsupportedContentType as e:
        return 415, {"error": str(e)}
    except Exception as e:
        return 400, {"error": f"Failed to parse body: {str(e)}"}

    return forward_to_upstream(payload)


def handle_get(path: str) -> Tuple[int, JsonDict]:
    """Process a GET. Only /health is supported."""
    normalized = path.split("?")[0].rstrip("/") or "/"
    if normalized == "/health":
        return 200, {"ok": True}
    return 404, {"error": "Not found"}
