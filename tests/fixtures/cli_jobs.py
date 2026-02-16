"""Jobs used for CLI integration tests."""

import elephantq


@elephantq.job()
async def cli_fixture_job(message: str = "hello"):
    return f"cli:{message}"
