"""Queue routing example.

Run workers for specific queues:
  elephantq start --queues emails,media
"""

import elephantq


@elephantq.job(queue="emails")
async def send_email(to: str, subject: str):
    print(f"Sending email to {to}: {subject}")


@elephantq.job(queue="media")
async def transcode_video(video_id: str):
    print(f"Transcoding video {video_id}")


async def main() -> None:
    await elephantq.enqueue(send_email, to="dev@example.com", subject="Welcome")
    await elephantq.enqueue(transcode_video, video_id="vid_123")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
