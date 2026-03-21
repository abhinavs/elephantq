# Stuck Job Recovery

When a worker crashes (SIGKILL, OOM, pod eviction), jobs it was processing remain in `processing` status. These "stuck" jobs won't be retried automatically until automatic recovery is implemented.

## Detection

Find stuck jobs by looking for `processing` jobs with old `updated_at` timestamps:

```sql
SELECT id, job_name, queue, attempts, updated_at
FROM elephantq_jobs
WHERE status = 'processing'
  AND updated_at < NOW() - INTERVAL '10 minutes'
ORDER BY updated_at ASC;
```

Check for stale workers:

```bash
elephantq workers --stale
```

## Manual recovery

Reset stuck jobs back to `queued` so they'll be picked up by a healthy worker:

```sql
UPDATE elephantq_jobs
SET status = 'queued', updated_at = NOW()
WHERE status = 'processing'
  AND updated_at < NOW() - INTERVAL '10 minutes';
```

Tune the interval to match your longest-running job. If you have jobs that legitimately run for 30 minutes, use `INTERVAL '35 minutes'` instead.

## Clean up stale workers

Remove worker records that haven't sent a heartbeat:

```bash
elephantq workers --cleanup
```

Or manually:

```sql
DELETE FROM elephantq_workers
WHERE last_heartbeat < NOW() - INTERVAL '10 minutes';
```

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `ELEPHANTQ_STALE_WORKER_THRESHOLD` | `300` (5 min) | Seconds before a worker is considered stale |
| `ELEPHANTQ_WORKER_HEARTBEAT_INTERVAL` | `5` | How often workers send heartbeats (seconds) |

## Preventive measures

- **Graceful shutdown**: Use `SIGTERM` (not `SIGKILL`) to stop workers. ElephantQ handles `SIGTERM` by finishing in-flight jobs before exiting.
- **Kubernetes**: Set `terminationGracePeriodSeconds` to match your longest job timeout.
- **Systemd**: Set `TimeoutStopSec` appropriately.
- **OOM**: Monitor memory usage with `ELEPHANTQ_MEMORY_USAGE_THRESHOLD` and keep job payloads small.

## Future

Automatic `processing → queued` recovery for stale workers is planned. Until then, consider running the manual recovery SQL as a cron job or a recurring ElephantQ job itself.
