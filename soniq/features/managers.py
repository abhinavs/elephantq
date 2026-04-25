"""
Soniq Features - Organized into logical objects.
Groups related functionality into cohesive, easy-to-use classes.
"""

from typing import List, Optional

from .flags import require_feature


class WebhookManager:
    """
    Centralized webhook management for job lifecycle notifications.
    """

    def __init__(self):
        require_feature("webhooks_enabled", "Webhooks")
        from . import webhooks

        self._mod = webhooks

    async def start(self):
        """Start the webhook system"""
        return await self._mod.start_webhook_system()

    async def stop(self):
        """Stop the webhook system"""
        return await self._mod.stop_webhook_system()

    async def register_endpoint(
        self,
        url: str,
        events: Optional[List[str]] = None,
        secret: Optional[str] = None,
        **kwargs,
    ):
        """Register a new webhook endpoint"""
        return await self._mod.register_webhook(url, events, secret, **kwargs)

    async def unregister_endpoint(self, endpoint_id: str):
        """Unregister a webhook endpoint"""
        return await self._mod.unregister_webhook(endpoint_id)

    async def list_endpoints(self):
        """Get all registered webhook endpoints"""
        return await self._mod.get_webhook_endpoints()

    async def get_delivery_stats(self, hours: int = 24):
        """Get webhook delivery statistics"""
        return await self._mod.get_delivery_stats(hours)


class MetricsCollector:
    """
    Performance analytics and monitoring for job processing.
    """

    def __init__(self):
        require_feature("metrics_enabled", "Metrics")
        from . import metrics

        self._mod = metrics

    async def start_collection(self):
        """Start metrics collection"""
        return await self._mod.start_metrics_collection()

    async def get_system_metrics(self):
        """Get current system performance metrics"""
        return await self._mod.get_system_metrics()

    async def generate_performance_report(self, hours: int = 24):
        """Generate a comprehensive performance report"""
        return await self._mod.generate_performance_report(hours)

    async def check_alerts(self):
        """Check for performance alerts"""
        return await self._mod.check_performance_alerts()


class LoggingManager:
    """
    Structured logging management for production environments.
    """

    def __init__(self):
        require_feature("logging_enabled", "Logging")
        from . import logging as log_mod

        self._mod = log_mod

    def setup(self, format: str = "structured", level: str = "INFO"):
        """Setup structured logging"""
        return self._mod.setup_logging(format, level)

    def get_job_logger(
        self,
        job_id: str,
        job_name: str = "",
        queue: str = "default",
        attempt: int = 1,
        max_attempts: int = 3,
    ):
        """Get a logger for a specific job"""
        return self._mod.get_job_logger(job_id, job_name, queue, attempt, max_attempts)

    async def get_error_summary(self, hours: int = 24):
        """Get summary of errors in the specified time period"""
        return await self._mod.get_error_summary(hours)

    async def search_logs(
        self,
        query: str,
        job_id: Optional[str] = None,
        level: Optional[str] = None,
        hours: int = 24,
    ):
        """Search through structured logs"""
        return await self._mod.search_logs(query, job_id, level, hours)


class DeadLetterManager:
    """
    Dead letter queue management for failed jobs.
    """

    def __init__(self):
        require_feature("dead_letter_queue_enabled", "Dead letter queue")
        from . import dead_letter

        self._mod = dead_letter

    async def setup(self):
        """Setup the dead letter queue system"""
        return await self._mod.setup_dead_letter_queue()

    async def move_job(self, job_id: str, reason: Optional[str] = None):
        """Move a job to the dead letter queue"""
        return await self._mod.move_job_to_dead_letter(job_id, reason)  # type: ignore[arg-type]

    async def resurrect_job(self, job_id: str):
        """Resurrect a single job from dead letter queue"""
        return await self._mod.resurrect_job(job_id)

    async def resurrect_jobs(self, job_ids: List[str]):
        """Resurrect multiple jobs from dead letter queue"""
        return await self._mod.bulk_resurrect_jobs(job_ids)  # type: ignore[arg-type]

    async def list_jobs(self, limit: int = 50, offset: int = 0):
        """List jobs in the dead letter queue"""
        return await self._mod.list_dead_letter_jobs(limit, offset)  # type: ignore[arg-type, call-arg]

    async def get_stats(self):
        """Get dead letter queue statistics"""
        return await self._mod.get_dead_letter_stats()


class SigningManager:
    """
    Signing and encryption management for sensitive data.
    """

    def __init__(self):
        require_feature("signing_enabled", "Signing")
        from . import signing

        self._mod = signing

    def encrypt_secret(self, plaintext: str) -> str:
        """Encrypt a secret for secure storage"""
        return self._mod.encrypt_secret(plaintext)

    def decrypt_secret(self, ciphertext: str) -> str:
        """Decrypt a secret for use"""
        return self._mod.decrypt_secret(ciphertext)

    def get_manager(self):
        """Get the underlying secret manager"""
        return self._mod.get_secret_manager()


class SoniqFeatures:
    """
    Main Soniq features interface.

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
                "delivery_stats": await self.webhooks.get_delivery_stats(1),
            },
            "metrics": await self.metrics.get_system_metrics(),
            "dead_letter": await self.dead_letter.get_stats(),
            "logging": "active",
            "signing": "ready",
        }


# Singleton instance for easy access
features = SoniqFeatures()


# Convenience functions
async def setup_features():
    """Setup all optional features with one call"""
    return await features.setup_all()


async def get_features_status():
    """Get comprehensive status of all optional features"""
    return await features.get_status()
