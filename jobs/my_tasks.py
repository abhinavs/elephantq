"""Test jobs for discovery mechanism."""

from elephantq import job


@job()
async def discovered_job(message: str):
    """A simple job for testing discovery functionality."""
    return f"Processed: {message}"
