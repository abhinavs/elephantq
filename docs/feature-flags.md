# Feature Flags and Environment Variables

All ElephantQ settings are configured via environment variables with the `ELEPHANTQ_` prefix. You can also use a `.env` file.

## Required

| Variable | Description | Default |
| --- | --- | --- |
| `ELEPHANTQ_DATABASE_URL` | PostgreSQL connection string | `postgresql://postgres@localhost/postgres` |

## Job Discovery

| Variable | Description | Default |
| --- | --- | --- |
| `ELEPHANTQ_JOBS_MODULE` | Python module containing jobs | `jobs` |
| `ELEPHANTQ_JOBS_MODULES` | Comma-separated list of modules | `""` |

## Worker

| Variable | Description | Default | Range |
| --- | --- | --- | --- |
| `ELEPHANTQ_DEFAULT_CONCURRENCY` | Concurrent job slots per worker | `4` | 1-100 |
| `ELEPHANTQ_DEFAULT_QUEUES` | Comma-separated queue names | `default` | — |
| `ELEPHANTQ_DEFAULT_MAX_RETRIES` | Max retries for failed jobs | `3` | 0-10 |
| `ELEPHANTQ_DEFAULT_PRIORITY` | Default job priority (lower = higher) | `100` | 1-1000 |

## Connection Pool

| Variable | Description | Default | Range |
| --- | --- | --- | --- |
| `ELEPHANTQ_DB_POOL_MIN_SIZE` | Minimum pool connections | `5` | 1-100 |
| `ELEPHANTQ_DB_POOL_MAX_SIZE` | Maximum pool connections | `20` | 1-200 |
| `ELEPHANTQ_DB_POOL_SAFETY_MARGIN` | Extra connections for listener/heartbeat | `2` | 0-50 |

## Timeouts and Intervals

| Variable | Description | Default | Range |
| --- | --- | --- | --- |
| `ELEPHANTQ_JOB_TIMEOUT` | Per-job execution timeout (seconds) | none | 1.0+ |
| `ELEPHANTQ_WORKER_HEARTBEAT_INTERVAL` | Heartbeat frequency (seconds) | `5.0` | 0.1-60.0 |
| `ELEPHANTQ_CLEANUP_INTERVAL` | Expired job cleanup interval (seconds) | `300.0` | 10.0-3600.0 |
| `ELEPHANTQ_STALE_WORKER_THRESHOLD` | Time before a worker is considered stale (seconds) | `300.0` | 60.0-7200.0 |
| `ELEPHANTQ_NOTIFICATION_TIMEOUT` | LISTEN/NOTIFY timeout (seconds) | `5.0` | 0.1-60.0 |
| `ELEPHANTQ_ERROR_RETRY_DELAY` | Delay before retrying after internal errors (seconds) | `5.0` | 0.1-300.0 |
| `ELEPHANTQ_RESULT_TTL` | Job result retention (seconds, 0 = delete immediately) | `300` | — |

## Feature Flags

All default to `false`. Set to `true` to enable.

| Variable | What it unlocks |
| --- | --- |
| `ELEPHANTQ_SCHEDULING_ENABLED` | `elephantq.scheduling` and `elephantq.scheduling` (requires `pip install elephantq[scheduling]`) |
| `ELEPHANTQ_DEPENDENCIES_ENABLED` | Job dependency tracking (experimental — not yet enforced by worker) |
| `ELEPHANTQ_TIMEOUTS_ENABLED` | Per-job timeout enforcement |
| `ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED` | Dead-letter queue for permanently failed jobs |
| `ELEPHANTQ_METRICS_ENABLED` | Metrics collection and Prometheus-style counters (requires `pip install elephantq[monitoring]`) |
| `ELEPHANTQ_LOGGING_ENABLED` | Structured logging (requires `pip install elephantq[logging]`) |
| `ELEPHANTQ_WEBHOOKS_ENABLED` | HTTP webhook notifications (requires `pip install elephantq[webhooks]`) |
| `ELEPHANTQ_SIGNING_ENABLED` | Signing and secure secret helpers (requires `pip install elephantq[webhooks]`) |
| `ELEPHANTQ_DASHBOARD_ENABLED` | Web dashboard (requires `pip install elephantq[dashboard]`) |
| `ELEPHANTQ_DASHBOARD_WRITE_ENABLED` | Write actions (retry/delete/cancel) in the dashboard |

## Health Check Thresholds

| Variable | Description | Default | Range |
| --- | --- | --- | --- |
| `ELEPHANTQ_HEALTH_CHECK_TIMEOUT` | Health check timeout (seconds) | `5.0` | 0.1-60.0 |
| `ELEPHANTQ_HEALTH_MONITORING_INTERVAL` | Health monitoring frequency (seconds) | `30.0` | 1.0-3600.0 |
| `ELEPHANTQ_HEALTH_ERROR_RETRY_DELAY` | Retry delay after health check failure (seconds) | `5.0` | 0.1-300.0 |
| `ELEPHANTQ_STUCK_JOBS_THRESHOLD` | Stuck jobs before alerting | `100` | 1-10000 |
| `ELEPHANTQ_JOB_FAILURE_RATE_THRESHOLD` | Failure rate percentage before alerting | `50.0` | 0.0-100.0 |
| `ELEPHANTQ_MEMORY_USAGE_THRESHOLD` | Memory usage percentage before alerting | `90.0` | 50.0-99.0 |
| `ELEPHANTQ_DISK_USAGE_THRESHOLD` | Disk usage percentage before alerting | `90.0` | 50.0-99.0 |
| `ELEPHANTQ_CPU_USAGE_THRESHOLD` | CPU usage percentage before alerting | `95.0` | 50.0-99.0 |

## Logging

| Variable | Description | Default |
| --- | --- | --- |
| `ELEPHANTQ_LOG_LEVEL` | Log level | `INFO` |
| `ELEPHANTQ_LOG_FORMAT` | Log format (`simple` or `structured`) | `simple` |

## Development

| Variable | Description | Default |
| --- | --- | --- |
| `ELEPHANTQ_DEBUG` | Enable debug mode | `false` |
| `ELEPHANTQ_ENVIRONMENT` | Environment name | `production` |
| `ELEPHANTQ_DEFAULT_JOB_DISPLAY_LIMIT` | Max jobs shown in CLI output | `10` |
