# Webhook Bridge

A lightweight HTTP service that translates form-encoded and plain text webhooks to JSON, then forwards them to any upstream webhook URL you configure.

**One self-hosted instance = one user = one destination.** There is no shared multi-tenant host and no Matrix / Maubot / Beeper dependency. Paste any JSON-accepting webhook as `UPSTREAM_URL` (AI chat, OpenBot routine URL, automation, etc.).

## What It Does

Some clients (including Pebble / Index 01) POST `application/x-www-form-urlencoded` or `text/plain`. Many AI chat and automation webhooks only accept `application/json` and return **HTTP 415** otherwise. This bridge sits in the middle:

```
Pebble / Index 01  →  your bridge URL  →  UPSTREAM_URL (any JSON webhook)
```

**Supported input formats**

- `application/json` — forwarded as-is (object pass-through)
- `application/x-www-form-urlencoded` — fields become a JSON object
- `multipart/form-data` — form fields become a JSON object (Pebble / Index 01 often uses this)
- `text/plain` — parse as JSON if valid, otherwise wrap as `{"text": "..."}`

By default, payload fields are **not** reshaped for a specific chat product. When optional **OpenBot signing** is enabled, the converted payload is wrapped in OpenBot’s required event envelope and signed (see below).

**Features**

- Zero runtime dependencies (Python standard library only)
- Optional auth for incoming requests (`SHARED_SECRET`)
- Optional auth for upstream (`UPSTREAM_BEARER` or `UPSTREAM_AUTH_HEADER`)
- Optional OpenBot webhook signing (`OPENBOT_WEBHOOK_SECRET`)
- `GET /health` → `{"ok": true}`
- ~10 second upstream timeout
- Docker / Portainer (primary) and AWS Lambda packaging under `lambda/`

## Pebble Index 01 setup

Index 01 can send transcriptions to a webhook URL and can usually set custom headers. Typical flow:

1. **Choose a destination** — any HTTPS URL that accepts a JSON POST (OpenBot routine URL, agent hook, Zapier/Make, etc.).
2. **Run this bridge** — Docker (below) or Lambda (`lambda/README.md`). Set:
   - `UPSTREAM_URL` = that destination
   - optional `SHARED_SECRET` if you want the ring (or companion) to prove it may call your bridge
   - for OpenBot: `OPENBOT_WEBHOOK_SECRET` (and optional `OPENBOT_EVENT_TYPE`)
   - otherwise optional `UPSTREAM_BEARER` / `UPSTREAM_AUTH_HEADER` if the destination requires auth
3. **Point Index 01 at your bridge** — use `https://<your-host>/hook` (or `/`). Index 01 does **not** need OpenBot signature headers; the bridge adds those when forwarding.
4. **If you set `SHARED_SECRET`** — configure Index 01 (or the companion that posts) with either:
   - header `X-Bridge-Token: <same secret>`, or
   - header `Authorization: Bearer <same secret>`
5. Speak / send a transcription — the bridge converts the body to JSON and POSTs it to `UPSTREAM_URL`.

You keep Docker as the everyday self-host path. Friends who prefer AWS can use the `lambda/` zip without changing the Docker flow.

## Optional OpenBot signing

OpenBot agent/channel webhook routines reject plain Bearer tokens. They require signed headers on every request ([OpenBot webhooks docs](https://github.com/nightly-labs/openbot/blob/main/docs/webhooks.md)).

When `OPENBOT_WEBHOOK_SECRET` is set (the routine secret, usually `whsec_…`):

1. The converted Pebble payload is wrapped as:

   ```json
   {
     "type": "pebble.transcription",
     "occurredAt": "2026-11-03T07:00:00.000Z",
     "data": { "...converted pebble fields..." }
   }
   ```

   Override `type` with `OPENBOT_EVENT_TYPE` if your routine filters by event type. If the client already posts a valid OpenBot envelope (`type` plus `data` / `occurredAt`), that body is kept as-is.

2. The bridge serializes that JSON **once**, then signs the exact UTF-8 bytes:

   - `X-OpenBot-Timestamp` — Unix seconds
   - `X-OpenBot-Delivery-Id` — unique id per forward
   - `X-OpenBot-Signature` — `sha256=` + HMAC-SHA256 of `{timestamp}.{deliveryId}.{body}` with the secret

3. `UPSTREAM_BEARER` / `UPSTREAM_AUTH_HEADER` are ignored while OpenBot mode is on (signing replaces them).

Pebble still only needs your bridge URL (and optional `SHARED_SECRET`). You never paste OpenBot signature headers into the ring.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PORT` | No | `8080` | Listen port (Docker / native only) |
| `UPSTREAM_URL` | **Yes** | — | Destination webhook URL (OpenBot routine URL or any JSON POST endpoint) |
| `UPSTREAM_BEARER` | No | — | Bearer token for upstream (ignored when OpenBot signing is on) |
| `UPSTREAM_AUTH_HEADER` | No | — | Full `Authorization` value; overrides `UPSTREAM_BEARER` (ignored when OpenBot signing is on) |
| `OPENBOT_WEBHOOK_SECRET` | No | — | When set, enable OpenBot envelope + `X-OpenBot-*` signing |
| `OPENBOT_EVENT_TYPE` | No | `pebble.transcription` | OpenBot event `type` when wrapping payloads |
| `SHARED_SECRET` | No | — | Require `X-Bridge-Token` or `Authorization: Bearer` on incoming requests |

## Endpoints

### `POST /` or `POST /hook`

Accept webhook data in a supported format and forward as JSON to upstream.

**Response:** status mirrors upstream when possible; body is a short JSON summary such as `{"status": 200, "response": "..."}` or an error object.

### `GET /health`

```json
{"ok": true}
```

## Quick Start (Docker)

1. Clone this repository
2. Copy `.env.example` to `.env` and set at least `UPSTREAM_URL`
3. Start:

```bash
docker-compose up -d
curl http://localhost:8080/health
```

### Portainer Git Stack

1. **Stacks** → **Add stack** → **Repository**
2. Point at this repo, branch `main`, compose path `docker-compose.yml`
3. Set environment variables in the Portainer UI (`UPSTREAM_URL`, optional secrets). Do not bake secrets into the compose file.
4. Deploy

### Native Python

```bash
export UPSTREAM_URL=https://example.com/your-json-webhook
python3 app.py
```

## AWS Lambda

See [`lambda/README.md`](lambda/README.md). Package with:

```bash
bash lambda/package.sh
```

Upload `lambda/function.zip`, set handler `handler.handler`, configure the same env vars, attach a Function URL or API Gateway. Lambda packaging notes live under `lambda/` so Docker stays the default path.

## Usage Examples

### Form-encoded

```bash
curl -X POST http://localhost:8080/hook \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "message=Hello&priority=high"
```

Forwards: `{"message": "Hello", "priority": "high"}`

### Plain text

```bash
curl -X POST http://localhost:8080/hook \
  -H "Content-Type: text/plain" \
  -d "Alert: System status changed"
```

Forwards: `{"text": "Alert: System status changed"}`

### JSON pass-through

```bash
curl -X POST http://localhost:8080/hook \
  -H "Content-Type: application/json" \
  -d '{"event": "alert", "level": "warning"}'
```

### With bridge auth

```bash
curl -X POST http://localhost:8080/hook \
  -H "Content-Type: text/plain" \
  -H "X-Bridge-Token: your-secret-token" \
  -d "Authenticated message"
```

## License

MIT License — see [LICENSE](LICENSE).
