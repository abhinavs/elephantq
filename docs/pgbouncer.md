# PgBouncer

ElephantQ can work with PgBouncer, but the pooling mode matters.

## Session mode (works)

In **session mode**, PgBouncer assigns a server connection for the lifetime of a client connection. This is compatible with ElephantQ because `LISTEN/NOTIFY` requires a persistent connection.

```ini
[pgbouncer]
pool_mode = session
```

No special configuration needed on the ElephantQ side.

## Transaction mode (breaks LISTEN/NOTIFY)

In **transaction mode**, PgBouncer returns the server connection to the pool after each transaction. This means `LISTEN` subscriptions are lost between transactions, and `NOTIFY` messages may not reach the intended listener.

**ElephantQ will not receive instant job notifications in transaction mode.** It will fall back to polling, which adds latency.

If you must use transaction mode:
- Expect higher job pickup latency (up to `ELEPHANTQ_NOTIFICATION_TIMEOUT` seconds, default 5).
- Consider running ElephantQ's connection directly to PostgreSQL (bypassing PgBouncer) while routing your application traffic through PgBouncer.

## Connection count math

ElephantQ uses connections for:

| Purpose | Connections | Lifetime |
| --- | --- | --- |
| Job processing | Up to `ELEPHANTQ_DEFAULT_CONCURRENCY` | Short (per job) |
| LISTEN/NOTIFY listener | 1 | Long-lived |
| Worker heartbeat | 1 | Periodic |
| Cleanup / scheduler | 1 (shared) | Periodic |

**Total per worker** = `concurrency + 2-3`

With the default concurrency of 4, budget ~7 connections per worker. The `ELEPHANTQ_DB_POOL_SAFETY_MARGIN` setting (default 2) accounts for the long-lived connections.

If you run 3 workers at concurrency 4, you need ~21 connections. Set PgBouncer's `max_client_conn` accordingly, and keep `default_pool_size` >= your total ElephantQ connection count.

## Recommendation

For most setups, point ElephantQ directly at PostgreSQL and use PgBouncer for your application's read-heavy queries. This avoids the LISTEN/NOTIFY limitation entirely.
