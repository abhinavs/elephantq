"""
Tests that MetricsCollector uses O(1) dict index for job lookups.

Written to verify MED-06: linear scan replaced with dict index.
"""

import inspect

import pytest


class TestMetricsIndex:
    def test_has_job_metrics_index(self):
        from elephantq.features.metrics import MetricsCollector

        collector = MetricsCollector()
        assert hasattr(collector, "_job_metrics_index")
        assert isinstance(collector._job_metrics_index, dict)

    def test_record_completion_uses_index(self):
        """record_job_completion should use dict index, not linear scan."""
        from elephantq.features.metrics import MetricsCollector

        source = inspect.getsource(MetricsCollector.record_job_completion)
        assert (
            "for metric in" not in source
        ), "record_job_completion still uses linear scan"
        assert (
            "_job_metrics_index" in source
        ), "record_job_completion should use _job_metrics_index for O(1) lookup"

    @pytest.mark.asyncio
    async def test_record_and_complete_roundtrip(self):
        from elephantq.features.metrics import MetricsCollector

        collector = MetricsCollector()
        await collector.record_job_start("job-1", "test.task", "default")
        await collector.record_job_completion("job-1", "done", 150.0)

        # Verify the metric was updated
        metric = collector._job_metrics_index.get("job-1")
        assert metric is not None
        assert metric.status == "done"
        assert metric.duration_ms == 150.0
