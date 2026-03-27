"""
Tests that the clean public import paths work.

Users should never need to import from elephantq.features.
Everything should be accessible from elephantq or elephantq.<module>.
"""


def test_every_and_cron_importable_from_top_level():
    """from elephantq import every, cron"""
    from elephantq import cron, every

    assert callable(every)
    assert callable(cron)


def test_scheduling_module_importable():
    """from elephantq.scheduling import schedule_job"""
    from elephantq.scheduling import schedule_job

    assert callable(schedule_job)


def test_scheduling_includes_recurring():
    """elephantq.scheduling should include every, cron, etc."""
    from elephantq.scheduling import cron, every

    assert callable(every)
    assert callable(cron)


def test_webhooks_module_importable():
    """from elephantq.webhooks import register_webhook"""
    from elephantq.webhooks import register_webhook

    assert callable(register_webhook)


def test_dead_letter_module_importable():
    """from elephantq.dead_letter import list_dead_letter_jobs"""
    from elephantq.dead_letter import list_dead_letter_jobs

    assert callable(list_dead_letter_jobs)


def test_metrics_module_importable():
    """from elephantq.metrics import get_system_metrics"""
    from elephantq.metrics import get_system_metrics

    assert callable(get_system_metrics)
