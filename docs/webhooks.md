# Webhooks

ElephantQ can send HTTP notifications when job lifecycle events occur — useful for alerting, audit trails, or triggering downstream systems.

## Enable

```bash
export ELEPHANTQ_WEBHOOKS_ENABLED=true
```

No extra install needed — `aiohttp` is included in the base package.

## Register an endpoint

```python
from elephantq.features.webhooks import WebhookRegistry

registry = WebhookRegistry()
await registry.register_endpoint(
    url="https://hooks.example.com/elephantq",
    events=["job.failed", "job.dead_letter"],
    secret="your-hmac-secret",
)
```

If you omit `events`, the endpoint receives all event types.

## Event types

| Event | Fires when |
| --- | --- |
| `job.queued` | A job is added to the queue |
| `job.started` | A worker begins processing a job |
| `job.completed` | A job finishes successfully |
| `job.failed` | A job fails (may still retry) |
| `job.retried` | A failed job is retried |
| `job.dead_letter` | A job exhausts its retries and moves to dead letter |
| `job.resurrected` | A dead-letter job is resurrected back to the queue |
| `queue.backlog` | Queue depth exceeds a threshold |
| `system.alert` | System-level alert (stale workers, high failure rate) |

## Payload format

Each delivery sends a JSON POST body:

```json
{
  "event": "job.failed",
  "timestamp": "2026-03-21T10:30:00Z",
  "data": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "job_name": "app.tasks.send_email",
    "queue": "emails",
    "status": "failed",
    "attempts": 3,
    "last_error": "ConnectionRefused: smtp.example.com"
  }
}
```

## HMAC signature verification

When you register an endpoint with a `secret`, ElephantQ signs each payload and includes the signature in the `X-Webhook-Signature` header.

To verify on your server:

```python
import hmac
import hashlib

def verify_signature(payload_bytes: bytes, secret: str, signature: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

### Headers sent with each delivery

| Header | Description |
| --- | --- |
| `Content-Type` | `application/json` |
| `User-Agent` | `ElephantQ-Webhook/1.0` |
| `X-Webhook-Event` | Event type (e.g. `job.failed`) |
| `X-Webhook-Delivery` | Unique delivery ID |
| `X-Webhook-Timestamp` | Unix timestamp of send |
| `X-Webhook-Signature` | HMAC-SHA256 signature (only if secret is set) |

## Retries

Failed deliveries are retried with exponential backoff (60s, 120s, 240s, capped at 300s). The default `max_attempts` is 3. After exhausting retries the delivery is marked as `failed`.

## Testing with curl

Simulate what ElephantQ sends to your endpoint:

```bash
curl -X POST https://hooks.example.com/elephantq \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Event: job.failed" \
  -H "X-Webhook-Delivery: test-123" \
  -d '{"event":"job.failed","timestamp":"2026-03-21T10:30:00Z","data":{"job_id":"test","job_name":"app.tasks.send_email","status":"failed"}}'
```
