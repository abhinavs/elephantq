"""Queue routing example.

Run workers for specific queues:
  soniq start --queues emails,media
"""

import soniq


@soniq.job(name="send_email", queue="emails")
async def send_email(to: str, subject: str):
    print(f"Sending email to {to}: {subject}")


@soniq.job(name="transcode_video", queue="media")
async def transcode_video(video_id: str):
    print(f"Transcoding video {video_id}")


async def main() -> None:
    await soniq.enqueue(
        "send_email", args={"to": "dev@example.com", "subject": "Welcome"}
    )
    await soniq.enqueue("transcode_video", args={"video_id": "vid_123"})


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
