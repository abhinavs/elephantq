# Extracting a feature into a plugin

Soniq's first-party features (webhooks, dead-letter, scheduler, logs,
signing, dashboard, metrics) are deliberately **not** plugins. They
ship as part of Soniq core because they share migrations, settings,
and schema with everything else, and because `app.webhooks.register(...)`
is one obvious property access where `app.plugins["webhooks"].register(...)`
is two.

But there's still a discipline question: *is the public plugin
contract good enough for an outside author?* The honest answer comes
from extracting one of our own features into a real plugin and seeing
whether the public surface holds.

## The commitment

Between 0.0.2 and 0.1.0, Soniq will extract **the Prometheus
`MetricsSink`** into a separate, externally-published PyPI package
that uses the same `SoniqPlugin` contract any third-party author
would.

| Item | Value |
| --- | --- |
| Feature to extract | Prometheus `MetricsSink` (today: `soniq.observability.PrometheusMetricsSink`) |
| New PyPI package | `soniq-prometheus` (separate repo, separate release cycle) |
| Target version | `soniq` 0.1.0 |
| Owners | Soniq core team |

## Why Prometheus first

Three reasons it is the cleanest first extraction:

1. **Already a Protocol implementation.** `MetricsSink` is a
   `@runtime_checkable` Protocol; `PrometheusMetricsSink` already
   plugs in via `app.metrics_sink = ...`. The seam exists; the
   extraction is mostly packaging.
2. **External dependency.** Prometheus support requires
   `prometheus_client`. Today that's an optional extra
   (`soniq[observability]`); tomorrow it's a separate package
   operators install only when they want it. Cleaner story.
3. **Smallest code surface.** ~250 LOC plus tests. Big enough to
   meaningfully exercise the contract, small enough that the
   extraction can land in a single PR with no ambiguity.

## Why not webhooks / scheduler

Webhooks and the recurring scheduler are tied to Soniq's database
schema (the `soniq_webhook_*` and `soniq_recurring_jobs` tables). A
plugin extraction would force them to ship migrations, register
dashboard panels, and settle their own table-prefix range. That's
real work, but it's *plugin authoring* work, not "test the contract"
work - it would conflate the two questions.

Dead-letter handling is **not** a plugin candidate at all. The worker
calls `mark_job_dead_letter` from inside the retry-exhaustion branch.
It's load-bearing for the job state machine; making it optional would
be a contradiction.

## What "good enough" means

If the Prometheus extraction can land **without expanding the public
plugin contract**, the contract is sufficient and we're done. If it
needs new public API to work, that API ships in the same release as
the extraction so the validation is real - not "we added a new hook
just for our own plugin".

The tests that matter:

- The plugin installs and runs against a regular `Soniq` with no
  changes to core.
- The extraction doesn't move any `_`-prefixed names into the public
  surface.
- The plugin's `pyproject.toml` pins a sane `soniq>=0.x.x,<0.y.y`
  range and survives a Soniq patch release without changes.
- Soniq's own CI imports and exercises the plugin (one smoke test in
  `tests/integration/test_example_plugin_installs.py` already does
  this for the example plugin; the extraction adds a Prometheus
  variant).

## What this does for users

Today (0.0.2):

```python
from soniq.observability import PrometheusMetricsSink

app = Soniq(database_url=..., metrics_sink=PrometheusMetricsSink())
```

After 0.1.0:

```bash
pip install soniq-prometheus
```

```python
from soniq_prometheus import PrometheusPlugin

app = Soniq(database_url=..., plugins=[PrometheusPlugin()])
# or, if the plugin is registered as an entry point:
#   SONIQ_PLUGINS=prometheus soniq start
```

The Soniq import stops mentioning Prometheus; the plugin handles its
own dependency, its own settings, and its own release cadence.

## Tracking

This page is the source of truth for the commitment. When the
extraction lands, this document gets a "Status: complete" header and
the changelog points to the new PyPI package. If the date target
slips, the slip is recorded here with a reason.

**Status:** planned, target Soniq 0.1.0.
