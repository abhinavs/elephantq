"""
Tests that depends_on() emits a deprecation/experimental warning.

Written to verify BLOCKER-02: the worker never checks job dependencies,
so depends_on() must warn users that enforcement is not implemented.
"""

import os
import warnings

import pytest

os.environ.setdefault("ELEPHANTQ_SCHEDULING_ENABLED", "true")


class TestDependsOnWarning:
    """Verify depends_on() emits an experimental warning."""

    def test_depends_on_emits_warning(self):
        from elephantq.features.scheduling import schedule_job

        async def dummy_job():
            pass

        dummy_job._elephantq_name = "test.dummy_job"

        builder = schedule_job(dummy_job)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            builder.depends_on("some-job-id")

            assert len(w) == 1
            assert "experimental" in str(w[0].message).lower()
            assert "not yet enforce" in str(w[0].message).lower() or "not enforced" in str(w[0].message).lower()

    def test_depends_on_still_stores_ids(self):
        from elephantq.features.scheduling import schedule_job

        async def dummy_job():
            pass

        dummy_job._elephantq_name = "test.dummy_job"

        builder = schedule_job(dummy_job)

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            builder.depends_on("id-1", "id-2")

        assert "id-1" in builder._dependencies
        assert "id-2" in builder._dependencies
