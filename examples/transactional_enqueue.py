"""
Transactional enqueue example for ElephantQ.

Demonstrates how to enqueue a job inside an existing database transaction.
If the transaction rolls back, the job is never created — your data and
your job are committed atomically.

Usage:
    pip install elephantq fastapi uvicorn
    export ELEPHANTQ_DATABASE_URL="postgresql://postgres@localhost/elephantq"
    elephantq setup
    uvicorn examples.transactional_enqueue:app --reload
"""

import asyncpg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import elephantq

DATABASE_URL = "postgresql://postgres@localhost/elephantq"


# ── Jobs ────────────────────────────────────────────────────────────────


@elephantq.job(queue="emails", retries=3)
async def send_welcome_email(user_id: int, email: str):
    """Send a welcome email to a newly registered user."""
    print(f"Sending welcome email to {email} (user {user_id})")


# ── API ─────────────────────────────────────────────────────────────────


class CreateUserRequest(BaseModel):
    name: str
    email: str


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def lifespan(app):
    app.state.pool = await asyncpg.create_pool(DATABASE_URL)
    elephantq.configure(database_url=DATABASE_URL)
    await elephantq._setup()

    async with app.state.pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE
            )
        """
        )

    yield

    await app.state.pool.close()


app = FastAPI(title="ElephantQ Transactional Enqueue Demo", lifespan=lifespan)


@app.post("/users")
async def create_user(req: CreateUserRequest):
    """
    Create a user and enqueue a welcome email — atomically.

    If the INSERT fails (e.g. duplicate email), the job is never enqueued.
    If the enqueue fails, the user row is rolled back.
    """
    async with app.state.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id",
                req.name,
                req.email,
            )
            user_id = row["id"]

            # Enqueue inside the same transaction
            job_id = await elephantq.enqueue(
                send_welcome_email,
                connection=conn,
                user_id=user_id,
                email=req.email,
            )

    return {"user_id": user_id, "welcome_email_job": job_id}


# ── Rollback demonstration ──────────────────────────────────────────────
#
# Uncomment the block below to see what happens when the transaction fails
# after the job is enqueued. The job will NOT appear in the queue.
#
# @app.post("/users/will-fail")
# async def create_user_will_fail(req: CreateUserRequest):
#     async with app.state.pool.acquire() as conn:
#         async with conn.transaction():
#             row = await conn.fetchrow(
#                 "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id",
#                 req.name,
#                 req.email,
#             )
#             job_id = await elephantq.enqueue(
#                 send_welcome_email,
#                 connection=conn,
#                 user_id=row["id"],
#                 email=req.email,
#             )
#             raise HTTPException(status_code=500, detail="Simulated failure")
#             # The transaction rolls back — neither the user nor the job exist.
