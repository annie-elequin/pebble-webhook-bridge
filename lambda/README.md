# AWS Lambda packaging

This folder is the Lambda-oriented entrypoint for the same bridge logic used by Docker (`../bridge.py`).

Docker remains the primary path maintained for day-to-day self-hosting. This path is for people who prefer AWS Lambda (API Gateway HTTP API or a Lambda Function URL).

## Behavior

Same as the Docker service:

- `GET /health` → `{"ok": true}`
- `POST /` or `POST /hook` → parse form / text / JSON, forward as `application/json` to `UPSTREAM_URL`
- Pass-through payload fields (no reshaping for a specific chat product)
- Optional `SHARED_SECRET`, `UPSTREAM_BEARER`, `UPSTREAM_AUTH_HEADER`, `UPSTREAM_HEADERS` (JSON object of extra outgoing headers)

## Package

From the repo root:

```bash
bash lambda/package.sh
```

That writes `lambda/function.zip` containing `bridge.py` and `handler.py`.

## Deploy (console sketch)

1. Create a Python 3.11+ Lambda function.
2. Upload `lambda/function.zip`.
3. Set **Handler** to `handler.handler`.
4. Set environment variables (same names as Docker):
   - `UPSTREAM_URL` (required) — any JSON webhook that should receive the message
   - optional: `SHARED_SECRET`, `UPSTREAM_BEARER`, `UPSTREAM_AUTH_HEADER`, `UPSTREAM_HEADERS`
5. Attach a **Function URL** (Auth: NONE or AWS_IAM) or API Gateway HTTP API route for `GET /health` and `POST /` (and `/hook` if you want both).
6. Point the Pebble / Index 01 webhook at the Function URL (or API stage URL).

## Note for maintainers

Keep Lambda-specific packaging and deploy notes here. Prefer changing shared behavior in `../bridge.py` so Docker and Lambda stay aligned.
