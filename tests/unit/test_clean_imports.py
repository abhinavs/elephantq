"""
Tests that the clean public import paths work.
"""


def test_every_and_cron_importable_from_top_level():
    """from soniq import every, cron"""
    from soniq import cron, every

    assert callable(every)
    assert callable(cron)


def test_scheduling_importable_from_features():
    """from soniq.features.scheduling import schedule_job"""
    from soniq.features.scheduling import schedule_job

    assert callable(schedule_job)


def test_recurring_importable_from_features():
    """from soniq.features.recurring import every, cron"""
    from soniq.features.recurring import cron, every

    assert callable(every)
    assert callable(cron)


def test_webhooks_importable_from_features():
    """from soniq.features.webhooks import register_webhook"""
    from soniq.features.webhooks import register_webhook

    assert callable(register_webhook)


def test_dead_letter_importable_from_features():
    """from soniq.features.dead_letter import list_dead_letter_jobs"""
    from soniq.features.dead_letter import list_dead_letter_jobs

    assert callable(list_dead_letter_jobs)


def test_metrics_importable_from_features():
    """from soniq.features.metrics import get_system_metrics"""
    from soniq.features.metrics import get_system_metrics

    assert callable(get_system_metrics)
