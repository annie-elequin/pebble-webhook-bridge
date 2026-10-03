#!/usr/bin/env python3
"""Quick smoke test of the webhook bridge logic"""
import json
from urllib.parse import parse_qs

def parse_body(content_type, body_bytes):
    """Parse incoming body based on content type"""
    body = body_bytes.decode('utf-8')
    
    if content_type.startswith('application/json'):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"text": body}
    
    elif content_type.startswith('application/x-www-form-urlencoded'):
        parsed = parse_qs(body, keep_blank_values=True)
        return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
    
    elif content_type.startswith('text/plain'):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"text": body}
    
    else:
        raise ValueError(f"Unsupported content type: {content_type}")

# Test cases
tests = [
    # Form-encoded
    {
        "name": "Form-encoded simple",
        "content_type": "application/x-www-form-urlencoded",
        "body": b"message=Hello&priority=high",
        "expected": {"message": "Hello", "priority": "high"}
    },
    # Plain text non-JSON
    {
        "name": "Plain text",
        "content_type": "text/plain",
        "body": b"Alert: System status changed",
        "expected": {"text": "Alert: System status changed"}
    },
    # Plain text that is JSON
    {
        "name": "Plain text JSON",
        "content_type": "text/plain",
        "body": b'{"event": "alert"}',
        "expected": {"event": "alert"}
    },
    # JSON pass-through
    {
        "name": "JSON pass-through",
        "content_type": "application/json",
        "body": b'{"event": "alert", "level": "warning"}',
        "expected": {"event": "alert", "level": "warning"}
    },
    # Unsupported content type
    {
        "name": "Unsupported content type",
        "content_type": "application/xml",
        "body": b"<xml/>",
        "should_fail": True
    }
]

print("Running webhook bridge logic tests...\n")
passed = 0
failed = 0

for test in tests:
    try:
        result = parse_body(test["content_type"], test["body"])
        if test.get("should_fail"):
            print(f"❌ {test['name']}: Expected failure but succeeded")
            print(f"   Result: {result}\n")
            failed += 1
        elif result == test["expected"]:
            print(f"✅ {test['name']}: PASS")
            passed += 1
        else:
            print(f"❌ {test['name']}: FAIL")
            print(f"   Expected: {test['expected']}")
            print(f"   Got: {result}\n")
            failed += 1
    except Exception as e:
        if test.get("should_fail"):
            print(f"✅ {test['name']}: PASS (expected failure: {e})")
            passed += 1
        else:
            print(f"❌ {test['name']}: FAIL with exception")
            print(f"   {e}\n")
            failed += 1

print(f"\n{'='*50}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'='*50}")

exit(0 if failed == 0 else 1)
