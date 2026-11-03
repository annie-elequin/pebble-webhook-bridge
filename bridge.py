"""
Shared webhook bridge logic — used by the Docker HTTP server and AWS Lambda.
"""
from __future__ import annotations

import base64
import email
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from email import policy
from typing import Any, Mapping, MutableMapping, Optional, Tuple, Union
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import Request, urlopen

Headers = Mapping[str, str]
JsonDict = MutableMapping[str, Any]
ResponseBody = Union[JsonDict, str]

# OpenBot delivery IDs: 1–256 ASCII letters/digits/._:- ; first char letter or digit.
_DELIVERY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,255}$")

# Compact JSON so the signed bytes match the bytes we POST (serialize once).
_JSON_SEPARATORS = (",", ":")


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


def _store_form_value(result: JsonDict, name: str, value: Any) -> None:
    """Accumulate form fields; repeated names become a list."""
    if name in result:
        existing = result[name]
        if isinstance(existing, list):
            existing.append(value)
        else:
            result[name] = [existing, value]
    else:
        result[name] = value


def parse_multipart(content_type_header: str, body_bytes: bytes) -> JsonDict:
    """Parse multipart/form-data (what Pebble / Index 01 often sends) into a JSON object.

    Text fields become string values. File parts become
    ``{"filename": "...", "content_type": "...", "content": "..."}`` when UTF-8
    decodable, otherwise ``base64`` instead of ``content``.
    """
    preamble = f"Content-Type: {content_type_header}\r\nMIME-Version: 1.0\r\n\r\n".encode(
        "utf-8"
    )
    msg = email.message_from_bytes(preamble + body_bytes, policy=policy.default)
    if not msg.is_multipart():
        raise ValueError("multipart/form-data body was not multipart")

    result: JsonDict = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        name = str(name)

        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        if payload is None:
            content = part.get_content()
            value: Any = content if isinstance(content, str) else str(content)
        else:
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset)
                if filename:
                    value = {
                        "filename": filename,
                        "content_type": part.get_content_type(),
                        "content": text,
                    }
                else:
                    value = text
            except UnicodeDecodeError:
                value = {
                    "filename": filename,
                    "content_type": part.get_content_type(),
                    "base64": base64.b64encode(payload).decode("ascii"),
                }

        _store_form_value(result, name, value)

    return result


def parse_body(content_type: str, body_bytes: bytes) -> JsonDict:
    """Parse an incoming body into a JSON-serializable dict (pass-through fields)."""
    raw_content_type = content_type or ""
    media_type = raw_content_type.lower().split(";")[0].strip()

    if media_type == "multipart/form-data":
        # Keep the full header (includes boundary=…).
        return parse_multipart(raw_content_type, body_bytes)

    body = body_bytes.decode("utf-8")

    if media_type == "application/json" or media_type.endswith("+json"):
        try:
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except json.JSONDecodeError:
            return {"text": body}

    if media_type == "application/x-www-form-urlencoded":
        parsed = parse_qs(body, keep_blank_values=True)
        return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

    if media_type == "text/plain" or media_type == "":
        # Empty content-type: try JSON, else wrap as text (common for simple clients).
        try:
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except json.JSONDecodeError:
            return {"text": body}

    raise UnsupportedContentType(f"Unsupported content type: {media_type or '(missing)'}")


def openbot_mode_enabled(secret: Optional[str] = None) -> bool:
    value = secret if secret is not None else os.environ.get("OPENBOT_WEBHOOK_SECRET")
    return bool(value and str(value).strip())


def build_openbot_envelope(
    payload: JsonDict,
    *,
    event_type: Optional[str] = None,
) -> JsonDict:
    """Wrap converted client payload in OpenBot's required webhook event shape.

    See https://github.com/nightly-labs/openbot/blob/main/docs/webhooks.md
    """
    type_value = (
        event_type
        if event_type is not None
        else os.environ.get("OPENBOT_EVENT_TYPE", "pebble.transcription")
    )
    type_value = (type_value or "").strip()
    if not type_value or len(type_value) > 256:
        raise ValueError("OPENBOT_EVENT_TYPE must be 1–256 characters")

    # If the client already sent a valid OpenBot envelope, keep it (pass-through).
    if (
        isinstance(payload, dict)
        and isinstance(payload.get("type"), str)
        and 1 <= len(payload["type"]) <= 256
        and ("data" in payload or "occurredAt" in payload)
    ):
        return payload

    return {
        "type": type_value,
        "occurredAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "data": payload,
    }


def make_openbot_delivery_id() -> str:
    """Generate a delivery ID that satisfies OpenBot's charset rules."""
    delivery_id = str(uuid.uuid4())
    if not _DELIVERY_ID_RE.match(delivery_id):
        # Extremely unlikely with UUID4; fall back to a safe prefix.
        delivery_id = "d" + uuid.uuid4().hex
    return delivery_id


def sign_openbot_request(
    body_text: str,
    secret: str,
    *,
    timestamp: Optional[str] = None,
    delivery_id: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Return (timestamp, delivery_id, signature_header_value).

    Signed bytes: ``{timestamp}.{deliveryId}.{body}`` (exact body string).
    Signature header: ``sha256=`` + lowercase hex HMAC-SHA256.
    """
    ts = timestamp if timestamp is not None else str(int(time.time()))
    did = delivery_id if delivery_id is not None else make_openbot_delivery_id()
    if not _DELIVERY_ID_RE.match(did):
        raise ValueError("OpenBot delivery id has an invalid format")

    digest = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.{did}.{body_text}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return ts, did, f"sha256={digest}"


def serialize_json_body(payload: JsonDict) -> str:
    """Serialize once — these exact bytes are both signed and POSTed."""
    return json.dumps(payload, separators=_JSON_SEPARATORS, ensure_ascii=False)


def forward_to_upstream(
    payload: JsonDict,
    *,
    upstream_url: Optional[str] = None,
    upstream_bearer: Optional[str] = None,
    upstream_auth_header: Optional[str] = None,
    openbot_secret: Optional[str] = None,
    openbot_event_type: Optional[str] = None,
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

    secret = (
        openbot_secret
        if openbot_secret is not None
        else os.environ.get("OPENBOT_WEBHOOK_SECRET")
    )

    if openbot_mode_enabled(secret):
        assert secret is not None
        try:
            envelope = build_openbot_envelope(payload, event_type=openbot_event_type)
            body_text = serialize_json_body(envelope)
            # OpenBot hard limit: 64 KiB UTF-8 body.
            body_bytes = body_text.encode("utf-8")
            if len(body_bytes) > 64 * 1024:
                return 413, {"error": "OpenBot webhook body exceeds 64 KiB"}
            ts, delivery_id, signature = sign_openbot_request(body_text, secret)
        except ValueError as e:
            return 500, {"error": str(e)}

        headers["X-OpenBot-Timestamp"] = ts
        headers["X-OpenBot-Delivery-Id"] = delivery_id
        headers["X-OpenBot-Signature"] = signature
        json_data = body_bytes
    else:
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

        json_data = serialize_json_body(payload).encode("utf-8")

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
