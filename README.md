# ElephantQ

**All-in-one background job processing for Python (PostgreSQL-backed)**

ElephantQ is a powerful, all-in-one background job processing library for Python. It uses PostgreSQL to provide a robust, reliable, and observable job queue. All features, including a web dashboard, advanced scheduling, and dead-letter queues, are included out of the box.

## Quick Start

**Prerequisites:** PostgreSQL

```bash
# 1. Install
pip install elephantq

# 2. Set your database URL
export ELEPHANTQ_DATABASE_URL="postgresql://localhost/your_db"

# 3. Initialize database (creates tables)
elephantq setup
```

### Minimal App

```python
import elephantq
from fastapi import FastAPI

elephantq.configure(database_url="postgresql://localhost/myapp")

app = FastAPI()

@elephantq.job()
async def process_upload(file_path: str):
    print(f"Processing {file_path}")

@elephantq.job(retries=5, retry_delay=1, retry_backoff=True, retry_max_delay=30)
async def resilient_task():
    ...

@app.post("/upload")
async def upload_file(file_path: str):
    job_id = await elephantq.enqueue(process_upload, file_path=file_path)
    return {"job_id": job_id}
```

### Run Workers

ElephantQ always runs workers as a separate process:

```bash
# Terminal 1: Your app
uvicorn app:app

# Terminal 2: Workers
export ELEPHANTQ_JOBS_MODULES="app"
elephantq start --concurrency 4
```

## Core Concepts

### Global vs Instance API

**Global API (most apps):**

```python
import elephantq

@elephantq.job()
async def send_email(to: str):
    pass

await elephantq.enqueue(send_email, to="user@example.com")
```

**Instance API (microservices / multi-tenant):**

```python
from elephantq import ElephantQ

user_service = ElephantQ(database_url="postgresql://localhost/users")

@user_service.job()
async def send_welcome_email(user_id: int):
    pass

await user_service.enqueue(send_welcome_email, user_id=123)
```

## Optional Features (Same Package)

ElephantQ includes advanced scheduling, recurring jobs, dashboard, metrics, logging, webhooks, and dead-letter tools in the **same package**. Advanced APIs live under the `elephantq.features` namespace. Features are opt-in via configuration flags, and optional extras install dependencies:

```bash
pip install elephantq[dashboard]
pip install elephantq[monitoring]
pip install elephantq[all]
```

Enable features via environment variables:

```bash
export ELEPHANTQ_DASHBOARD_ENABLED=true
export ELEPHANTQ_SCHEDULING_ENABLED=true
export ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED=true
export ELEPHANTQ_METRICS_ENABLED=true
export ELEPHANTQ_LOGGING_ENABLED=true
export ELEPHANTQ_WEBHOOKS_ENABLED=true
export ELEPHANTQ_DEPENDENCIES_ENABLED=true
export ELEPHANTQ_TIMEOUTS_ENABLED=true
export ELEPHANTQ_SECURITY_ENABLED=true
```

### Advanced Features (Namespace)

```python
import elephantq

@elephantq.job()
async def nightly_report():
    ...

# Recurring scheduler (cron)
elephantq.features.recurring.schedule("0 2 * * *").job(nightly_report)

# Metrics (if enabled)
metrics = await elephantq.features.metrics.get_system_metrics()

# Dead letter stats (if enabled)
stats = await elephantq.features.dead_letter.get_stats()
```

## CLI

```bash
elephantq setup
elephantq start --concurrency 4 --queues default,urgent
elephantq scheduler
elephantq dashboard --port 6161  # read-only by default
elephantq metrics --hours 24
elephantq dead-letter list
```
