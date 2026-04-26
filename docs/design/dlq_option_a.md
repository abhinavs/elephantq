# DLQ Option A: design notes

Status: locked for 0.0.3 (alpha; one-way; no transitional shims).

This is the engineering design doc behind the user-facing [`../contracts/dead_letter.md`](../contracts/dead_letter.md). The contract states **what** the DLQ semantics are; this doc covers the **how** and the **why**, plus the migration body and the failure-mode catalogue that operators and reviewers need.

## 1. State transition diagram

Every legal transition for a job, with the SQL operation that effects it. Disallowed transitions are listed below the diagram and are enforced by CHECK constraints (postgres), triggers (sqlite), and Python assertions (memory).

```
soniq_jobs(queued)        --claim-->     soniq_jobs(processing)
soniq_jobs(processing)    --done-->      soniq_jobs(done)
soniq_jobs(processing)    --retry-->     soniq_jobs(queued)         [attempts++]
soniq_jobs(processing)    --cancel-->    soniq_jobs(cancelled)
soniq_jobs(processing)    --DLQ-->       soniq_dead_letter_jobs     [INSERT+DELETE in one tx; row removed from soniq_jobs]
soniq_dead_letter_jobs    --replay-->    soniq_jobs(queued, fresh id, attempts=0)   [DLQ row preserved; resurrection_count++]
soniq_dead_letter_jobs    --purge-->     (deleted)
```

### Disallowed transitions (rejected by the schema)

- `done -> queued` - terminal states do not regress. Replay creates a **new** row; it does not move the original.
- `cancelled -> processing` - cancellation is final.
- `done -> processing`, `cancelled -> queued`, `cancelled -> done` - same reasoning.
- `* -> dead_letter` (on `soniq_jobs`) - the value is **gone** from the enum. Writing it is rejected:
  - **Postgres**: CHECK constraint on `soniq_jobs.status` excludes `dead_letter`. The 0.0.3 migration adds a defensive CHECK re-asserting this.
  - **SQLite**: a `BEFORE INSERT OR UPDATE` trigger on `soniq_jobs` raises when `NEW.status = 'dead_letter'`.
  - **Memory**: the in-Python write paths (insert, transition update) raise `ValueError` if the value is `'dead_letter'`.
- `soniq_dead_letter_jobs(*) -> soniq_jobs(processing)` - replay always lands as `queued` with `attempts=0`. There is no "skip the queue and start running" path.

The `soniq_jobs.status` allowed set in 0.0.3 is exactly: `queued`, `processing`, `done`, `cancelled`. Four values.

## 2. Migration plan

The 0.0.3 migration is a **single migration containing destructive cleanup + schema tightening** - not DDL-only. It lives at `soniq/backends/postgres/migrations/00XX_dead_letter_option_a.sql` (the next number in the series).

Migration body:

1. `DELETE FROM soniq_jobs WHERE status='dead_letter'` - any pre-existing alpha rows in this state are dropped. This is the **destructive cleanup** step.
2. Drop the `dead_letter` value from the `soniq_jobs.status` CHECK constraint or enum type. Add a defensive CHECK that the column never accepts `dead_letter` again. This is the **schema tightening** step.
3. Idempotent: re-running on a clean post-migration DB is a no-op (the DELETE matches zero rows; the CHECK constraint already excludes the value).

What the migration does **not** do:

- No `INSERT ... SELECT FROM soniq_jobs WHERE status='dead_letter' INTO soniq_dead_letter_jobs`. There is no data backfill. v7 had this; v8+ removed it under the alpha-no-compat decision.
- No `LOCK TABLE` ceremony.
- No batched copy.
- No preflight gate (no `--i-have-a-backup` flag). The migration CLI runs without ceremony.

### Why "destructive cleanup + schema tightening" and not "DDL only"

The migration contains a `DELETE` statement against user data. Calling it "DDL only" misrepresents what runs. Operators reading the migration must understand that any `soniq_jobs.status='dead_letter'` rows on their alpha install **are deleted** when the migration runs. v7 documents the destructive step; v8+ keeps that wording. CHANGELOG flags it in **bold** under the alpha-context destructive items list.

### Pre-upgrade hand-off (operator-side)

Operators who care about preserving pre-existing `dead_letter` rows must hand-export them **before upgrading to 0.0.3**:

- On the still-running 0.0.2 code, call `DeadLetterService.move()` (it still exists at 0.0.2; gone at 0.0.3) or hit the schema with direct SQL.
- After installing 0.0.3, `move()` is gone and the migration has not yet run. The only escape is direct SQL against the still-pre-migration schema. Once the migration runs, those rows are gone.

This is the entire migration UX. It is intentionally bare for alpha.

### Backend asymmetry

- **Postgres**: the migration described above runs.
- **SQLite**: ships fresh in 0.0.3 with the new schema (no in-the-wild 0.0.2 sqlite users to migrate). The rejection trigger is part of the schema bootstrap, not a separate migration.
- **Memory**: no persistent state to migrate. The Python `ValueError` is added to the write paths; that is the entire change.

This asymmetry is documented in the contract doc. It is the reason Group B (postgres-only migration tests) exists alongside Group A (cross-backend API parity).

## 3. Rollback policy (alpha): one-way

**Downgrade is not supported in 0.0.3.**

- No legacy-compat flag (`SONIQ_ALLOW_LEGACY_DLQ_STATUS` was on the table in v5; v6+ dropped it).
- No downgrade migration shipped.
- No backup preflight in the migration CLI.
- Operators on alpha installs who want to roll back must restore from their own backup. The CHANGELOG says so plainly, in bold, alongside the destructive-cleanup callout.

Rationale: alpha = no transitional compatibility paths. A two-way migration would require either preserving the `dead_letter` value in the enum (defeating the schema-tightening purpose) or shipping reverse-direction code (defeating the no-shim rule). Either path is more code than the alpha contract justifies.

After 0.0.3 ships and the API is on its way to 1.0, a forward-only-but-supported migration story replaces this. For 0.0.3 specifically: one-way.

## 4. Move transaction failure modes

The runtime move (`mark_job_dead_letter`) is `BEGIN; INSERT INTO soniq_dead_letter_jobs ... SELECT FROM soniq_jobs WHERE id = $1 FOR UPDATE; DELETE FROM soniq_jobs WHERE id = $1; COMMIT`. It runs inside one transaction; the row exists in exactly one table at any consistent read.

| Failure scenario | Outcome | Recovery |
| --- | --- | --- |
| Connection dies between INSERT and DELETE (postgres) | Postgres rolls back the open transaction. No DLQ row, no missing source row. | The job remains in `processing` on the original `soniq_jobs` row. Stale-worker recovery requeues it after the heartbeat-stale window; the runtime path runs again on a fresh worker; eventually the move commits. |
| Worker process crashes mid-call | Same as connection-dies (the postgres connection is reset; the open tx is rolled back). | Same: stale-recovery requeue, retry on next worker. |
| INSERT succeeds, DELETE deadlocks | Transaction rolls back (both statements undone). | Same as above; deadlock is observed by the worker as a transient failure; retried by stale-recovery. |
| INSERT fails (duplicate primary key, e.g. replay collision) | Transaction rolls back. The DLQ row's primary key equals the source `soniq_jobs.id`; collisions can only happen if the same id was already moved (would indicate a logic bug in the worker, not a normal path). | Logged as an error; the source row remains; manual operator inspection. The integration test `test_dlq_runtime_move_atomicity` asserts no duplicate state. |
| DLQ table "full" | Not a real failure mode in postgres or sqlite; there is no row-count cap. Disk full is a separate concern (the DB raises out-of-disk; same recovery as any other DB outage). | Operators size the DLQ for their failure-rate budget. P1.2 adds retention/partitioning to bound long-term growth. |
| Memory backend mid-call exception | The in-memory move is wrapped in a try/except that restores the prior state on any exception. | Same observable contract: no duplicate, no loss. |
| SQLite SAVEPOINT rollback | sqlite uses an explicit transaction; on the injected fault, SAVEPOINT rolls back to the pre-INSERT state. | Same observable contract. |

The integration test `test_dlq_mid_transaction_crash` (Group A; runs on all three backends) injects a fault between INSERT and DELETE on each backend (postgres: connection drop; sqlite: SAVEPOINT rollback; memory: monkey-patched failure) and asserts: no duplicate state, no loss. Eventual-consistency via stale-recovery is acceptable; the contract is "exactly one of: pre-move state, post-move state" at any consistent read.

## 5. Why Option A (recap)

The existing `0020_dead_letter.sql` schema already carries all the DLQ-row columns we need (`dead_letter_reason`, `tags`, `resurrection_count`, `last_resurrection_at`, `original_created_at`, `moved_to_dead_letter_at`). Option A is mostly a wiring + migration job, not a schema redesign. It also removes terminal-state churn from the hot `soniq_jobs` table immediately, which is a free win for P1.2 (retention/partitioning).

## 6. Cross-references

- User-facing contract: [`../contracts/dead_letter.md`](../contracts/dead_letter.md).
- Stats contract that consumes the DLQ table: [`../contracts/queue_stats.md`](../contracts/queue_stats.md).
- Plan sections: P0.2 (Option A wiring), B4 (test matrix split into Group A / Group B), v8 alpha-no-compat decisions, v8.1 destructive-cleanup wording, v8.5 pre-upgrade `move()` scoping.
