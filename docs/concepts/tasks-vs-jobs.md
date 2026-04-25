# Tasks vs. jobs

Soniq's API splits two related ideas. Knowing which one a name refers
to makes the surface easier to navigate and explains why
`task_name` and `job_id` live next to each other.

## The split

**Task** = the *named definition*. The recipe. A stable wire-protocol
identifier the producer side uses to address work without importing
the consumer's code.

**Job** = an *execution* of a task. A row in `soniq_jobs` with its own
status, attempt count, args payload, and result.

One task definition can produce many jobs. The same task name fires a
new job every time you `enqueue` it.

## Where each name shows up

| Term | Used for |
| --- | --- |
| `task_name` | The wire-protocol identifier (`"billing.send.v2"`). |
| `task_ref` / `TaskRef` | A typed reference to a task name, optionally with an `args_model` and `default_queue`. Sharable across services via a stub package. |
| `SONIQ_TASK_NAME_PATTERN` | Validation regex applied to explicit `name=` arguments. |
| `soniq_task_registry` | Observability table: which workers register which task names. Used by the dashboard and `soniq tasks check`. |
| `soniq tasks list` / `soniq tasks check` | CLI surfaces over the registry. |
| `soniq_jobs` | The work queue itself. Each row is one execution. |
| `JobContext`, `JobStatus` | Runtime objects describing an in-flight job. |
| `app.get_job(job_id)`, `app.list_jobs()`, `app.cancel_job(...)` | Operate on rows in `soniq_jobs`. |
| `Job not registered` | Dead-letter reason: a job arrived for a task name no worker registers. |

## The middle ground

A few names straddle, by historical accident, and aren't worth
breaking:

- `@app.job(name=...)` registers a *task definition* but uses the
  "job" prefix because the decorator also configures per-execution
  defaults (`max_retries`, `priority`, `timeout`).
- `JobRegistry` stores task definitions in-process. Same reason.
- `app.enqueue(...)` returns a `job_id` (the row's UUID), not a task
  name.

Treat these as one-name shorthand for "the thing the decorator
attaches to." The split between *named definition* and *execution row*
still applies; the decorator just owns both ends.

## Quick rule of thumb

- Talking about something that crosses the wire or lives in the
  registry table? It's a **task**.
- Talking about something with a status, an attempt count, or a UUID?
  It's a **job**.
