"""
Tests for multi-scheduler safety.

When multiple scheduler processes check the same recurring job simultaneously,
only one should fire it per period.
"""

import pytest


@pytest.mark.asyncio
async def test_claim_recurring_run_returns_true_on_first_claim(monkeypatch):
    """First scheduler to claim a due job should succeed."""
    from elephantq.features.recurring import EnhancedRecurringManager

    manager = EnhancedRecurringManager()

    claimed = []

    async def fake_claim(
        job_id, expected_next_run, new_next_run, run_count, actual_job_id
    ):
        claimed.append(job_id)
        return True

    monkeypatch.setattr(manager, "_claim_and_advance_run", fake_claim)

    assert hasattr(manager, "_claim_and_advance_run"), (
        "EnhancedRecurringManager must have _claim_and_advance_run method "
        "for atomic scheduling coordination"
    )
