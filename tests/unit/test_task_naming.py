"""
Tests for soniq.core.naming.validate_task_name.
"""

import os

import pytest

from tests.db_utils import TEST_DATABASE_URL

os.environ.setdefault("SONIQ_DATABASE_URL", TEST_DATABASE_URL)

from soniq.core.naming import validate_task_name  # noqa: E402
from soniq.errors import SONIQ_INVALID_TASK_NAME, SoniqError  # noqa: E402


class TestValidateTaskName:
    @pytest.mark.parametrize(
        "good",
        [
            "a.b.c",
            "billing.invoices.send.v2",
            "x_y.z_w",
            "foo",
            "billing_v2.send",
            "a.b",
        ],
    )
    def test_accepts_valid_names(self, good):
        assert validate_task_name(good) == good

    @pytest.mark.parametrize(
        "bad",
        [
            "Billing.x",
            ".leading",
            "trailing.",
            "double..dot",
            "has space",
            "dash-name",
            "",
        ],
    )
    def test_rejects_invalid_names(self, bad):
        with pytest.raises(SoniqError) as exc_info:
            validate_task_name(bad)
        assert exc_info.value.error_code == SONIQ_INVALID_TASK_NAME

    def test_error_context_carries_name_and_pattern(self):
        with pytest.raises(SoniqError) as exc_info:
            validate_task_name("Bad Name")
        assert exc_info.value.context["name"] == "Bad Name"
        assert "pattern" in exc_info.value.context

    def test_non_string_input_raises(self):
        with pytest.raises(SoniqError) as exc_info:
            validate_task_name(123)  # type: ignore[arg-type]
        assert exc_info.value.error_code == SONIQ_INVALID_TASK_NAME
        assert exc_info.value.context["received_type"] == "int"

    def test_pattern_can_be_overridden_via_arg(self):
        assert validate_task_name("Has Space", pattern=r".+") == "Has Space"

    def test_default_pattern_consults_settings(self):
        """If the helper bypassed settings, 'Has Space' would pass under any
        permissive default. It fails -> the helper is reading settings."""
        with pytest.raises(SoniqError) as exc_info:
            validate_task_name("Has Space")
        assert exc_info.value.error_code == SONIQ_INVALID_TASK_NAME


class TestPatternConfigurable:
    """Override SONIQ_TASK_NAME_PATTERN via env and verify the helper sees it."""

    def setup_method(self):
        self.original_env = {
            k: v for k, v in os.environ.items() if k.startswith("SONIQ_")
        }
        for key in list(os.environ.keys()):
            if key.startswith("SONIQ_"):
                del os.environ[key]
        os.environ["SONIQ_DATABASE_URL"] = TEST_DATABASE_URL
        import soniq.settings

        soniq.settings._settings = None

    def teardown_method(self):
        for key in list(os.environ.keys()):
            if key.startswith("SONIQ_"):
                del os.environ[key]
        for key, value in self.original_env.items():
            os.environ[key] = value
        import soniq.settings

        soniq.settings._settings = None

    def test_permissive_pattern_accepts_previously_invalid(self):
        os.environ["SONIQ_TASK_NAME_PATTERN"] = r"^.+$"
        from soniq.settings import get_settings

        get_settings(reload=True)
        assert validate_task_name("Has Space") == "Has Space"
        assert validate_task_name("Billing.X") == "Billing.X"
