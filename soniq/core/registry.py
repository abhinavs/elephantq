"""
Job Registry System

Maps job names to their functions and configuration.
Supports both instance-based and global operations.
"""

import functools
from typing import Any, Callable, Dict, List, Optional, Type, Union

from pydantic import BaseModel


class JobRegistry:
    """
    Instance-based job registry.

    Manages job registration and lookup for a specific Soniq instance.
    Replaces global _registry pattern with clean instance-based architecture.
    """

    def __init__(self):
        """Initialize empty job registry."""
        self._registry: Dict[str, Dict[str, Any]] = {}

    def register_job(
        self,
        func: Callable[..., Any],
        *,
        name: str,
        retries: int = 3,
        max_retries: Optional[int] = None,
        args_model: Optional[Type[BaseModel]] = None,
        validate: Optional[Type[BaseModel]] = None,
        priority: int = 100,
        queue: str = "default",
        unique: bool = False,
        retry_delay: Optional[Union[int, float, List[Union[int, float]]]] = 0,
        retry_backoff: bool = False,
        retry_max_delay: Optional[Union[int, float]] = None,
        retry_jitter: bool = True,
        timeout: Optional[Union[int, float]] = None,
        **kwargs,
    ) -> Callable[..., Any]:
        """
        Register a job function with this registry.

        `name` is a mandatory keyword argument: a stable, dotted protocol
        identifier owned by the consumer service (e.g.
        ``billing.invoices.send.v2``). Module-derived names were removed
        because once queues cross repo boundaries, the name is the wire
        protocol; treating ``module.qualname`` as authoritative made every
        rename a wire-protocol migration. Use the explicit ``name=`` form.

        Args:
            func: Job function to register
            name: Required dotted task identifier (validated against
                ``SONIQ_TASK_NAME_PATTERN``).
            retries: Number of retry attempts (default: 3)
            args_model: Pydantic model for argument validation (alias: validate)
            priority: Job priority (lower = higher priority)
            queue: Queue name for job processing
            unique: Whether job should be deduplicated
            retry_delay: Retry delay in seconds or list of delays per attempt
            retry_backoff: Apply exponential backoff to retry_delay
            retry_max_delay: Optional maximum delay cap in seconds
            retry_jitter: If True (default) and retry_backoff is True, apply
                full-jitter to the computed delay to prevent thundering herds
                after batch failures. Set False for deterministic timing in
                tests.
            timeout: Per-job timeout in seconds (None = use global default)
            **kwargs: Additional job configuration

        Returns:
            The wrapped job function

        Raises:
            SoniqError(SONIQ_INVALID_TASK_NAME): name missing, empty, or
                violating the configured task name pattern.
        """
        from .naming import validate_task_name

        job_name = validate_task_name(name)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        # validate is the preferred alias for args_model
        effective_args_model = validate or args_model

        # max_retries is preferred; retries is the backward-compat alias
        effective_max_retries = max_retries if max_retries is not None else retries

        # Store job metadata
        job_config = {
            "func": wrapper,
            "max_retries": effective_max_retries,
            "args_model": effective_args_model,
            "priority": priority,
            "queue": queue,
            "unique": unique,
            "retry_delay": retry_delay,
            "retry_backoff": retry_backoff,
            "retry_max_delay": retry_max_delay,
            "retry_jitter": retry_jitter,
            "timeout": timeout,
            **kwargs,  # Allow additional configuration
        }

        self._registry[job_name] = job_config

        # Set job metadata on function for introspection
        wrapper._soniq_name = job_name  # type: ignore[attr-defined]
        wrapper._soniq_config = job_config  # type: ignore[attr-defined]

        return wrapper

    def get_job(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get job configuration by name.

        Args:
            name: Job name (module.function format)

        Returns:
            Job configuration dict or None if not found
        """
        return self._registry.get(name)

    def get_all_jobs(self) -> List[str]:
        """
        Get all registered job names.

        Returns:
            List of job names
        """
        return list(self._registry.keys())

    def get_jobs_by_queue(self, queue: str) -> List[str]:
        """
        Get all job names for a specific queue.

        Args:
            queue: Queue name

        Returns:
            List of job names in the queue
        """
        return [
            name
            for name, config in self._registry.items()
            if config.get("queue") == queue
        ]

    def clear(self):
        """Clear all registered jobs. Primarily for testing."""
        self._registry.clear()

    def remove_job(self, name: str) -> bool:
        """
        Remove a job from the registry.

        Args:
            name: Job name to remove

        Returns:
            True if job was removed, False if not found
        """
        if name in self._registry:
            del self._registry[name]
            return True
        return False

    def list_jobs(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all jobs with their configurations.

        Returns:
            Dictionary mapping job names to their configurations
        """
        return self._registry.copy()

    def __len__(self) -> int:
        """Get number of registered jobs."""
        return len(self._registry)

    def __contains__(self, name: str) -> bool:
        """Check if job is registered."""
        return name in self._registry


def get_job(name: str) -> Optional[Dict[str, Any]]:
    """
    Get job configuration by name from the global app's registry.

    Args:
        name: Fully qualified job name (module.function)

    Returns:
        Job configuration dict or None
    """
    import soniq

    return soniq._get_global_app()._get_job_registry().get_job(name)


def get_global_registry() -> JobRegistry:
    """
    Get the global app's job registry.

    Returns:
        JobRegistry from the global Soniq instance
    """
    import soniq

    return soniq._get_global_app()._get_job_registry()


def clear_registry():
    """Clear global registry. Used for testing."""
    get_global_registry().clear()
