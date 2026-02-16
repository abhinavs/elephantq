"""
ElephantQ Configuration Management

Uses Pydantic v2 BaseSettings for robust, type-safe configuration with support for
environment variables, config files, and validation.
"""

import os
from pathlib import Path
from typing import Any, List, Optional

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import EnvSettingsSource


class CustomEnvSource(EnvSettingsSource):
    """Custom environment source that handles comma-separated lists without JSON parsing."""

    def prepare_field_value(
        self, field_name: str, field: Any, value: Any, value_is_complex: bool
    ) -> Any:
        """Override to handle comma-separated lists for specific fields."""
        if field_name == "default_queues" and isinstance(value, str):
            # Handle comma-separated queues without JSON parsing
            return [q.strip() for q in value.split(",") if q.strip()]
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class ElephantQSettings(BaseSettings):
    """
    ElephantQ configuration with environment variable support and validation.

    Configuration priority:
    1. Environment variables (ELEPHANTQ_*)
    2. Config file (if specified)
    3. Default values
    """

    model_config = SettingsConfigDict(
        env_prefix="ELEPHANTQ_",
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
        default="postgresql://postgres@localhost/postgres",
        description="PostgreSQL database URL for ElephantQ",
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
    default_concurrency: int = Field(
        default=4, ge=1, le=100, description="Default number of concurrent workers"
    )

    default_queues: List[str] = Field(
        default=["default"],
        description="Default queues to process (when not using dynamic discovery)",
    )

    # Job Processing Settings
    default_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Default maximum retry attempts for failed jobs",
    )

    default_priority: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Default job priority (lower = higher priority)",
    )

    # Feature Flags (all disabled by default)
    dashboard_enabled: bool = Field(
        default=False, description="Enable the ElephantQ dashboard"
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
    dependencies_enabled: bool = Field(
        default=False, description="Enable job dependency management"
    )
    timeouts_enabled: bool = Field(
        default=False, description="Enable job timeout processing"
    )
    security_enabled: bool = Field(
        default=False, description="Enable secret management and security helpers"
    )

    # Timeouts and Intervals
    worker_heartbeat_interval: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
        description="Worker heartbeat check interval in seconds",
    )

    job_timeout: Optional[float] = Field(
        default=None, ge=1.0, description="Default job execution timeout in seconds"
    )

    # Worker Processing Intervals
    cleanup_interval: float = Field(
        default=300.0,
        ge=10.0,
        le=3600.0,
        description="Interval for cleaning up expired jobs and stale workers (seconds)",
    )

    stale_worker_threshold: float = Field(
        default=300.0,
        ge=60.0,
        le=7200.0,
        description="Time after which workers are considered stale (seconds)",
    )

    notification_timeout: float = Field(
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
    default_job_display_limit: int = Field(
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
    db_pool_min_size: int = Field(
        default=5, ge=1, le=100, description="Minimum database connection pool size"
    )

    db_pool_max_size: int = Field(
        default=20, ge=1, le=200, description="Maximum database connection pool size"
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
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError("database_url must be a PostgreSQL connection string")
        return v


# Global settings instance
_settings: Optional[ElephantQSettings] = None


def get_settings(
    config_file: Optional[Path] = None, reload: bool = False
) -> ElephantQSettings:
    """
    Get ElephantQ settings with caching.

    Args:
        config_file: Optional path to config file
        reload: Force reload settings from environment

    Returns:
        ElephantQSettings instance
    """
    global _settings

    if _settings is None or reload:
        try:
            if config_file and config_file.exists():
                # Load settings from file if provided
                _settings = ElephantQSettings(_env_file=str(config_file))
            else:
                # Load from environment variables
                _settings = ElephantQSettings()

        except ValidationError as e:
            raise ValueError(f"Invalid ElephantQ configuration: {e}")

    return _settings


def reload_settings(config_file: Optional[Path] = None):
    """Force reload settings from environment/config file."""
    return get_settings(config_file=config_file, reload=True)


def configure(**kwargs) -> ElephantQSettings:
    """
    Configure ElephantQ settings programmatically.

    This validates provided settings, applies them to environment variables,
    and reloads the settings cache.
    """
    if not kwargs:
        return get_settings()

    unknown = [key for key in kwargs if key not in ElephantQSettings.model_fields]
    if unknown:
        raise ValueError(f"Unknown ElephantQ settings: {', '.join(unknown)}")

    # Validate settings upfront
    ElephantQSettings(**kwargs)

    for key, value in kwargs.items():
        env_key = f"ELEPHANTQ_{key.upper()}"
        if value is None:
            os.environ.pop(env_key, None)
            continue
        if isinstance(value, list):
            os.environ[env_key] = ",".join([str(item) for item in value])
        else:
            os.environ[env_key] = str(value)

    return get_settings(reload=True)


# Create settings instance
settings = get_settings()


def __getattr__(name: str):
    """Expose ELEPHANTQ_* settings as module attributes for CLI convenience."""
    if name.startswith("ELEPHANTQ_"):
        key = name[len("ELEPHANTQ_") :].lower()
        current = get_settings()
        if hasattr(current, key):
            return getattr(current, key)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
