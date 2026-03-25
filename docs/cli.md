# ElephantQ CLI

## Available commands

```
elephantq --help

Available commands:
  start            Start ElephantQ worker
  setup            Setup ElephantQ database
  migrate-status   Show database migration status
  status           Show system status
  workers          Show worker status
  dashboard        Launch the ElephantQ web dashboard
  scheduler        Run the ElephantQ recurring job scheduler
  metrics          Show ElephantQ performance metrics
  dead-letter      Manage dead letter queue jobs
```

## Setup and workers

```bash
# Initialize database schema
elephantq setup

# Start a worker
elephantq start --concurrency 4 --queues default,urgent

# Check system status
elephantq status --verbose --jobs

# List workers (active and stale)
elephantq workers
elephantq workers --stale
elephantq workers --cleanup   # remove stale worker records

# Check migration status
elephantq migrate-status
```

All commands accept `--database-url` to override `ELEPHANTQ_DATABASE_URL`.

## Dashboard

```bash
export ELEPHANTQ_DASHBOARD_ENABLED=true
elephantq dashboard --host 0.0.0.0 --port 6161
```

The dashboard is read-only by default. Set `ELEPHANTQ_DASHBOARD_WRITE_ENABLED=true` to enable retry/delete/cancel actions.

## Scheduler

```bash
# Run the recurring job scheduler
elephantq scheduler

# Check scheduler status
elephantq scheduler --status

# Custom check interval
elephantq scheduler --check-interval 30
```

## Metrics

```bash
# Table output (default)
elephantq metrics --hours 24

# JSON output
elephantq metrics --format json --hours 1

# Export to file
elephantq metrics --format json --export metrics.json
```

## Dead Letter

```bash
# List dead-letter jobs
elephantq dead-letter list --limit 50

# Resurrect a job (put it back in the queue)
elephantq dead-letter resurrect <job-id>

# Delete a dead-letter job
elephantq dead-letter delete <job-id>

# Clean up old dead-letter jobs
elephantq dead-letter cleanup --days 30
elephantq dead-letter cleanup --days 7 --dry-run   # preview first

# Export dead-letter jobs
elephantq dead-letter export --format json --output dead_letter.json
elephantq dead-letter export --format csv --output dead_letter.csv
```
