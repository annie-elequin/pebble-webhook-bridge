#!/usr/bin/env python3
"""
Webhook Bridge - Translates form-encoded and plain text webhooks to JSON
"""
import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class WebhookBridgeHandler(BaseHTTPRequestHandler):
    def _send_response(self, status, body, content_type="application/json"):
        """Send HTTP response"""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        if isinstance(body, dict):
            body = json.dumps(body)
        self.wfile.write(body.encode('utf-8'))

    def _check_auth(self):
        """Verify incoming request authentication if SHARED_SECRET is set"""
        shared_secret = os.environ.get('SHARED_SECRET')
        if not shared_secret:
            return True
        
        # Check X-Bridge-Token header
        bridge_token = self.headers.get('X-Bridge-Token')
        if bridge_token == shared_secret:
            return True
        
        # Check Authorization Bearer
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            if token == shared_secret:
                return True
        
        return False

    def _parse_body(self, content_type, body_bytes):
        """Parse incoming body based on content type"""
        body = body_bytes.decode('utf-8')
        
        if content_type.startswith('application/json'):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"text": body}
        
        elif content_type.startswith('application/x-www-form-urlencoded'):
            parsed = parse_qs(body, keep_blank_values=True)
            # Convert lists to single values for simplicity
            return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
        
        elif content_type.startswith('text/plain'):
            # Try to parse as JSON first
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"text": body}
        
        else:
            raise ValueError(f"Unsupported content type: {content_type}")

    def _forward_to_upstream(self, payload):
        """Forward JSON payload to upstream webhook"""
        upstream_url = os.environ.get('UPSTREAM_URL')
        if not upstream_url:
            return 500, {"error": "UPSTREAM_URL not configured"}
        
        # Prepare headers
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'webhook-bridge/1.0'
        }
        
        # Add authentication if configured
        upstream_auth_header = os.environ.get('UPSTREAM_AUTH_HEADER')
        upstream_bearer = os.environ.get('UPSTREAM_BEARER')
        
        if upstream_auth_header:
            headers['Authorization'] = upstream_auth_header
        elif upstream_bearer:
            headers['Authorization'] = f'Bearer {upstream_bearer}'
        
        # Create and send request
        json_data = json.dumps(payload).encode('utf-8')
        req = Request(upstream_url, data=json_data, headers=headers, method='POST')
        
        try:
            with urlopen(req, timeout=10) as response:
                response_body = response.read().decode('utf-8')
                return response.status, {"status": response.status, "response": response_body}
        except HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else str(e)
            return e.code, {"status": e.code, "error": error_body}
        except URLError as e:
            return 502, {"error": f"Upstream connection failed: {str(e.reason)}"}
        except Exception as e:
            return 500, {"error": f"Request failed: {str(e)}"}

    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/health':
            self._send_response(200, {"ok": True})
        else:
            self._send_response(404, {"error": "Not found"})

    def do_POST(self):
        """Handle POST requests"""
        # Only handle / and /hook paths
        if self.path not in ['/', '/hook']:
            self._send_response(404, {"error": "Not found"})
            return
        
        # Check authentication
        if not self._check_auth():
            self._send_response(401, {"error": "Unauthorized"})
            return
        
        # Get content type
        content_type = self.headers.get('Content-Type', '').lower()
        
        # Read body
        content_length = int(self.headers.get('Content-Length', 0))
        body_bytes = self.rfile.read(content_length)
        
        # Parse body
        try:
            payload = self._parse_body(content_type, body_bytes)
        except ValueError as e:
            self._send_response(415, {"error": str(e)})
            return
        except Exception as e:
            self._send_response(400, {"error": f"Failed to parse body: {str(e)}"})
            return
        
        # Forward to upstream
        status, response = self._forward_to_upstream(payload)
        self._send_response(status, response)

    def log_message(self, format, *args):
        """Log messages to stdout"""
        sys.stdout.write(f"{self.address_string()} - [{self.log_date_time_string()}] {format % args}\n")


def main():
    port = int(os.environ.get('PORT', 8080))
    upstream_url = os.environ.get('UPSTREAM_URL')
    
    print(f"Webhook Bridge starting on port {port}")
    print(f"Upstream URL: {upstream_url or 'NOT CONFIGURED'}")
    print(f"Auth required: {os.environ.get('SHARED_SECRET') is not None}")
    
    server = HTTPServer(('0.0.0.0', port), WebhookBridgeHandler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()
