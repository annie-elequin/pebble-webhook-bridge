#!/usr/bin/env bash
# Build a zip suitable for AWS Lambda (Python 3.11+ runtime).
# Output: lambda/function.zip with bridge.py + handler.py at the zip root.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/lambda/function.zip"
STAGE="$(mktemp -d)"

cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

cp "${ROOT}/bridge.py" "${STAGE}/bridge.py"
cp "${ROOT}/lambda/handler.py" "${STAGE}/handler.py"

rm -f "$OUT"
(cd "$STAGE" && zip -q "$OUT" bridge.py handler.py)

echo "Wrote ${OUT}"
echo "Upload to Lambda and set handler to: handler.handler"
echo "Configure env: UPSTREAM_URL (required), SHARED_SECRET, UPSTREAM_BEARER, UPSTREAM_AUTH_HEADER, UPSTREAM_HEADERS"
