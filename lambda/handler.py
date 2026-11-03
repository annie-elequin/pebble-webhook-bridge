"""
AWS Lambda entrypoint for the webhook bridge.

Package with the repo-root bridge.py next to this file (see README.md).
Handler: handler.handler
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

# Allow importing bridge.py from the deployment package root or the repo root.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for path in (_HERE, _ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from bridge import handle_get, handle_post  # noqa: E402


def _headers_from_event(event: Dict[str, Any]) -> Dict[str, str]:
    headers = event.get("headers") or {}
    # API Gateway may also provide multiValueHeaders; prefer single headers map.
    return {str(k): str(v) for k, v in headers.items()}


def _path_from_event(event: Dict[str, Any]) -> str:
    # HTTP API (payload v2) uses rawPath; REST API uses path.
    return event.get("rawPath") or event.get("path") or "/"


def _method_from_event(event: Dict[str, Any]) -> str:
    if "requestContext" in event:
        http = event["requestContext"].get("http") or {}
        if "method" in http:
            return str(http["method"]).upper()
        if "httpMethod" in event["requestContext"]:
            return str(event["requestContext"]["httpMethod"]).upper()
    return str(event.get("httpMethod") or "GET").upper()


def _body_bytes_from_event(event: Dict[str, Any]) -> bytes:
    body = event.get("body")
    if body is None:
        return b""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    if isinstance(body, bytes):
        return body
    return str(body).encode("utf-8")


def _content_type(headers: Dict[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value
    return ""


def _response(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """API Gateway / Function URL Lambda handler."""
    method = _method_from_event(event)
    path = _path_from_event(event)
    headers = _headers_from_event(event)

    if method == "GET":
        status, body = handle_get(path)
        return _response(status, body)

    if method == "POST":
        status, body = handle_post(
            path,
            _content_type(headers),
            _body_bytes_from_event(event),
            headers,
        )
        return _response(status, body)

    return _response(405, {"error": "Method not allowed"})
