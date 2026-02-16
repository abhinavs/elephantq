from elephantq.core.retry import compute_retry_delay_seconds


def test_retry_delay_fixed():
    assert compute_retry_delay_seconds(attempt=1, retry_delay=2) == 2
    assert compute_retry_delay_seconds(attempt=3, retry_delay=2) == 2


def test_retry_delay_list():
    assert compute_retry_delay_seconds(attempt=1, retry_delay=[1, 5, 10]) == 1
    assert compute_retry_delay_seconds(attempt=2, retry_delay=[1, 5, 10]) == 5
    assert compute_retry_delay_seconds(attempt=5, retry_delay=[1, 5, 10]) == 10


def test_retry_backoff():
    assert compute_retry_delay_seconds(attempt=1, retry_delay=1, retry_backoff=True) == 1
    assert compute_retry_delay_seconds(attempt=2, retry_delay=1, retry_backoff=True) == 2
    assert compute_retry_delay_seconds(attempt=3, retry_delay=1, retry_backoff=True) == 4


def test_retry_backoff_max_delay():
    assert (
        compute_retry_delay_seconds(
            attempt=4, retry_delay=2, retry_backoff=True, retry_max_delay=5
        )
        == 5
    )
