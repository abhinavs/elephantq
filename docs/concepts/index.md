# Concepts

The building blocks of Soniq.

- [Jobs](jobs.md) — define async functions as background jobs, configure retries, priorities, and timeouts
- [Queues](queues.md) — route jobs to named queues, control priority ordering, inspect queue stats
- [Workers](workers.md) — run job processors with configurable concurrency, heartbeat monitoring, and graceful shutdown
- [Retries](retries.md) — fixed delays, exponential backoff, per-attempt delay lists, and max retry limits
- [Scheduling](scheduling.md) — delay jobs to a future time, set up recurring cron-based tasks
- [Dead-letter queue](dead-letter.md) — inspect jobs that exhausted all retries, resurrect or delete them
