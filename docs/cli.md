# ElephantQ CLI

```bash
elephantq setup
elephantq start --concurrency 4 --queues default,urgent
elephantq status --verbose --jobs
elephantq workers
elephantq jobs list --limit 50
elephantq jobs retry <job-id>
elephantq jobs cancel <job-id>
```

## Dashboard

```bash
export ELEPHANTQ_DASHBOARD_ENABLED=true
elephantq dashboard --host 0.0.0.0 --port 6161
```
This dashboard is read-only.

## Scheduler

```bash
elephantq scheduler
elephantq scheduler --status
```

## Metrics

```bash
elephantq metrics --hours 24
```

## Dead Letter

```bash
elephantq dead-letter list --limit 50
elephantq dead-letter resurrect <job-id>
elephantq dead-letter delete <job-id>
elephantq dead-letter cleanup --days 30
elephantq dead-letter export --format json --output dead_letter.json
```
