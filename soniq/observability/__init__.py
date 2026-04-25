"""
Pluggable observability surface for Soniq.

The `MetricsSink` Protocol formalizes the per-job metrics callbacks the
worker emits. The default is `NoopMetricsSink` (no observability
dependency required to run Soniq). To wire up Prometheus:

    from soniq import Soniq
    from soniq.observability import PrometheusMetricsSink

    app = Soniq(
        database_url="postgresql://localhost/myapp",
        metrics_sink=PrometheusMetricsSink(),
    )

`PrometheusMetricsSink` requires `pip install soniq[monitoring]`. It
lazy-imports `prometheus_client` so unused installations stay light.
"""

from .metrics import MetricsSink, NoopMetricsSink
from .prometheus import PrometheusMetricsSink

__all__ = ["MetricsSink", "NoopMetricsSink", "PrometheusMetricsSink"]
