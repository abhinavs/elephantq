"""
Retry policy helpers for job processing.

The backoff implementation uses AWS-style "full jitter":
    deterministic = min(base * 2 ** (attempt - 1), retry_max_delay)
    delay         = uniform(deterministic / 2, deterministic)

Full jitter is simpler than decorrelated jitter and empirically close in
outcome: retry schedules spread across the interval instead of all landing
at the same computed delay, which prevents thundering herds after a batch
failure (e.g. a webhook endpoint flaking, then recovering).
"""

import random
from typing import Iterable, Optional, Union

# Cap the exponent so `base * 2 ** attempt` cannot overflow for absurd inputs.
# With MAX_EXPONENT=62, `2 ** 62` is ~4.6e18 - comfortably above any realistic
# retry_max_delay - but still finite. retry_max_delay is always re-applied
# after, so this only protects the multiplication.
_MAX_EXPONENT = 62

_rng = random.Random()


def set_rng(rng: random.Random) -> None:
    """Inject an RNG for deterministic tests. Default is a module-level Random()."""
    global _rng
    _rng = rng


def compute_retry_delay_seconds(
    *,
    attempt: int,
    retry_delay: Optional[Union[int, float, Iterable[Union[int, float]]]] = 0,
    retry_backoff: bool = False,
    retry_max_delay: Optional[Union[int, float]] = None,
    retry_jitter: bool = True,
) -> float:
    """
    Compute retry delay for a given attempt.

    Args:
        attempt: 1-based retry attempt index (1 for first retry).
        retry_delay: base delay seconds or list/tuple of delays per attempt.
        retry_backoff: if True, apply exponential backoff to base delay.
        retry_max_delay: optional upper bound on delay seconds.
        retry_jitter: if True and retry_backoff is True, apply full-jitter to
            the computed delay. Ignored when retry_backoff is False, since
            fixed or per-attempt list delays are already deterministic by
            caller intent.

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
        delay = float(retry_delay)  # type: ignore[arg-type]

    if retry_backoff:
        base = delay if delay > 0 else 1.0
        exponent = min(attempt - 1, _MAX_EXPONENT)
        delay = base * (2**exponent)

    if retry_max_delay is not None:
        delay = min(delay, float(retry_max_delay))

    if retry_backoff and retry_jitter and delay > 0:
        delay = _rng.uniform(delay / 2.0, delay)

    if delay < 0:
        delay = 0.0

    return delay
