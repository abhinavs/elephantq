"""
ElephantQ Features - Organized into logical objects.
Groups related functionality into cohesive, easy-to-use classes.
"""

from datetime import datetime
from typing import List, Optional

from .dead_letter import bulk_resurrect_jobs as _bulk_resurrect_jobs
from .dead_letter import get_dead_letter_stats as _get_dead_letter_stats
from .dead_letter import list_dead_letter_jobs as _list_dead_letter_jobs
from .dead_letter import move_job_to_dead_letter as _move_job_to_dead_letter
from .dead_letter import resurrect_job as _resurrect_job
from .dead_letter import setup_dead_letter_queue as _setup_dead_letter_queue
from .flags import require_feature
from .logging import get_error_summary as _get_error_summary
from .logging import get_job_logger as _get_job_logger
from .logging import search_logs as _search_logs
from .logging import setup_logging as _setup_logging
from .metrics import check_performance_alerts as _check_performance_alerts
from .metrics import generate_performance_report as _generate_performance_report
from .metrics import get_system_metrics as _get_system_metrics
from .metrics import start_metrics_collection as _start_metrics_collection
from .signing import decrypt_secret as _decrypt_secret
from .signing import encrypt_secret as _encrypt_secret
from .signing import get_secret_manager as _get_secret_manager

# Import individual feature modules
from .webhooks import get_delivery_stats as _get_delivery_stats
from .webhooks import get_webhook_endpoints as _get_webhook_endpoints
from .webhooks import register_webhook as _register_webhook
from .webhooks import start_webhook_system as _start_webhook_system
from .webhooks import stop_webhook_system as _stop_webhook_system
from .webhooks import unregister_webhook as _unregister_webhook


class WebhookManager:
    """
    Centralized webhook management for job lifecycle notifications.

    Provides a clean interface for managing webhook endpoints, deliveries,
    and signing without dealing with individual functions.
    """

    def __init__(self):
        require_feature("webhooks_enabled", "Webhooks")

    async def start(self):
        """Start the webhook system"""
        return await _start_webhook_system()

    async def stop(self):
        """Stop the webhook system"""
        return await _stop_webhook_system()

    async def register_endpoint(
        self, url: str, events: List[str] = None, secret: str = None, **kwargs
    ):
        """Register a new webhook endpoint"""
        return await _register_webhook(url, events, secret, **kwargs)

    async def unregister_endpoint(self, endpoint_id: str):
        """Unregister a webhook endpoint"""
        return await _unregister_webhook(endpoint_id)

    async def list_endpoints(self):
        """Get all registered webhook endpoints"""
        return await _get_webhook_endpoints()

    async def get_delivery_stats(self, hours: int = 24):
        """Get webhook delivery statistics"""
        return await _get_delivery_stats(hours)


class MetricsCollector:
    """
    Performance analytics and monitoring for job processing.

    Centralizes all metrics collection, reporting, and alerting functionality
    into a single, easy-to-use interface.
    """

    def __init__(self):
        require_feature("metrics_enabled", "Metrics")

    async def start_collection(self):
        """Start metrics collection"""
        return await _start_metrics_collection()

    async def get_system_metrics(self):
        """Get current system performance metrics"""
        return await _get_system_metrics()

    async def generate_performance_report(self, hours: int = 24):
        """Generate a comprehensive performance report"""
        return await _generate_performance_report(hours)

    async def check_alerts(self):
        """Check for performance alerts"""
        return await _check_performance_alerts()


class LoggingManager:
    """
    Structured logging management for production environments.

    Provides centralized access to job logs, error analysis, and log searching
    with proper structured logging setup.
    """

    def __init__(self):
        require_feature("logging_enabled", "Logging")

    def setup(self, format: str = "structured", level: str = "INFO"):
        """Setup structured logging"""
        return _setup_logging(format, level)

    def get_job_logger(self, job_id: str):
        """Get a logger for a specific job"""
        return _get_job_logger(job_id)

    async def get_error_summary(self, hours: int = 24):
        """Get summary of errors in the specified time period"""
        return await _get_error_summary(hours)

    async def search_logs(
        self,
        query: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ):
        """Search through structured logs"""
        return await _search_logs(query, start_time, end_time, limit)


class DeadLetterManager:
    """
    Dead letter queue management for failed jobs.

    Handles job failures, analysis, resurrection, and cleanup in a cohesive
    interface without scattered function calls.
    """

    def __init__(self):
        require_feature("dead_letter_queue_enabled", "Dead letter queue")

    async def setup(self):
        """Setup the dead letter queue system"""
        return await _setup_dead_letter_queue()

    async def move_job(self, job_id: str, reason: str = None):
        """Move a job to the dead letter queue"""
        return await _move_job_to_dead_letter(job_id, reason)

    async def resurrect_job(self, job_id: str):
        """Resurrect a single job from dead letter queue"""
        return await _resurrect_job(job_id)

    async def resurrect_jobs(self, job_ids: List[str]):
        """Resurrect multiple jobs from dead letter queue"""
        return await _bulk_resurrect_jobs(job_ids)

    async def list_jobs(self, limit: int = 50, offset: int = 0):
        """List jobs in the dead letter queue"""
        return await _list_dead_letter_jobs(limit, offset)

    async def get_stats(self):
        """Get dead letter queue statistics"""
        return await _get_dead_letter_stats()


class SigningManager:
    """
    Signing and encryption management for sensitive data.

    Centralizes signing-related functionality including secret encryption,
    key management, and secure storage.
    """

    def __init__(self):
        require_feature("signing_enabled", "Signing")

    def encrypt_secret(self, plaintext: str) -> str:
        """Encrypt a secret for secure storage"""
        return _encrypt_secret(plaintext)

    def decrypt_secret(self, ciphertext: str) -> str:
        """Decrypt a secret for use"""
        return _decrypt_secret(ciphertext)

    def get_manager(self):
        """Get the underlying secret manager"""
        return _get_secret_manager()


class ElephantQFeatures:
    """
    Main ElephantQ features interface.

    This is the primary entry point for all optional functionality,
    providing organized access to all feature managers.
    """

    def __init__(self):
        self._webhooks: Optional[WebhookManager] = None
        self._metrics: Optional[MetricsCollector] = None
        self._logging: Optional[LoggingManager] = None
        self._dead_letter: Optional[DeadLetterManager] = None
        self._signing: Optional[SigningManager] = None

    @property
    def webhooks(self) -> WebhookManager:
        if self._webhooks is None:
            self._webhooks = WebhookManager()
        return self._webhooks

    @property
    def metrics(self) -> MetricsCollector:
        if self._metrics is None:
            self._metrics = MetricsCollector()
        return self._metrics

    @property
    def logging(self) -> LoggingManager:
        if self._logging is None:
            self._logging = LoggingManager()
        return self._logging

    @property
    def dead_letter(self) -> DeadLetterManager:
        if self._dead_letter is None:
            self._dead_letter = DeadLetterManager()
        return self._dead_letter

    @property
    def signing(self) -> SigningManager:
        if self._signing is None:
            self._signing = SigningManager()
        return self._signing

    async def setup_all(self):
        """Setup all optional features"""
        await self.webhooks.start()
        await self.metrics.start_collection()
        await self.dead_letter.setup()
        self.logging.setup()

        return {
            "webhooks": "started",
            "metrics": "collecting",
            "dead_letter": "ready",
            "logging": "configured",
            "signing": "available",
        }

    async def get_status(self):
        """Get status of all optional features"""
        return {
            "webhooks": {
                "endpoints": len(await self.webhooks.list_endpoints()),
                "delivery_stats": await self.webhooks.get_delivery_stats(
                    1
                ),  # Last hour
            },
            "metrics": await self.metrics.get_system_metrics(),
            "dead_letter": await self.dead_letter.get_stats(),
            "logging": "active",
            "signing": "ready",
        }


# Singleton instance for easy access
features = ElephantQFeatures()

# Backward-compatible alias
EnterpriseFeatures = ElephantQFeatures
enterprise = features


# Convenience functions that use the organized objects
async def setup_features():
    """Setup all optional features with one call"""
    return await features.setup_all()


async def get_features_status():
    """Get comprehensive status of all optional features"""
    return await features.get_status()


# Backward compatibility
async def setup_enterprise_features():
    """Legacy alias for setup_features()"""
    return await setup_features()


async def get_enterprise_status():
    """Legacy alias for get_features_status()"""
    return await get_features_status()
