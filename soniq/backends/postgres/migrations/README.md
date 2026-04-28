# Soniq Postgres migrations

Schema migrations for the Postgres backend. Files are named
`NNNN_short_name.sql`, applied in numeric order, and recorded in the
`soniq_migrations` table by `MigrationRunner`.

## Numbering convention

| Range       | Owner                                            |
|-------------|--------------------------------------------------|
| `0001-0099` | Soniq core (always applied by `Soniq.setup()`)   |
| `0100-8999` | Reserved for OSS plugins                         |
| `9000-9999` | Reserved for first-party commercial / soniq-pro  |

Within the core range:

| Version     | Feature       | Applied by                       |
|-------------|---------------|----------------------------------|
| `0001`      | core schema           | `Soniq.setup()`                  |
| `0002`      | DLQ option-A cleanup  | `Soniq.setup()`                  |
| `0003`      | dead-letter table     | `Soniq.setup()`                  |
| `0010`      | scheduler             | `Scheduler.setup()`              |
| `0021`      | webhooks              | `WebhookService.setup()`         |
| `0022`      | logs                  | `LogService.setup()`             |

`Soniq.setup()` only applies the `0001-0009` core slice. Optional
features apply their own slice on first use, or the operator can opt in
up front with `soniq setup --features=scheduler,webhooks,logs`.

Additive core changes (a new column or table that lives in the core
write path) get a new file in the `0002-0009` range, not an edit to
`0001_core.sql`. The baseline stays the baseline.

This is why a deployment that does not use webhooks does not get empty
`soniq_webhook_*` tables sitting in its database.

## Plugin migrations

Plugins ship their own `NNNN_*.sql` files inside their package and
register the directory through `app.migrations.register_source(path,
prefix=...)`. The runner discovers and applies them under the same
advisory-lock guard as core. Pick a prefix in the `0100-8999` range
that does not collide with other plugins.
