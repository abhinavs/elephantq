"""
Consumer service - registers the handler under the same task name the
producer uses, and runs the worker.

Run with `SONIQ_DATABASE_URL` pointing at the same Postgres database the
producer writes to.
"""

from __future__ import annotations

import asyncio
import logging
import os

from pydantic import BaseModel

from soniq import Soniq

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


class InvoiceArgs(BaseModel):
    order_id: str
    customer: str


async def main() -> None:
    db_url = os.environ.get("SONIQ_DATABASE_URL")
    if not db_url:
        raise SystemExit(
            "SONIQ_DATABASE_URL not set. "
            "Try: export SONIQ_DATABASE_URL=postgresql://localhost/soniq_demo"
        )

    consumer = Soniq(database_url=db_url)

    @consumer.job(name="billing.invoices.send.v2", validate=InvoiceArgs)
    async def send_invoice(order_id: str, customer: str) -> None:
        logging.info("handler ran: order_id=%s customer=%s", order_id, customer)

    logging.info("consumer waiting for jobs (Ctrl-C to stop)...")
    await consumer.run_worker()


if __name__ == "__main__":
    asyncio.run(main())
