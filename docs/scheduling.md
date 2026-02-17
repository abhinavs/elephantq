# Scheduling & Recurring Jobs

Enable scheduling features:

```bash
export ELEPHANTQ_SCHEDULING_ENABLED=true
```

## One-off scheduling

```python
import elephantq
from datetime import timedelta

@elephantq.job()
async def send_email(to: str):
    pass

# schedule in 10 minutes
await elephantq.schedule(send_email, run_in=timedelta(minutes=10), to="user@example.com")
```

### Transactional scheduling

If you need the schedule to be part of an existing database transaction, pass a connection:

```python
pool = await elephantq.get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        await elephantq.schedule(send_email, run_in=60, connection=conn, to="user@example.com")
```

## Recurring (cron)

```python
import elephantq

@elephantq.job()
async def daily_report():
    pass

await elephantq.features.recurring.cron("0 9 * * *").schedule(daily_report)
```

## Recurring (interval)

```python
elephantq.features.recurring.every(10).minutes().schedule(daily_report)
```

## Scheduler process

```bash
elephantq scheduler
```

## Persistence

Recurring jobs are persisted in the database (table: `elephantq_recurring_jobs`) and are reloaded when the scheduler starts. If the scheduler restarts, previously scheduled recurring jobs resume automatically.
