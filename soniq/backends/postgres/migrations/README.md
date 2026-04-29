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

| Version | File                            | Applied by      |
|---------|---------------------------------|-----------------|
| `0001`  | `0001_core.sql`                 | `Soniq.setup()` |
| `0002`  | `0002_dead_letter_option_a.sql` | `Soniq.setup()` |
| `0003`  | `0003_dead_letter.sql`          | `Soniq.setup()` |
| `0004`  | `0004_scheduler.sql`            | `Soniq.setup()` |
| `0005`  | `0005_webhooks.sql`             | `Soniq.setup()` |
| `0006`  | `0006_logs.sql`                 | `Soniq.setup()` |
| `0007`  | `0007_drop_failed_status.sql`   | `Soniq.setup()` |

`Soniq.setup()` applies the `0001-0099` core slice. There is no
`--features` flag any more: 0.0.3 always creates every soniq-owned table
on first setup. Tables that the deployment never writes to stay empty
and cost ~16KB each, which we trade for a smaller mental surface
(`setup()` either ran or it didn't).

### What "DLQ Option A cleanup" means (`0002`)

`docs/contracts/dead_letter.md` settled on Option A: dead-lettered jobs
live in the dedicated `soniq_dead_letter_jobs` table, never as a
`status='dead_letter'` row in `soniq_jobs`. The `0002` migration enforces
that contract on the schema by:

1. Deleting any pre-existing `soniq_jobs` rows with
   `status='dead_letter'` (one-way; export beforehand if you need them).
2. Replacing the column-level `CHECK` on `soniq_jobs.status` with one
   that excludes `'dead_letter'`, plus a named guard constraint
   (`soniq_jobs_status_no_dead_letter`) so the contract is visible in
   `pg_constraint`.

The DLQ table itself is `0003`, not `0002` - keeping the schema
tightening separate from the table creation makes the intent of each
migration legible at a glance.

### What "drop failed status" means (`0007`)

`docs/contracts/job_lifecycle.md` pins the live `soniq_jobs.status`
values to `queued / processing / done / cancelled`. Failures either
re-queue (status flips back to `queued`) or move into
`soniq_dead_letter_jobs`; there is no `failed` row state. `0007`
reconciles legacy installs by:

1. Re-queuing any pre-existing `status='failed'` rows so the rebuilt
   `CHECK` does not reject them.
2. Replacing the column-level `CHECK` on `soniq_jobs.status` (and
   dropping the redundant `soniq_jobs_status_no_dead_letter` guard
   that `0002` added) with a single constraint pinning the four live
   values.

### Additive core changes

Additive core changes (a new column or table that lives in the core
write path) get a new file in the next free `00NN` slot, not an edit
to `0001_core.sql`. The baseline stays the baseline.

## Plugin migrations

Plugins ship their own `NNNN_*.sql` files inside their package and
register the directory through `app.migrations.register_source(path,
prefix=...)`. The runner discovers and applies them under the same
advisory-lock guard as core. Pick a prefix in the `0100-8999` range
that does not collide with other plugins.
