"""Dashboard module for Soniq."""

from .app import DashboardService
from .fastapi_app import create_dashboard_app, run_dashboard

__all__ = [
    "DashboardService",
    "create_dashboard_app",
    "run_dashboard",
]
