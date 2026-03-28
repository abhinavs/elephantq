"""
Test for the documentation_url formatting path in ElephantQError.
"""

from elephantq.errors import ElephantQError


def test_error_with_documentation_url():
    error = ElephantQError(
        message="Setup failed",
        error_code="SETUP_ERROR",
        documentation_url="https://elephantq.dev/errors/setup",
    )
    error_str = str(error)
    assert "Documentation: https://elephantq.dev/errors/setup" in error_str
