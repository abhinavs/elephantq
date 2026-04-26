"""Jobs used for CLI integration tests."""

import soniq


@soniq.job(name="cli_fixture_job")
async def cli_fixture_job(message: str = "hello"):
    return f"cli:{message}"
