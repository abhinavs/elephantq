# Metrics, Logging, Webhooks, Dead Letter

These features are available in the core package and require optional deps for monitoring, plus feature flags.

```bash
pip install elephantq[monitoring]
```

Enable flags:

```bash
export ELEPHANTQ_METRICS_ENABLED=true
export ELEPHANTQ_LOGGING_ENABLED=true
export ELEPHANTQ_WEBHOOKS_ENABLED=true
export ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED=true
```

## Metrics

```python
import elephantq
metrics = await elephantq.features.metrics.get_system_metrics()
```

## Structured Logging

```python
logger = elephantq.features.logging.setup(format="structured", level="INFO")
job_logger = elephantq.features.logging.get_job_logger("job-id")
```

## Webhooks

```python
await elephantq.features.webhooks.register_endpoint(
    url="https://example.com/webhooks/job-events",
    events=["job.failed", "job.dead_letter"],
    secret="your-secret",
)
```

## Dead Letter

```python
stats = await elephantq.features.dead_letter.get_stats()
```
