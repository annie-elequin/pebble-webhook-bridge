#!/usr/bin/env python3
"""
Webhook Bridge — Docker / native HTTP server entrypoint.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from bridge import handle_get, handle_post


def _log(message: str) -> None:
    """Write to stderr so Docker/Portainer logs show up immediately."""
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


class WebhookBridgeHandler(BaseHTTPRequestHandler):
    def _send_response(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        if isinstance(body, dict):
            body = json.dumps(body)
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        status, body = handle_get(self.path)
        _log(f"{self.client_address[0]} GET {self.path} -> {status}")
        self._send_response(status, body)

    def do_POST(self):
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        headers = {k: v for k, v in self.headers.items()}
        status, body = handle_post(self.path, content_type, body_bytes, headers)
        ctype = content_type or "(missing)"
        detail = ""
        if isinstance(body, dict) and body.get("error"):
            detail = f" error={body['error']!r}"
        _log(
            f"{self.client_address[0]} POST {self.path} "
            f"content-type={ctype!r} bytes={len(body_bytes)} -> {status}{detail}"
        )
        self._send_response(status, body)

    def log_message(self, format, *args):
        # Prefer our explicit request lines; keep stdlib access log on stderr too.
        _log(f"{self.address_string()} - [{self.log_date_time_string()}] {format % args}")


def main():
    port = int(os.environ.get("PORT", 8080))
    upstream_url = os.environ.get("UPSTREAM_URL")
    openbot = bool(os.environ.get("OPENBOT_WEBHOOK_SECRET"))

    _log(f"Webhook Bridge starting on port {port}")
    _log(f"Upstream URL: {upstream_url or 'NOT CONFIGURED'}")
    _log(f"Auth required: {bool(os.environ.get('SHARED_SECRET'))}")
    _log(f"OpenBot signing: {openbot}")

    server = HTTPServer(("0.0.0.0", port), WebhookBridgeHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
