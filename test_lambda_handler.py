#!/usr/bin/env python3
"""Smoke tests for the Lambda adapter (no AWS required)."""
import base64
import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load_handler_module():
    path = Path(__file__).resolve().parent / "lambda" / "handler.py"
    spec = importlib.util.spec_from_file_location("webhook_bridge_lambda_handler", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


handler_mod = _load_handler_module()


class LambdaHandlerTests(unittest.TestCase):
    def test_health(self):
        result = handler_mod.handler(
            {
                "rawPath": "/health",
                "requestContext": {"http": {"method": "GET"}},
                "headers": {},
            },
            None,
        )
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"]), {"ok": True})

    def test_post_form_forwards(self):
        fake_resp = MagicMock()
        fake_resp.status = 201
        fake_resp.read.return_value = b"ok"
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.__exit__.return_value = False

        os.environ["UPSTREAM_URL"] = "https://example.com/dest"
        os.environ.pop("SHARED_SECRET", None)
        os.environ.pop("OPENBOT_WEBHOOK_SECRET", None)

        with patch("bridge.urlopen", return_value=fake_resp):
            result = handler_mod.handler(
                {
                    "rawPath": "/hook",
                    "requestContext": {"http": {"method": "POST"}},
                    "headers": {"content-type": "application/x-www-form-urlencoded"},
                    "body": "text=hello+ring",
                    "isBase64Encoded": False,
                },
                None,
            )

        self.assertEqual(result["statusCode"], 201)
        body = json.loads(result["body"])
        self.assertEqual(body["status"], 201)

    def test_base64_body(self):
        os.environ.pop("SHARED_SECRET", None)
        os.environ["UPSTREAM_URL"] = "https://example.com/dest"

        fake_resp = MagicMock()
        fake_resp.status = 200
        fake_resp.read.return_value = b"{}"
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.__exit__.return_value = False

        raw = b'{"note":"from pebble"}'
        with patch("bridge.urlopen", return_value=fake_resp) as mocked:
            result = handler_mod.handler(
                {
                    "path": "/",
                    "httpMethod": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": base64.b64encode(raw).decode("ascii"),
                    "isBase64Encoded": True,
                },
                None,
            )
            req = mocked.call_args[0][0]
            self.assertEqual(json.loads(req.data.decode("utf-8")), {"note": "from pebble"})

        self.assertEqual(result["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
