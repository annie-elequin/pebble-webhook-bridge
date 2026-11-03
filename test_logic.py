#!/usr/bin/env python3
"""Quick smoke test of the webhook bridge logic"""
import json
import unittest
from unittest.mock import MagicMock, patch

from bridge import (
    UnsupportedContentType,
    check_auth,
    handle_get,
    handle_post,
    parse_body,
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
            {"UPSTREAM_URL": "https://example.com/hook", "SHARED_SECRET": ""},
            clear=False,
        ):
            # Ensure SHARED_SECRET does not force auth from a polluted env.
            import os

            os.environ.pop("SHARED_SECRET", None)
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


if __name__ == "__main__":
    unittest.main()
