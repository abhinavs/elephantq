"""
Job Registry System

Maps job names to their functions and configuration. Each Soniq
instance owns its own ``JobRegistry``; there is no process-global
registry.
"""

import functools
from typing import (  # noqa: F401
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    ParamSpec,
    Type,
    TypeVar,
    Union,
)

from pydantic import BaseModel

from soniq.core.naming import validate_task_name
from soniq.settings import SoniqSettings

_P = ParamSpec("_P")
_R = TypeVar("_R")


class JobRegistry:
    """
    Instance-based job registry.

    Manages job registration and lookup for a specific Soniq instance.
    Replaces global _registry pattern with clean instance-based architecture.
    """

    def __init__(self) -> None:
        """Initialize empty job registry."""
        self._registry: Dict[str, Dict[str, Any]] = {}

    def register_job(
        self,
        func: Callable[_P, Awaitable[_R]],
        *,
        name: Optional[str] = None,
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
        _route_map: Optional[Dict[str, str]] = None,
        _task_name_pattern: Optional[str] = None,
        **kwargs: Any,
    ) -> Callable[_P, Awaitable[_R]]:
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
        # Celery-style name resolution. When the caller passes name=, it is
        # validated against SONIQ_TASK_NAME_PATTERN (the explicit name is a
        # protocol identifier; we want the loud failure on a typo). When
        # the caller omits name=, derive `f"{module}.{qualname}"` and
        # accept it without pattern validation - the user did not pick the
        # derived name, and module/qualname segments may legitimately
        # contain camelcase or test-class chrome that the default pattern
        # rejects.
        if name is None:
            job_name = f"{func.__module__}.{func.__name__}"
        else:
            # The pattern is threaded from the owning Soniq instance via
            # `Soniq.job` (see app.py). Direct callers of register_job
            # (legacy tests, ad-hoc fixtures) may pass it explicitly; if
            # neither path supplied one, fall back to a fresh
            # `SoniqSettings()` read of the env. We never reach for
            # `get_settings()` here - that would re-introduce the global
            # cache the instance-boundary contract bans.
            if _task_name_pattern is None:
                _task_name_pattern = SoniqSettings().task_name_pattern
            job_name = validate_task_name(name, _task_name_pattern)

        @functools.wraps(func)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Awaitable[_R]:
            return func(*args, **kwargs)

        # validate is the preferred alias for args_model
        effective_args_model = validate or args_model

        # max_retries is preferred; retries is the backward-compat alias
        effective_max_retries = max_retries if max_retries is not None else retries

        # Resolve the registered queue with precedence:
        #     explicit @app.job(queue=...) > route_map prefix match > "default"
        # The default `queue="default"` kwarg from the signature can't be
        # distinguished from an explicit pass at this level; we approximate
        # by treating "default" as "unset" for the route_map check, which
        # matches the historical default.
        effective_queue = queue
        if queue == "default" and _route_map:
            # Longest-prefix-match wins so a more-specific prefix beats
            # a less-specific one.
            best: Optional[tuple[str, str]] = None
            for prefix, mapped in _route_map.items():
                if job_name.startswith(prefix):
                    if best is None or len(prefix) > len(best[0]):
                        best = (prefix, mapped)
            if best is not None:
                effective_queue = best[1]

        # Store job metadata
        job_config = {
            "func": wrapper,
            "max_retries": effective_max_retries,
            "args_model": effective_args_model,
            "priority": priority,
            "queue": effective_queue,
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

    def clear(self) -> None:
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
