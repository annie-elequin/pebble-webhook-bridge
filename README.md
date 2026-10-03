# Webhook Bridge

A lightweight HTTP service that translates form-encoded and plain text webhooks to JSON format before forwarding them to an upstream webhook URL.

## What It Does

Many webhook clients (like Pebble smartwatches) send data as `application/x-www-form-urlencoded` or `text/plain`, but some webhook receivers only accept `application/json`. This bridge sits in the middle, accepting various content types and forwarding everything as properly formatted JSON.

**Supported Input Formats:**
- `application/json` - forwarded as-is
- `application/x-www-form-urlencoded` - parsed into JSON object
- `text/plain` - parsed as JSON if valid, otherwise wrapped as `{"text": "..."}`

**Features:**
- Zero dependencies (Python standard library only)
- Optional authentication for incoming requests
- Optional authentication for upstream requests
- Health check endpoint
- ~10 second upstream timeout
- Docker-ready with Portainer support

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PORT` | No | `8080` | Port to listen on |
| `UPSTREAM_URL` | **Yes** | - | Upstream webhook URL to forward requests to |
| `UPSTREAM_BEARER` | No | - | Bearer token for upstream authentication |
| `UPSTREAM_AUTH_HEADER` | No | - | Full Authorization header value (overrides `UPSTREAM_BEARER`) |
| `SHARED_SECRET` | No | - | Require incoming requests to send this token via `X-Bridge-Token` header or `Authorization: Bearer` |

## Endpoints

### `POST /` or `POST /hook`
Accept webhook data in any supported format and forward as JSON to upstream.

**Request Headers:**
- `Content-Type`: `application/json`, `application/x-www-form-urlencoded`, or `text/plain`
- `X-Bridge-Token` or `Authorization: Bearer <token>` (if `SHARED_SECRET` is set)

**Response:**
- Status code matches upstream response
- Body: `{"status": <code>, "response": "<upstream_body>"}` or error details

### `GET /health`
Health check endpoint.

**Response:**
```json
{"ok": true}
```

## Quick Start

### Docker Compose (Local)

1. Clone this repository
2. Copy `.env.example` to `.env` and configure:
   ```bash
   cp .env.example .env
   ```
3. Edit `.env` and set at minimum:
   ```
   UPSTREAM_URL=https://your-webhook-endpoint.com/webhook
   ```
4. Start the service:
   ```bash
   docker-compose up -d
   ```
5. Test the health check:
   ```bash
   curl http://localhost:8080/health
   ```

### Portainer Git Stack

1. In Portainer, go to **Stacks** → **Add stack**
2. Choose **Repository** as build method
3. Configure:
   - **Repository URL**: `https://github.com/your-username/webhook-bridge`
   - **Repository reference**: `refs/heads/main`
   - **Compose path**: `docker-compose.yml`
4. Under **Environment variables**, add:
   ```
   UPSTREAM_URL=https://your-webhook-endpoint.com/webhook
   PORT=8080
   ```
   Add optional variables as needed:
   ```
   SHARED_SECRET=your-secret-token
   UPSTREAM_BEARER=upstream-auth-token
   ```
5. Click **Deploy the stack**
6. Portainer will clone the repo, build the image, and start the service

### Native Python (Development)

```bash
export UPSTREAM_URL=https://your-webhook-endpoint.com/webhook
python3 app.py
```

## Usage Examples

### Form-Encoded Request
```bash
curl -X POST http://localhost:8080/hook \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "message=Hello&priority=high"
```
Forwards as:
```json
{"message": "Hello", "priority": "high"}
```

### Plain Text Request
```bash
curl -X POST http://localhost:8080/hook \
  -H "Content-Type: text/plain" \
  -d "Alert: System status changed"
```
Forwards as:
```json
{"text": "Alert: System status changed"}
```

### JSON Request (Pass-Through)
```bash
curl -X POST http://localhost:8080/hook \
  -H "Content-Type: application/json" \
  -d '{"event": "alert", "level": "warning"}'
```
Forwards as-is.

### With Authentication
```bash
curl -X POST http://localhost:8080/hook \
  -H "Content-Type: text/plain" \
  -H "X-Bridge-Token: your-secret-token" \
  -d "Authenticated message"
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Contributing

This is a simple utility project. Feel free to fork and adapt for your needs!
