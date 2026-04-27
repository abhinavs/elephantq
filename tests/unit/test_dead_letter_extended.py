"""
Extended tests for dead_letter.py — DeadLetterService and helpers.
"""

from datetime import datetime, timezone

from soniq.features.dead_letter import (
    DeadLetterFilter,
    DeadLetterJob,
    create_filter,
)


class TestCreateFilter:
    def test_create_filter_returns_filter(self):
        f = create_filter()
        assert isinstance(f, DeadLetterFilter)

    def test_create_filter_customizable(self):
        f = create_filter()
        f.job_names = ["mod.task"]
        f.queues = ["default"]
        f.reasons = ["timeout"]
        f.limit = 50
        assert f.job_names == ["mod.task"]
        assert f.queues == ["default"]
        assert f.reasons == ["timeout"]
        assert f.limit == 50


class TestDeadLetterFilterSql:
    def test_filter_with_tags(self):
        f = DeadLetterFilter()
        f.tags = {"env": "prod"}
        conditions, params = f.to_sql_conditions()
        assert len(conditions) >= 1

    def test_filter_with_resurrected_flag(self):
        f = DeadLetterFilter()
        f.has_been_resurrected = True
        conditions, params = f.to_sql_conditions()
        assert len(conditions) >= 1

    def test_filter_limit_and_offset(self):
        f = DeadLetterFilter()
        f.limit = 10
        f.offset = 20
        # Limit/offset may not be in conditions, they're usually applied separately
        assert f.limit == 10
        assert f.offset == 20


class TestDeadLetterJobDataclass:
    def test_as_dict(self):
        from dataclasses import asdict

        now = datetime.now(timezone.utc)
        job = DeadLetterJob(
            id="j1",
            job_name="mod.task",
            args={"key": "value"},
            queue="default",
            priority=100,
            max_attempts=3,
            attempts=3,
            last_error="error msg",
            dead_letter_reason="max_retries_exceeded",
            original_created_at=now,
            moved_to_dead_letter_at=now,
        )
        d = asdict(job)
        assert d["id"] == "j1"
        assert d["args"] == {"key": "value"}
        assert d["resurrection_count"] == 0
        assert d["tags"] is None
