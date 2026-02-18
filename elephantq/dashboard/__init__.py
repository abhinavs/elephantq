"""Dashboard module for ElephantQ."""

from .app import (
    cancel_job,
    delete_job,
    get_job_details,
    get_job_metrics,
    get_job_stats,
    get_job_timeline,
    get_job_types_stats,
    get_queue_stats,
    get_recent_jobs,
    get_system_health,
    get_worker_stats,
    retry_job,
    search_jobs,
)
from .fastapi_app import create_dashboard_app, run_dashboard

__all__ = [
    "get_job_stats",
    "get_recent_jobs",
    "get_queue_stats",
    "get_job_metrics",
    "get_job_details",
    "retry_job",
    "delete_job",
    "cancel_job",
    "get_worker_stats",
    "get_job_timeline",
    "get_job_types_stats",
    "search_jobs",
    "get_system_health",
    "create_dashboard_app",
    "run_dashboard",
]
