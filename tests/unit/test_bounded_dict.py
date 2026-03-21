import os

import pytest

# Enable scheduling feature flag before importing
os.environ.setdefault("ELEPHANTQ_SCHEDULING_ENABLED", "true")

from elephantq.features.scheduling import _BoundedDict


class TestBoundedDict:
    """Verify _BoundedDict evicts the oldest entry when capacity is exceeded."""

    def test_evicts_oldest_when_over_capacity(self):
        bd = _BoundedDict(max_size=10_000)

        for i in range(10_001):
            bd[f"key-{i}"] = i

        assert len(bd) == 10_000
        # The first key should have been evicted
        assert "key-0" not in bd
        # The last key should still exist
        assert "key-10000" in bd

    def test_respects_custom_max_size(self):
        bd = _BoundedDict(max_size=5)

        for i in range(8):
            bd[f"k{i}"] = i

        assert len(bd) == 5
        assert "k0" not in bd
        assert "k1" not in bd
        assert "k2" not in bd
        assert "k7" in bd
