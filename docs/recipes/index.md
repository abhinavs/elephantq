# Recipes

Copy-paste patterns for common background job use cases.

## Job patterns

- [Email jobs](email-jobs.md) - idempotent sending, escalating retries, dedicated queue
- [File processing](file-processing.md) - background uploads, CPU-bound work, long timeouts
- [Scheduled reports](scheduled-reports.md) - cron-based periodic tasks
- [Webhook delivery](webhook-delivery.md) - aggressive retries, idempotency tracking, payload signing

## Extension points

- [Custom retry policy](custom-retry-policy.md) - rate-limit-aware backoff, type-specific delays, no-retry mode
- [Custom serializer](custom-serializer.md) - schema-versioned payloads, redaction, JSON wrappers
- [Custom metrics sink](custom-metrics-sink.md) - Prometheus, statsd, OpenTelemetry, or anything else
