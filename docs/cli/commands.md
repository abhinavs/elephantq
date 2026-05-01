# CLI Commands

All commands accept `--database-url URL` to override the `SONIQ_DATABASE_URL`
environment variable.

```
soniq <command> [options]
```


## setup

Create or update the database schema. Idempotent -- run it on every deploy.

```bash
soniq setup
```

What it does:
1. Creates the PostgreSQL database if it does not exist.
2. Applies all pending migrations.
3. Reports how many migrations were applied.

If the schema is already up to date, it prints a confirmation and exits.

**When to use:** during deployment, in CI pipelines, or the first time you set up
Soniq.


## start

Start a worker process that fetches and executes jobs.

```bash
soniq start [--concurrency N] [--queues QUEUES] [--run-once]
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--concurrency` | `int` | `4` | Number of jobs the worker will run in parallel. |
| `--queues` | `str` | all queues | Comma-separated list of queue names to process. |
| `--run-once` | flag | off | Process all available jobs and exit. |

Requires `SONIQ_JOBS_MODULES` to be set so the worker can discover and import
your job functions. See [Job module discovery](../getting-started/installation.md#job-module-discovery) for the full reference (single-repo, cross-service, and per-worker overrides).

```bash
export SONIQ_JOBS_MODULES=myapp.tasks,myapp.other_tasks
soniq start --concurrency 8 --queues urgent,default
```

When `--queues` is omitted, the worker processes **all queues** in the database. Pass `--queues=name1,name2` to restrict.

The worker handles `SIGINT` and `SIGTERM` for graceful shutdown. Send the signal
once to finish current jobs, twice to force exit.


## status

Show system health, queue statistics, and optionally recent jobs.

```bash
soniq status [--verbose] [--jobs]
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--verbose` | flag | off | Show per-queue breakdown table. |
| `--jobs` | flag | off | Show the 10 most recent jobs. |

```bash
soniq status --verbose --jobs
```

Output includes:
- Database connection health check
- Total jobs, queued count, failed/dead-letter count
- Active and stale worker summary
- Per-queue breakdown (with `--verbose`)
- Recent job list (with `--jobs`)


## workers

List registered workers and their status.

```bash
soniq workers [--stale] [--cleanup]
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--stale` | flag | off | Include stale (no recent heartbeat) workers in the output. |
| `--cleanup` | flag | off | Remove stale worker records from the database. |

```bash
# Show active workers
soniq workers

# Show stale workers too
soniq workers --stale

# Clean up stale records
soniq workers --cleanup
```

For each active worker, shows: hostname, PID, queues, concurrency, uptime, last
heartbeat, and resource usage (CPU/memory) when available.


## dead-letter

Manage jobs that exhausted all retries.

```bash
soniq dead-letter <action> [options]
```

### Actions

**list** -- show dead-letter jobs.

```bash
soniq dead-letter list [--limit 50] [--filter JOB_NAME]
```

**replay** -- mint a fresh job from a dead-letter row. The DLQ row stays
as the audit trail; a new `soniq_jobs` row is created with a new UUID
and `resurrection_count` is incremented.

```bash
soniq dead-letter replay <job-id> [<job-id> ...]
soniq dead-letter replay --all                       # interactive prompt for >= 5 jobs
soniq dead-letter replay --all --dry-run             # report count + sample, no changes
soniq dead-letter replay --all --yes                 # skip the confirmation prompt
```

`replay --all` is a footgun: if the DLQ filled up because of a bug that
has not been fixed, replaying everything just runs the same jobs back
into the same bug. The CLI prompts before re-queuing five or more jobs
and refuses to run non-interactively without `--yes`.

**delete** -- permanently remove a dead-letter job.

```bash
soniq dead-letter delete <job-id> [<job-id> ...]
soniq dead-letter delete --all                       # interactive prompt for >= 5 jobs
soniq dead-letter delete --all --dry-run             # report count + sample, no changes
soniq dead-letter delete --all --yes                 # skip the confirmation prompt
```

**cleanup** -- remove dead-letter jobs older than N days. The `--dry-run`
flag is accepted for symmetry but is currently a no-op: cleanup always
deletes.

```bash
soniq dead-letter cleanup --days 30
```

**export** -- export dead-letter jobs to a file.

```bash
soniq dead-letter export --format json --output dead_letter.json
soniq dead-letter export --format csv --output dead_letter.csv
```

### Common flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--limit` | `int` | `50` | Maximum jobs to show (for `list`). |
| `--filter` | `str` | | Filter by job name pattern. |
| `--all` | flag | off | Apply action to all matching jobs. |
| `--days` | `int` | `30` | Age threshold for `cleanup`. |
| `--dry-run` | flag | off | Honoured on `replay --all` and `delete --all` (reports count + sample). Accepted on `cleanup` for symmetry but ignored -- cleanup always deletes. |
| `--yes`, `-y` | flag | off | Skip the interactive confirmation for bulk `replay --all` / `delete --all`. Required in non-interactive shells. |
| `--format` | `csv \| json` | `csv` | Export format. |
| `--output` | `str` | | Output file path (required for `export`). |


## dashboard

Launch the web dashboard for monitoring jobs, queues, and workers.

Requires `pip install soniq[dashboard]`.

```bash
soniq dashboard [--host HOST] [--port PORT] [--reload]
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--host` | `str` | `127.0.0.1` | Network interface to bind to. Use `0.0.0.0` for all interfaces. |
| `--port` | `int` | `6161` | Port number. |
| `--reload` | flag | off | Auto-reload on code changes (development only). |

```bash
soniq dashboard --host 0.0.0.0 --port 6161
```

Open `http://localhost:6161` in your browser.

The dashboard is read-only by default. Set `SONIQ_DASHBOARD_WRITE_ENABLED=true`
to enable replay, delete, and cancel actions.


## scheduler

Start the recurring job scheduler. It checks for due `@periodic` jobs and
enqueues them.

```bash
soniq scheduler [--check-interval SECONDS] [--status]
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--check-interval` | `int` | `60` | Seconds between checks for due recurring jobs. |
| `--status` | flag | off | Print scheduler status and exit. |

```bash
# Start the scheduler
soniq scheduler --check-interval 30

# Check if the scheduler is running
soniq scheduler --status
```

Stop the scheduler gracefully with `Ctrl+C`.


## migrate-status

Show which database migrations have been applied and which are pending.

```bash
soniq migrate-status
```

Output lists each migration with its status (applied or pending). If migrations
are pending, it tells you to run `soniq setup`.
