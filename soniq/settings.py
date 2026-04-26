"""
Soniq Configuration Management

Uses Pydantic v2 BaseSettings for robust, type-safe configuration with support for
environment variables, config files, and validation.
"""

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import EnvSettingsSource


class CustomEnvSource(EnvSettingsSource):
    """Custom environment source that handles comma-separated lists without JSON parsing."""

    def prepare_field_value(
        self, field_name: str, field: Any, value: Any, value_is_complex: bool
    ) -> Any:
        """Override to handle comma-separated lists for specific fields."""
        if field_name == "queues" and isinstance(value, str):
            # Handle comma-separated queues without JSON parsing
            return [q.strip() for q in value.split(",") if q.strip()]
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class SoniqSettings(BaseSettings):
    """
    Soniq configuration with environment variable support and validation.

    Configuration priority:
    1. Environment variables (SONIQ_*)
    2. Config file (if specified)
    3. Default values
    """

    model_config = SettingsConfigDict(
        env_prefix="SONIQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Use custom environment source."""
        return (
            init_settings,
            CustomEnvSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    # Database Configuration
    database_url: str = Field(
        default="postgresql://postgres@localhost/soniq",
        description="PostgreSQL database URL for Soniq",
    )

    # Job Discovery
    jobs_module: str = Field(
        default="jobs", description="Module name for automatic job discovery"
    )
    jobs_modules: str = Field(
        default="",
        description=(
            "Comma-separated list of modules to import on worker startup "
            "(e.g. 'my_app.tasks,my_app.other_tasks')"
        ),
    )

    # Worker Configuration
    concurrency: int = Field(
        default=4, ge=1, le=100, description="Default number of concurrent workers"
    )

    queues: List[str] = Field(
        default=["default"],
        description="Default queues to process (when not using dynamic discovery)",
    )

    # Job Processing Settings
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Default maximum retry attempts for failed jobs",
    )

    priority: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Default job priority (lower = higher priority)",
    )

    enqueue_validation: Literal["strict", "warn", "none"] = Field(
        default="strict",
        description=(
            "How enqueue() handles a string name that is not registered locally. "
            "'strict' raises SONIQ_UNKNOWN_TASK_NAME (default; loud at the call site). "
            "'warn' emits a rate-limited WARN and proceeds (for producer services that "
            "cannot validate locally). 'none' is silent. Does not apply when enqueue() "
            "is called with a TaskRef; that path validates against args_model."
        ),
    )

    task_name_pattern: str = Field(
        default=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$",
        description=(
            "Regex enforced on every task name at @app.job(name=) registration and "
            "at enqueue() call time. Default rejects spaces, capitalisation, leading "
            "dots. Override for teams with existing conventions."
        ),
    )

    producer_id: str = Field(
        default="auto",
        description=(
            "Identifier stamped on every row this instance enqueues, for "
            "observability ('who enqueued this poison message?'). 'auto' "
            "resolves to <hostname>:<pid>:<argv0> the first time a producer_id "
            "is needed. Set explicitly (e.g. 'billing-api') for cleaner "
            "dashboards in multi-deployment topologies."
        ),
    )

    route_map: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Consumer-side prefix-to-queue routing. When a job is registered "
            "without an explicit queue=, the longest matching prefix in this "
            "dict determines the queue the consumer's worker polls for that "
            "name. Producer queue= overrides ride on top of the row, not on "
            "this map (the producer is unaware of consumer routing - this is "
            "consumer-side only). Example: "
            "{'billing.': 'billing-queue', 'reports.': 'reports-queue'}."
        ),
    )

    # Feature Flags (all disabled by default)
    dashboard_enabled: bool = Field(
        default=False, description="Enable the Soniq dashboard"
    )
    dashboard_write_enabled: bool = Field(
        default=False,
        description="Enable write actions (retry/delete/cancel) in the dashboard",
    )
    scheduling_enabled: bool = Field(
        default=False, description="Enable advanced scheduling and recurring jobs"
    )
    dead_letter_queue_enabled: bool = Field(
        default=False, description="Enable dead-letter queue features"
    )
    metrics_enabled: bool = Field(
        default=False, description="Enable metrics collection features"
    )
    logging_enabled: bool = Field(
        default=False, description="Enable structured logging features"
    )
    webhooks_enabled: bool = Field(
        default=False, description="Enable webhook notifications"
    )
    timeouts_enabled: bool = Field(
        default=False, description="Enable job timeout processing"
    )
    signing_enabled: bool = Field(
        default=False, description="Enable signing and secret helpers"
    )

    # Timeouts and Intervals
    heartbeat_interval: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Worker heartbeat check interval in seconds",
    )

    job_timeout: Optional[float] = Field(
        default=300.0,
        ge=1.0,
        description="Default job execution timeout in seconds (None or 0 to disable)",
    )

    # Worker Processing Intervals
    cleanup_interval: float = Field(
        default=300.0,
        ge=10.0,
        le=3600.0,
        description="Interval for cleaning up expired jobs and stale workers (seconds)",
    )

    heartbeat_timeout: float = Field(
        default=300.0,
        ge=60.0,
        le=7200.0,
        description="Time after which workers are considered stale (seconds)",
    )

    poll_interval: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Timeout when waiting for job notifications (seconds)",
    )

    error_retry_delay: float = Field(
        default=5.0,
        ge=0.1,
        le=300.0,
        description="Delay before retrying after worker errors (seconds)",
    )

    # Health Monitoring Settings
    health_check_timeout: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Default timeout for health checks (seconds)",
    )

    health_monitoring_interval: float = Field(
        default=30.0,
        ge=1.0,
        le=3600.0,
        description="Interval for health monitoring loops (seconds)",
    )

    health_error_retry_delay: float = Field(
        default=5.0,
        ge=0.1,
        le=300.0,
        description="Delay before retrying health checks after errors (seconds)",
    )

    # Health Check Thresholds
    stuck_jobs_threshold: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Number of stuck jobs that triggers health warning",
    )

    job_failure_rate_threshold: float = Field(
        default=50.0,
        ge=0.0,
        le=100.0,
        description="Job failure rate percentage that triggers health degradation",
    )

    memory_usage_threshold: float = Field(
        default=90.0,
        ge=50.0,
        le=99.0,
        description="Memory usage percentage that triggers health warning",
    )

    disk_usage_threshold: float = Field(
        default=90.0,
        ge=50.0,
        le=99.0,
        description="Disk usage percentage that triggers health warning",
    )

    cpu_usage_threshold: float = Field(
        default=95.0,
        ge=50.0,
        le=99.0,
        description="CPU usage percentage that triggers health warning",
    )

    # CLI and Display Settings
    display_limit: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Default number of jobs to display in CLI commands",
    )

    @field_validator("job_timeout", mode="before")
    @classmethod
    def parse_job_timeout(cls, v):
        """Parse job timeout value, converting 0 to None (no timeout)."""
        if v == "0" or v == 0:
            return None
        return v

    # Connection Pool Settings
    pool_min_size: int = Field(
        default=5, ge=1, le=100, description="Minimum database connection pool size"
    )

    pool_max_size: int = Field(
        default=20, ge=1, le=200, description="Maximum database connection pool size"
    )

    pool_headroom: int = Field(
        default=2,
        ge=0,
        le=50,
        description="Extra connections reserved beyond worker concurrency (listener/heartbeat)",
    )

    # Logging Configuration
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    log_format: str = Field(
        default="simple", description="Log format: 'simple' or 'structured'"
    )

    # Job Result Retention (TTL)
    result_ttl: int = Field(
        default=300,
        ge=0,
        description="Time to live for completed jobs in seconds (0=delete immediately, default=300 for 5 minutes)",
    )

    # Snooze
    snooze_max_seconds: float = Field(
        default=24 * 3600,
        gt=0,
        description="Upper bound on Snooze(seconds=...) before the value is capped, preventing handlers from scheduling jobs arbitrarily far in the future",
    )

    # Development/Testing
    debug: bool = Field(default=False, description="Enable debug mode")

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, v):
        """Parse debug value from environment variables, handling empty strings."""
        if isinstance(v, str):
            if v.lower() in ("", "0", "false", "f", "no", "n"):
                return False
            elif v.lower() in ("1", "true", "t", "yes", "y"):
                return True
        return v

    environment: str = Field(
        default="production",
        description="Environment name (development, testing, production)",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v):
        valid_formats = ["simple", "structured"]
        if v.lower() not in valid_formats:
            raise ValueError(f"log_format must be one of {valid_formats}")
        return v.lower()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v):
        if not v:
            raise ValueError("database_url must not be empty")
        return v


# Global settings instance
_settings: Optional[SoniqSettings] = None


def get_settings(
    config_file: Optional[Path] = None, reload: bool = False
) -> SoniqSettings:
    """
    Get Soniq settings with caching.

    Args:
        config_file: Optional path to config file
        reload: Force reload settings from environment

    Returns:
        SoniqSettings instance
    """
    global _settings

    if _settings is None or reload:
        try:
            if config_file and config_file.exists():
                # Load settings from file if provided
                _settings = SoniqSettings(_env_file=str(config_file))  # type: ignore[call-arg]
            else:
                # Load from environment variables
                _settings = SoniqSettings()

        except ValidationError as e:
            raise ValueError(f"Invalid Soniq configuration: {e}")

    return _settings


def reload_settings(config_file: Optional[Path] = None):
    """Force reload settings from environment/config file."""
    return get_settings(config_file=config_file, reload=True)


def configure(**kwargs) -> SoniqSettings:
    """
    Configure Soniq settings programmatically.

    Creates a new settings instance directly with kwargs.
    Does not modify os.environ.
    """
    global _settings

    if not kwargs:
        return get_settings()

    unknown = [key for key in kwargs if key not in SoniqSettings.model_fields]
    if unknown:
        raise ValueError(f"Unknown Soniq settings: {', '.join(unknown)}")

    _settings = SoniqSettings(**kwargs)
    return _settings


def __getattr__(name: str):
    """Expose SONIQ_* settings as module attributes for CLI convenience."""
    if name.startswith("SONIQ_"):
        key = name[len("SONIQ_") :].lower()
        current = get_settings()
        if hasattr(current, key):
            return getattr(current, key)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
