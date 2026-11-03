#!/usr/bin/env python3
"""
Webhook Bridge — Docker / native HTTP server entrypoint.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from bridge import handle_get, handle_post


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
        self._send_response(status, body)

    def do_POST(self):
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        headers = {k: v for k, v in self.headers.items()}
        status, body = handle_post(self.path, content_type, body_bytes, headers)
        self._send_response(status, body)

    def log_message(self, format, *args):
        sys.stdout.write(
            f"{self.address_string()} - [{self.log_date_time_string()}] {format % args}\n"
        )


def main():
    port = int(os.environ.get("PORT", 8080))
    upstream_url = os.environ.get("UPSTREAM_URL")

    print(f"Webhook Bridge starting on port {port}")
    print(f"Upstream URL: {upstream_url or 'NOT CONFIGURED'}")
    print(f"Auth required: {bool(os.environ.get('SHARED_SECRET'))}")

    server = HTTPServer(("0.0.0.0", port), WebhookBridgeHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
