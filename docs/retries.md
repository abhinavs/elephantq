# Retries & Backoff

ElephantQ retries failed jobs by default. You can control the delay and backoff at the job level.

## Basic Retries

```python
import elephantq

@elephantq.job(retries=3)
async def send_email(to: str):
    ...
```

## Fixed Delay

```python
@elephantq.job(retries=5, retry_delay=2)  # 2 seconds between attempts
async def flaky_task():
    ...
```

## Exponential Backoff

```python
@elephantq.job(retries=5, retry_delay=1, retry_backoff=True, retry_max_delay=30)
async def api_call():
    ...
```

## Per-Attempt Delays

```python
@elephantq.job(retries=3, retry_delay=[1, 5, 15])
async def staged_retry():
    ...
```

Notes:
- `retries` means additional attempts. Total attempts = `retries + 1`.
- Backoff is applied on top of `retry_delay`.
- If delay is 0, the retry is immediate.

## Idempotency

ElephantQ provides **at-least-once delivery**. Because retries re-execute your job function, and because a worker crash can also cause re-execution, your jobs should be idempotent. Common patterns:

- **Database upserts:** Use `INSERT ... ON CONFLICT DO UPDATE` instead of plain inserts.
- **Idempotency keys:** Store a unique key per operation and check before performing side effects.
- **Check-before-act:** Verify the current state before taking action (e.g., check if the email was already sent).
