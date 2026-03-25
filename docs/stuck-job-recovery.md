# Stuck Job Recovery

When a worker crashes (SIGKILL, OOM, pod eviction), jobs it was processing remain in `processing` status. ElephantQ automatically recovers these jobs via its heartbeat system.

## Automatic recovery

Running workers periodically clean up stale peers. When a worker's heartbeat exceeds the stale threshold (default 5 minutes), its in-flight jobs are reset to `queued` and picked up by healthy workers.

The worst-case recovery time is `stale_worker_threshold` + `cleanup_interval` (default: 5 + 5 = 10 minutes). You can reduce this by tuning:

```bash
ELEPHANTQ_STALE_WORKER_THRESHOLD=120   # 2 minutes
ELEPHANTQ_CLEANUP_INTERVAL=60          # Check every minute
```

Additionally, the default **300-second job timeout** prevents most stuck-job scenarios caused by hung code (infinite loops, dead network calls). Override per-job with `@elephantq.job(timeout=600)`.

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

If no workers are running to perform automatic cleanup, reset stuck jobs manually:

```sql
UPDATE elephantq_jobs
SET status = 'queued', worker_id = NULL, updated_at = NOW()
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
UPDATE elephantq_workers
SET status = 'stopped'
WHERE status = 'active'
  AND last_heartbeat < NOW() - INTERVAL '10 minutes';
```

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `ELEPHANTQ_JOB_TIMEOUT` | `300` (5 min) | Default execution timeout per job (seconds) |
| `ELEPHANTQ_STALE_WORKER_THRESHOLD` | `300` (5 min) | Seconds before a worker is considered stale |
| `ELEPHANTQ_CLEANUP_INTERVAL` | `300` (5 min) | How often workers check for stale peers (seconds) |
| `ELEPHANTQ_WORKER_HEARTBEAT_INTERVAL` | `5` | How often workers send heartbeats (seconds) |

## Preventive measures

- **Graceful shutdown**: Use `SIGTERM` (not `SIGKILL`) to stop workers. ElephantQ handles `SIGTERM` by finishing in-flight jobs before exiting.
- **Kubernetes**: Set `terminationGracePeriodSeconds` to match your longest job timeout.
- **Systemd**: Set `TimeoutStopSec` appropriately.
- **OOM**: Monitor memory usage with `ELEPHANTQ_MEMORY_USAGE_THRESHOLD` and keep job payloads small.
