"""File processing example.

Keep payloads small: store files elsewhere and pass IDs/paths.
"""

import elephantq


@elephantq.job(retries=3, retry_backoff=True, retry_delay=2)
async def process_file(file_id: str, storage_path: str):
    print(f"Processing file {file_id} at {storage_path}")


async def main() -> None:
    await elephantq.enqueue(
        process_file,
        file_id="file_abc",
        storage_path="/tmp/uploads/file_abc.bin",
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
