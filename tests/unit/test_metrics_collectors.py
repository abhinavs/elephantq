"""
Tests for metrics.py MetricsCollector in-memory behavior.

Covers: record_job_start, record_job_completion, get_recent_metrics,
calculate_throughput, get_processing_time_percentiles.
"""

import pytest

from soniq.features.metrics import MetricsCollector


class TestMetricsCollector:
    @pytest.mark.asyncio
    async def test_record_job_start(self):
        mc = MetricsCollector()
        await mc.record_job_start("job-1", "mod.task", "default")
        assert "job-1" in mc._job_metrics_index

    @pytest.mark.asyncio
    async def test_record_job_completion(self):
        mc = MetricsCollector()
        await mc.record_job_start("job-1", "mod.task", "default")
        await mc.record_job_completion("job-1", status="done", duration_ms=50.0)
        assert len(mc.job_metrics) == 1
        metric = mc.job_metrics[0]
        assert metric.status == "done"
        assert metric.duration_ms == 50.0

    @pytest.mark.asyncio
    async def test_record_job_completion_failure(self):
        mc = MetricsCollector()
        await mc.record_job_start("job-2", "mod.task", "default")
        await mc.record_job_completion("job-2", status="failed", duration_ms=10.0)
        assert len(mc.job_metrics) == 1

    @pytest.mark.asyncio
    async def test_get_recent_metrics(self):
        mc = MetricsCollector()
        await mc.record_job_start("j1", "mod.task", "default")
        await mc.record_job_completion("j1", status="done", duration_ms=50.0)
        await mc.record_job_start("j2", "mod.task", "default")
        await mc.record_job_completion("j2", status="done", duration_ms=30.0)

        recent = await mc.get_recent_metrics(minutes=60)
        assert len(recent) == 2

    @pytest.mark.asyncio
    async def test_calculate_throughput(self):
        mc = MetricsCollector()
        for i in range(5):
            await mc.record_job_start(f"j{i}", "mod.task", "default")
            await mc.record_job_completion(f"j{i}", status="done", duration_ms=10.0)

        throughput = await mc.calculate_throughput("default", minutes=60)
        assert throughput >= 0

    @pytest.mark.asyncio
    async def test_get_processing_time_percentiles(self):
        mc = MetricsCollector()
        for i in range(20):
            await mc.record_job_start(f"j{i}", "mod.task", "default")
            await mc.record_job_completion(
                f"j{i}", status="done", duration_ms=float(i * 10)
            )

        percentiles = await mc.get_processing_time_percentiles("default")
        assert "p50" in percentiles
        assert "p95" in percentiles
        assert "p99" in percentiles
