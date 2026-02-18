"""
Performance Analytics and Monitoring.
System-wide performance analytics, success rates, processing times, queue statistics.
"""

import asyncio
import json
import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import asyncpg

from elephantq.db.context import get_context_pool


@dataclass
class JobMetrics:
    """Metrics for a single job execution"""

    job_id: str
    job_name: str
    queue: str
    status: str
    duration_ms: float
    memory_usage_mb: Optional[float] = None
    cpu_usage_percent: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class QueueStats:
    """Queue statistics"""

    queue_name: str
    queued_count: int
    processing_count: int
    done_count: int
    failed_count: int
    dead_letter_count: int
    avg_processing_time_ms: float
    success_rate: float
    throughput_per_minute: float


@dataclass
class SystemMetrics:
    """System-wide metrics"""

    total_jobs: int
    jobs_per_status: Dict[str, int]
    avg_processing_time_ms: float
    p95_processing_time_ms: float
    p99_processing_time_ms: float
    success_rate: float
    throughput_per_minute: float
    memory_usage_mb: float
    cpu_usage_percent: float
    queue_stats: List[QueueStats]
    top_slow_jobs: List[Dict]
    top_failed_jobs: List[Dict]


class MetricsCollector:
    """Real-time metrics collection and aggregation"""

    def __init__(self, retention_hours: int = 24):
        self.retention_hours = retention_hours
        self.job_metrics: deque = deque(maxlen=10000)  # In-memory buffer
        self.queue_throughput: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self.processing_times: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self._lock = asyncio.Lock()

    async def record_job_start(self, job_id: str, job_name: str, queue: str):
        """Record job start event"""
        async with self._lock:
            metric = JobMetrics(
                job_id=job_id,
                job_name=job_name,
                queue=queue,
                status="processing",
                duration_ms=0.0,
            )
            self.job_metrics.append(metric)

    async def record_job_completion(
        self,
        job_id: str,
        status: str,
        duration_ms: float,
        memory_usage_mb: Optional[float] = None,
        cpu_usage_percent: Optional[float] = None,
    ):
        """Record job completion event"""
        async with self._lock:
            # Find and update the job metric
            for metric in reversed(self.job_metrics):
                if metric.job_id == job_id:
                    metric.status = status
                    metric.duration_ms = duration_ms
                    metric.memory_usage_mb = memory_usage_mb
                    metric.cpu_usage_percent = cpu_usage_percent

                    # Record processing time and throughput
                    self.processing_times[metric.queue].append(duration_ms)
                    self.queue_throughput[metric.queue].append(time.time())
                    break

    async def get_recent_metrics(self, minutes: int = 60) -> List[JobMetrics]:
        """Get metrics from the last N minutes"""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return [m for m in self.job_metrics if m.timestamp >= cutoff]

    async def calculate_throughput(self, queue: str, minutes: int = 5) -> float:
        """Calculate jobs/minute throughput for a queue"""
        if queue not in self.queue_throughput:
            return 0.0

        cutoff = time.time() - (minutes * 60)
        recent_completions = [t for t in self.queue_throughput[queue] if t >= cutoff]
        return len(recent_completions) / minutes

    async def get_processing_time_percentiles(self, queue: str) -> Dict[str, float]:
        """Get processing time percentiles for a queue"""
        if queue not in self.processing_times or not self.processing_times[queue]:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}

        times = list(self.processing_times[queue])
        return {
            "p50": statistics.median(times),
            "p95": (
                statistics.quantiles(times, n=20)[18]
                if len(times) >= 20
                else max(times, default=0)
            ),
            "p99": (
                statistics.quantiles(times, n=100)[98]
                if len(times) >= 100
                else max(times, default=0)
            ),
        }


class MetricsAnalyzer:
    """Advanced metrics analysis and reporting"""

    def __init__(self, collector: MetricsCollector):
        self.collector = collector

    async def get_system_metrics(self, timeframe_hours: int = 1) -> SystemMetrics:
        """Get comprehensive system metrics"""
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            # Get job counts by status
            status_counts = await conn.fetch(
                """
                SELECT status, COUNT(*) as count
                FROM elephantq_jobs 
                WHERE created_at >= NOW() - INTERVAL '%s hours'
                GROUP BY status
            """,
                timeframe_hours,
            )

            jobs_per_status = {row["status"]: row["count"] for row in status_counts}
            total_jobs = sum(jobs_per_status.values())

            # Get processing time stats
            time_stats = await conn.fetchrow(
                """
                SELECT 
                    AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) * 1000) as avg_time_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (updated_at - created_at)) * 1000) as p95_time_ms,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (updated_at - created_at)) * 1000) as p99_time_ms
                FROM elephantq_jobs 
                WHERE status IN ('done', 'failed') 
                AND created_at >= NOW() - INTERVAL '%s hours'
            """,
                timeframe_hours,
            )

            # Calculate success rate
            done_count = jobs_per_status.get("done", 0)
            failed_count = jobs_per_status.get("failed", 0)
            total_completed = done_count + failed_count
            success_rate = (
                (done_count / total_completed * 100) if total_completed > 0 else 0.0
            )

            # Get queue stats
            queue_stats = await self._get_queue_stats(conn, timeframe_hours)

            # Get top slow jobs
            top_slow_jobs = await conn.fetch(
                """
                SELECT job_name, queue, 
                       EXTRACT(EPOCH FROM (updated_at - created_at)) * 1000 as duration_ms
                FROM elephantq_jobs 
                WHERE status IN ('done', 'failed')
                AND created_at >= NOW() - INTERVAL '%s hours'
                ORDER BY duration_ms DESC 
                LIMIT 10
            """,
                timeframe_hours,
            )

            # Get top failed jobs
            top_failed_jobs = await conn.fetch(
                """
                SELECT job_name, queue, COUNT(*) as failure_count,
                       array_agg(DISTINCT last_error) as error_messages
                FROM elephantq_jobs 
                WHERE status = 'failed'
                AND created_at >= NOW() - INTERVAL '%s hours'
                GROUP BY job_name, queue
                ORDER BY failure_count DESC 
                LIMIT 10
            """,
                timeframe_hours,
            )

            # Calculate system throughput
            throughput = (
                total_jobs / timeframe_hours * 60 if timeframe_hours > 0 else 0.0
            )

            return SystemMetrics(
                total_jobs=total_jobs,
                jobs_per_status=jobs_per_status,
                avg_processing_time_ms=float(time_stats["avg_time_ms"] or 0),
                p95_processing_time_ms=float(time_stats["p95_time_ms"] or 0),
                p99_processing_time_ms=float(time_stats["p99_time_ms"] or 0),
                success_rate=success_rate,
                throughput_per_minute=throughput,
                memory_usage_mb=await self._get_system_memory_usage(),
                cpu_usage_percent=await self._get_system_cpu_usage(),
                queue_stats=queue_stats,
                top_slow_jobs=[dict(row) for row in top_slow_jobs],
                top_failed_jobs=[dict(row) for row in top_failed_jobs],
            )

    async def _get_queue_stats(
        self, conn: asyncpg.Connection, timeframe_hours: int
    ) -> List[QueueStats]:
        """Get statistics for all queues"""
        queue_data = await conn.fetch(
            """
            SELECT 
                queue,
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) as queued_count,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing_count,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as done_count,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                SUM(CASE WHEN status = 'dead_letter' THEN 1 ELSE 0 END) as dead_letter_count,
                AVG(CASE WHEN status IN ('done', 'failed') 
                    THEN EXTRACT(EPOCH FROM (updated_at - created_at)) * 1000 
                    ELSE NULL END) as avg_processing_time_ms
            FROM elephantq_jobs 
            WHERE created_at >= NOW() - INTERVAL '%s hours'
            GROUP BY queue
        """,
            timeframe_hours,
        )

        stats = []
        for row in queue_data:
            done_count = row["done_count"]
            failed_count = row["failed_count"]
            total_completed = done_count + failed_count
            success_rate = (
                (done_count / total_completed * 100) if total_completed > 0 else 0.0
            )

            # Calculate throughput using collector data if available
            throughput = await self.collector.calculate_throughput(row["queue"], 60)

            stats.append(
                QueueStats(
                    queue_name=row["queue"],
                    queued_count=row["queued_count"],
                    processing_count=row["processing_count"],
                    done_count=done_count,
                    failed_count=failed_count,
                    dead_letter_count=row["dead_letter_count"],
                    avg_processing_time_ms=float(row["avg_processing_time_ms"] or 0),
                    success_rate=success_rate,
                    throughput_per_minute=throughput,
                )
            )

        return stats

    async def _get_system_memory_usage(self) -> float:
        """Get system memory usage in MB"""
        try:
            import psutil

            return psutil.virtual_memory().used / (1024 * 1024)
        except ImportError:
            return 0.0

    async def _get_system_cpu_usage(self) -> float:
        """Get system CPU usage percentage"""
        try:
            import psutil

            return psutil.cpu_percent(interval=1)
        except ImportError:
            return 0.0

    async def generate_performance_report(self, timeframe_hours: int = 24) -> Dict:
        """Generate a comprehensive performance report"""
        system_metrics = await self.get_system_metrics(timeframe_hours)

        # Analyze trends
        pool = await get_context_pool()
        async with pool.acquire() as conn:
            # Get hourly job completion trends
            hourly_trends = await conn.fetch(
                """
                SELECT 
                    DATE_TRUNC('hour', created_at) as hour,
                    COUNT(*) as job_count,
                    SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) as success_count
                FROM elephantq_jobs 
                WHERE created_at >= NOW() - INTERVAL '%s hours'
                GROUP BY hour
                ORDER BY hour
            """,
                timeframe_hours,
            )

            # Get error pattern analysis
            error_patterns = await conn.fetch(
                """
                SELECT 
                    last_error,
                    COUNT(*) as occurrence_count,
                    array_agg(DISTINCT job_name) as affected_jobs
                FROM elephantq_jobs 
                WHERE status = 'failed' 
                AND last_error IS NOT NULL
                AND created_at >= NOW() - INTERVAL '%s hours'
                GROUP BY last_error
                ORDER BY occurrence_count DESC
                LIMIT 20
            """,
                timeframe_hours,
            )

        return {
            "system_metrics": system_metrics,
            "hourly_trends": [dict(row) for row in hourly_trends],
            "error_patterns": [dict(row) for row in error_patterns],
            "recommendations": await self._generate_recommendations(system_metrics),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _generate_recommendations(self, metrics: SystemMetrics) -> List[str]:
        """Generate performance recommendations based on metrics"""
        recommendations = []

        # Check success rate
        if metrics.success_rate < 95:
            recommendations.append(
                f"Success rate is {metrics.success_rate:.1f}% - investigate error patterns"
            )

        # Check processing times
        if metrics.p95_processing_time_ms > 30000:  # 30 seconds
            recommendations.append(
                "95th percentile processing time is high - consider job optimization"
            )

        # Check queue backlogs
        for queue_stat in metrics.queue_stats:
            if queue_stat.queued_count > 1000:
                recommendations.append(
                    f"Queue '{queue_stat.queue_name}' has {queue_stat.queued_count} backlogged jobs"
                )

        # Check throughput
        if metrics.throughput_per_minute < 10:
            recommendations.append(
                "Low throughput - consider increasing worker concurrency"
            )

        # Check memory usage
        if metrics.memory_usage_mb > 4096:  # 4GB
            recommendations.append(
                f"High memory usage ({metrics.memory_usage_mb:.0f}MB) - monitor for memory leaks"
            )

        if not recommendations:
            recommendations.append("System performance is healthy")

        return recommendations


class AlertManager:
    """Performance alerting and notifications"""

    def __init__(self, analyzer: MetricsAnalyzer):
        self.analyzer = analyzer
        self.alert_thresholds = {
            "success_rate_min": 95.0,
            "p95_processing_time_max_ms": 30000,
            "queue_backlog_max": 1000,
            "throughput_min_per_minute": 10,
            "memory_usage_max_mb": 4096,
        }
        self.alert_cooldown = {}  # Prevent alert spam

    async def check_alerts(self) -> List[Dict]:
        """Check for alert conditions and return active alerts"""
        metrics = await self.analyzer.get_system_metrics(1)  # Last hour
        alerts = []
        current_time = time.time()

        # Success rate alert
        if metrics.success_rate < self.alert_thresholds["success_rate_min"]:
            alert_key = "low_success_rate"
            if self._should_send_alert(alert_key, current_time):
                alerts.append(
                    {
                        "type": "performance",
                        "severity": "high",
                        "title": "Low Success Rate",
                        "message": f"Success rate is {metrics.success_rate:.1f}% (threshold: {self.alert_thresholds['success_rate_min']}%)",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

        # Processing time alert
        if (
            metrics.p95_processing_time_ms
            > self.alert_thresholds["p95_processing_time_max_ms"]
        ):
            alert_key = "high_processing_time"
            if self._should_send_alert(alert_key, current_time):
                alerts.append(
                    {
                        "type": "performance",
                        "severity": "medium",
                        "title": "High Processing Time",
                        "message": f"95th percentile processing time is {metrics.p95_processing_time_ms:.0f}ms (threshold: {self.alert_thresholds['p95_processing_time_max_ms']}ms)",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

        # Queue backlog alerts
        for queue_stat in metrics.queue_stats:
            if queue_stat.queued_count > self.alert_thresholds["queue_backlog_max"]:
                alert_key = f"queue_backlog_{queue_stat.queue_name}"
                if self._should_send_alert(alert_key, current_time):
                    alerts.append(
                        {
                            "type": "capacity",
                            "severity": "high",
                            "title": f"Queue Backlog: {queue_stat.queue_name}",
                            "message": f"Queue has {queue_stat.queued_count} backlogged jobs (threshold: {self.alert_thresholds['queue_backlog_max']})",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )

        return alerts

    def _should_send_alert(
        self, alert_key: str, current_time: float, cooldown_minutes: int = 30
    ) -> bool:
        """Check if alert should be sent based on cooldown period"""
        last_sent = self.alert_cooldown.get(alert_key, 0)
        if current_time - last_sent > (cooldown_minutes * 60):
            self.alert_cooldown[alert_key] = current_time
            return True
        return False


# Global instances
_metrics_collector = MetricsCollector()
_metrics_analyzer = MetricsAnalyzer(_metrics_collector)
_alert_manager = AlertManager(_metrics_analyzer)


# Public API
async def record_job_start(job_id: str, job_name: str, queue: str):
    """Record job start for metrics collection"""
    await _metrics_collector.record_job_start(job_id, job_name, queue)


async def record_job_completion(
    job_id: str,
    status: str,
    duration_ms: float,
    memory_usage_mb: Optional[float] = None,
    cpu_usage_percent: Optional[float] = None,
):
    """Record job completion for metrics collection"""
    await _metrics_collector.record_job_completion(
        job_id, status, duration_ms, memory_usage_mb, cpu_usage_percent
    )


async def get_system_metrics(timeframe_hours: int = 1) -> SystemMetrics:
    """Get comprehensive system metrics"""
    return await _metrics_analyzer.get_system_metrics(timeframe_hours)


async def get_queue_stats(timeframe_hours: int = 1) -> List[QueueStats]:
    """Get statistics for all queues"""
    metrics = await get_system_metrics(timeframe_hours)
    return metrics.queue_stats


async def generate_performance_report(timeframe_hours: int = 24) -> Dict:
    """Generate a comprehensive performance report"""
    return await _metrics_analyzer.generate_performance_report(timeframe_hours)


async def check_performance_alerts() -> List[Dict]:
    """Check for performance alerts"""
    return await _alert_manager.check_alerts()


async def export_metrics_json(
    timeframe_hours: int = 24, file_path: str = "metrics_export.json"
):
    """Export metrics to JSON file"""
    report = await generate_performance_report(timeframe_hours)

    with open(file_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    return file_path


# Background metrics collection task
async def start_metrics_collection():
    """Start background metrics collection"""

    async def collection_loop():
        while True:
            try:
                # Periodic cleanup of old metrics
                cutoff = datetime.now(timezone.utc) - timedelta(
                    hours=_metrics_collector.retention_hours
                )
                _metrics_collector.job_metrics = deque(
                    [
                        m
                        for m in _metrics_collector.job_metrics
                        if m.timestamp >= cutoff
                    ],
                    maxlen=10000,
                )

                await asyncio.sleep(300)  # Clean up every 5 minutes
            except Exception as e:
                import logging

                logging.exception(f"Metrics collection error: {e}")
                await asyncio.sleep(60)

    return asyncio.create_task(collection_loop())
