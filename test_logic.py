#!/usr/bin/env python3
"""Quick smoke test of the webhook bridge logic"""
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from bridge import (
    UnsupportedContentType,
    build_openbot_envelope,
    check_auth,
    forward_to_upstream,
    handle_get,
    handle_post,
    parse_body,
    serialize_json_body,
    sign_openbot_request,
)


class ParseBodyTests(unittest.TestCase):
    def test_form_encoded(self):
        result = parse_body(
            "application/x-www-form-urlencoded",
            b"message=Hello&priority=high",
        )
        self.assertEqual(result, {"message": "Hello", "priority": "high"})

    def test_plain_text(self):
        result = parse_body("text/plain", b"Alert: System status changed")
        self.assertEqual(result, {"text": "Alert: System status changed"})

    def test_plain_text_json(self):
        result = parse_body("text/plain", b'{"event": "alert"}')
        self.assertEqual(result, {"event": "alert"})

    def test_json_passthrough(self):
        result = parse_body(
            "application/json",
            b'{"event": "alert", "level": "warning"}',
        )
        self.assertEqual(result, {"event": "alert", "level": "warning"})

    def test_json_with_charset(self):
        result = parse_body(
            "application/json; charset=utf-8",
            b'{"ok": true}',
        )
        self.assertEqual(result, {"ok": True})

    def test_multipart_form_data(self):
        boundary = "7c643b7d-c810-4d52-92c0-0f5614f1edb3"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="text"\r\n'
            f"\r\n"
            f"hello from pebble\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="title"\r\n'
            f"\r\n"
            f"ring note\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        result = parse_body(
            f"multipart/form-data; boundary={boundary}",
            body,
        )
        self.assertEqual(
            result,
            {"text": "hello from pebble", "title": "ring note"},
        )

    def test_multipart_with_file_field(self):
        boundary = "abc123"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="note"\r\n'
            f"\r\n"
            f"caption\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="a.txt"\r\n'
            f"Content-Type: text/plain\r\n"
            f"\r\n"
            f"file-bytes\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        result = parse_body(f"multipart/form-data; boundary={boundary}", body)
        self.assertEqual(result["note"], "caption")
        self.assertEqual(result["file"]["filename"], "a.txt")
        self.assertEqual(result["file"]["content"], "file-bytes")

    def test_unsupported(self):
        with self.assertRaises(UnsupportedContentType):
            parse_body("application/xml", b"<xml/>")


class AuthTests(unittest.TestCase):
    def test_no_secret_allows(self):
        self.assertTrue(check_auth({}, shared_secret=""))

    def test_bridge_token(self):
        self.assertTrue(
            check_auth({"X-Bridge-Token": "s3cret"}, shared_secret="s3cret")
        )

    def test_bearer(self):
        self.assertTrue(
            check_auth({"Authorization": "Bearer s3cret"}, shared_secret="s3cret")
        )

    def test_reject(self):
        self.assertFalse(
            check_auth({"Authorization": "Bearer wrong"}, shared_secret="s3cret")
        )


class OpenBotSigningTests(unittest.TestCase):
    def test_sign_matches_docs_formula(self):
        body = '{"type":"deployment.completed","data":{"environment":"production"}}'
        secret = "whsec_test_secret"
        ts, did, sig = sign_openbot_request(
            body,
            secret,
            timestamp="1700000000",
            delivery_id="abc-123",
        )
        expected = hmac.new(
            secret.encode("utf-8"),
            b"1700000000.abc-123." + body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(ts, "1700000000")
        self.assertEqual(did, "abc-123")
        self.assertEqual(sig, f"sha256={expected}")

    def test_envelope_wraps_payload(self):
        envelope = build_openbot_envelope(
            {"text": "hello ring"},
            event_type="pebble.transcription",
        )
        self.assertEqual(envelope["type"], "pebble.transcription")
        self.assertEqual(envelope["data"], {"text": "hello ring"})
        self.assertIn("occurredAt", envelope)

    def test_envelope_passthrough_existing(self):
        existing = {
            "type": "custom.event",
            "data": {"ok": True},
            "occurredAt": "2026-01-01T00:00:00.000Z",
        }
        self.assertEqual(build_openbot_envelope(existing), existing)

    def test_forward_adds_openbot_headers(self):
        fake_resp = MagicMock()
        fake_resp.status = 202
        fake_resp.read.return_value = b"accepted"
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.__exit__.return_value = False

        secret = "whsec_test_secret"
        with patch("bridge.urlopen", return_value=fake_resp) as mocked:
            status, body = forward_to_upstream(
                {"text": "from pebble"},
                upstream_url="https://example.com/openbot",
                openbot_secret=secret,
                openbot_event_type="pebble.transcription",
            )

        self.assertEqual(status, 202)
        self.assertEqual(body["status"], 202)
        req = mocked.call_args[0][0]
        sent = req.data.decode("utf-8")
        payload = json.loads(sent)
        self.assertEqual(payload["type"], "pebble.transcription")
        self.assertEqual(payload["data"], {"text": "from pebble"})

        ts = req.get_header("X-openbot-timestamp")
        did = req.get_header("X-openbot-delivery-id")
        sig = req.get_header("X-openbot-signature")
        self.assertTrue(ts and did and sig)
        # Signature must be over the exact body bytes we sent.
        expected = (
            "sha256="
            + hmac.new(
                secret.encode("utf-8"),
                f"{ts}.{did}.{sent}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        )
        self.assertEqual(sig, expected)
        self.assertIsNone(req.get_header("Authorization"))
        # Compact serialization (no spaces) matches serialize_json_body.
        self.assertEqual(sent, serialize_json_body(payload))


class HandleTests(unittest.TestCase):
    def test_health(self):
        status, body = handle_get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True})

    def test_post_unauthorized(self):
        with patch.dict("os.environ", {"SHARED_SECRET": "s3cret"}, clear=False):
            status, body = handle_post(
                "/hook",
                "text/plain",
                b"hi",
                {},
            )
            self.assertEqual(status, 401)

    def test_post_forwards(self):
        fake_resp = MagicMock()
        fake_resp.status = 200
        fake_resp.read.return_value = b'{"received": true}'
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.__exit__.return_value = False

        with patch.dict(
            "os.environ",
            {"UPSTREAM_URL": "https://example.com/hook"},
            clear=False,
        ):
            os.environ.pop("SHARED_SECRET", None)
            os.environ.pop("OPENBOT_WEBHOOK_SECRET", None)
            with patch("bridge.urlopen", return_value=fake_resp) as mocked:
                status, body = handle_post(
                    "/hook",
                    "application/x-www-form-urlencoded",
                    b"text=hello+from+index",
                    {},
                )
                self.assertEqual(status, 200)
                self.assertEqual(body["status"], 200)
                req = mocked.call_args[0][0]
                self.assertEqual(req.get_header("Content-type"), "application/json")
                self.assertEqual(
                    json.loads(req.data.decode("utf-8")),
                    {"text": "hello from index"},
                )
                self.assertIsNone(req.get_header("X-openbot-signature"))


if __name__ == "__main__":
    unittest.main()
