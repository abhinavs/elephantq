# Queues

Queues let you separate jobs by workload type and control which workers process them.

## Named queues

Assign a job to a queue in the decorator:

```python
@app.job(queue="emails")
async def send_welcome_email(user_id: int):
    ...

@app.job(queue="billing")
async def charge_subscription(account_id: str, amount: int):
    ...

@app.job()  # defaults to "default" queue
async def process_thumbnail(image_id: str):
    ...
```

You can also override the queue at enqueue time:

```python
await app.enqueue(send_welcome_email, user_id=42, queue="urgent")
```

## Priority ordering

Within a queue, jobs are processed by priority. Lower number means higher priority. Jobs with the same priority are processed in FIFO order.

| Priority | Typical use |
| --- | --- |
| 1 | Urgent -- user-facing, time-sensitive |
| 10 | High -- important but not blocking |
| 50 | Normal -- default for most workloads |
| 100 | Default -- the `@app.job()` default |

```python
@app.job(queue="billing", priority=10)
async def charge_subscription(account_id: str, amount: int):
    ...

# One-off priority override
await app.enqueue(charge_subscription, account_id="acct_123", amount=999, priority=1)
```

## Running workers on specific queues

By default, a worker processes all queues. To limit a worker to specific queues, use the `--queues` flag:

```bash
# Process only email and billing jobs
elephantq start --queues emails,billing

# Dedicated urgent worker with higher concurrency
elephantq start --queues urgent --concurrency 8
```

Programmatically:

```python
await app.run_worker(queues=["emails", "billing"], concurrency=4)
```

This lets you scale queue capacity independently. Run more email workers during peak hours, or dedicate a fast machine to your billing queue.

## Queue stats

```python
stats = await app.get_queue_stats()
for queue in stats:
    print(f"{queue['queue']}: {queue['queued']} queued, {queue['processing']} processing")
```

From the CLI:

```bash
elephantq status
```

## Design advice

**Split by workload type.** Keep CPU-bound image processing separate from fast email sends. This prevents slow jobs from blocking quick ones.

**Keep payloads small.** Pass IDs, not blobs. Instead of enqueuing a 10MB CSV, store it somewhere and pass the storage key. Job arguments are serialized as JSON in the database.

**Run dedicated worker groups per queue.** A worker group is a set of processes that share the same `--queues` flag. This gives you independent scaling and failure isolation -- a crash in image processing won't affect your email workers.
