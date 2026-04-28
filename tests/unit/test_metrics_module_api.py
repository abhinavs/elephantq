"""
Module-level metrics wrappers fail cleanly without an app.

The legacy ``soniq.features.metrics.get_system_metrics`` (and friends)
construct a ``_metrics_analyzer`` at import time without an ``app``
argument. ``MetricsAnalyzer._acquire`` requires an explicit app since
the global-app fallback was removed for instance-boundary correctness.

After B3 lands, calling these wrappers from cold (no app constructed)
must either succeed (with explicit app argument) or raise a clear
``MetricsRequiresApp``-style error - never the accidental
``_acquire``-needs-app traceback. The cleanest resolution is to remove
the wrappers entirely; this test then asserts the symbols are gone.
"""

from __future__ import annotations


def test_module_level_db_backed_wrappers_are_removed():
    """The module-level DB-backed wrappers should not exist on the
    ``soniq.features.metrics`` module surface. Use ``MetricsService(app)``."""
    import soniq.features.metrics as metrics_mod

    removed = [
        "get_system_metrics",
        "get_queue_stats",
        "generate_performance_report",
        "_metrics_analyzer",
        "_alert_manager",
    ]
    leaked = [name for name in removed if hasattr(metrics_mod, name)]
    assert not leaked, (
        "These DB-backed module-level metrics symbols should be removed; "
        "use MetricsService(app) instead. Still present: "
        f"{leaked}"
    )
