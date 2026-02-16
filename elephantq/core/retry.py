"""
Retry policy helpers for job processing.
"""

from typing import Iterable, Optional, Union


def compute_retry_delay_seconds(
    *,
    attempt: int,
    retry_delay: Optional[Union[int, float, Iterable[Union[int, float]]]] = 0,
    retry_backoff: bool = False,
    retry_max_delay: Optional[Union[int, float]] = None,
) -> float:
    """
    Compute retry delay for a given attempt.

    Args:
        attempt: 1-based retry attempt index (1 for first retry).
        retry_delay: base delay seconds or list/tuple of delays per attempt.
        retry_backoff: if True, apply exponential backoff to base delay.
        retry_max_delay: optional upper bound on delay seconds.

    Returns:
        Delay in seconds (>= 0).
    """
    if attempt < 1:
        attempt = 1

    delay = 0.0

    if retry_delay is None:
        delay = 0.0
    elif isinstance(retry_delay, (list, tuple)):
        if len(retry_delay) > 0:
            index = min(attempt - 1, len(retry_delay) - 1)
            delay = float(retry_delay[index])
        else:
            delay = 0.0
    else:
        delay = float(retry_delay)

    if retry_backoff:
        base = delay if delay > 0 else 1.0
        delay = base * (2 ** (attempt - 1))

    if retry_max_delay is not None:
        delay = min(delay, float(retry_max_delay))

    if delay < 0:
        delay = 0.0

    return delay
