# Using ElephantQ with AI Agents

ElephantQ provides a programmatic async API suitable for LLM agents and automation pipelines.

## Setup

```python
import elephantq

elephantq.configure(database_url="postgresql://localhost/myapp")
await elephantq.setup()
```

## Operations

### Enqueue work

```python
job_id = await elephantq.enqueue(process_document, doc_id="abc123")
```

### Check job status

```python
status = await elephantq.get_job_status(job_id)
# Returns: {
#   "id": "...",
#   "status": "done",       # queued | processing | done | failed | dead_letter | cancelled
#   "attempts": 1,
#   "max_attempts": 3,
#   "queue": "default",
#   "created_at": "2025-01-15T09:00:00+00:00",
#   ...
# }
```

### List jobs

```python
# All jobs
jobs = await elephantq.list_jobs()

# Filter by status
failed = await elephantq.list_jobs(status="dead_letter", limit=10)

# Filter by queue
email_jobs = await elephantq.list_jobs(queue="emails")
```

### Manage jobs

```python
# Cancel a queued job
await elephantq.cancel_job(job_id)

# Retry a dead-lettered job
await elephantq.retry_job(job_id)

# Delete a job
await elephantq.delete_job(job_id)
```

### Queue statistics

```python
stats = await elephantq.get_queue_stats()
# Returns: [
#   {"queue": "default", "total": 100, "queued": 5, "processing": 2, "done": 90, ...},
#   {"queue": "emails", "total": 50, "queued": 10, ...},
# ]
```

## Response format

All API methods return plain Python dicts with consistent shapes:

- **Job IDs** — UUIDs as strings
- **Status values** — `queued`, `processing`, `done`, `failed`, `dead_letter`, `cancelled`
- **Timestamps** — ISO 8601 UTC strings
- **Args** — parsed JSON (dict)

## Idempotency

ElephantQ provides at-least-once delivery. Use `queueing_lock` to prevent duplicate enqueues:

```python
await elephantq.enqueue(
    send_report,
    user_id=42,
    queueing_lock=f"report:{42}",  # Only one per user
)
```

Jobs can also access their own identity for idempotency checks:

```python
from elephantq import JobContext

@elephantq.job()
async def process_payment(order_id: str, ctx: JobContext):
    if await already_processed(ctx.job_id):
        return
    ...
```
