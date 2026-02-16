# ElephantQ Getting Started

ElephantQ is a PostgreSQL-backed async job queue. It runs workers as **separate processes** (no embedded workers).

## Install

```bash
pip install elephantq
```

Optional extras:

```bash
pip install elephantq[dashboard]
pip install elephantq[monitoring]
pip install elephantq[all]
```

Enable optional features:

```bash
export ELEPHANTQ_DASHBOARD_ENABLED=true
export ELEPHANTQ_SCHEDULING_ENABLED=true
export ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED=true
```

## Define Jobs

Create a Python file to define your job functions. For example, create `my_app/tasks.py`:

```python
# my_app/tasks.py
import time

def my_first_job(user_id: int):
    print(f"Starting job for user {user_id}...")
    time.sleep(5)
    print(f"Finished job for user {user_id}.")

def another_job():
    print("Doing other work...")
```

## Tell ElephantQ Where Jobs Live

This is the most important step. You must tell the ElephantQ worker which Python modules contain your job definitions. You do this by setting the `ELEPHANTQ_JOBS_MODULES`
environment variable.

This variable should be a comma-separated list of modules to import:

```bash
export ELEPHANTQ_JOBS_MODULES="my_app.tasks"
```

## Configure

```bash
export ELEPHANTQ_DATABASE_URL="postgresql://localhost/your_db"
```

## Migrate

```bash
elephantq setup
```

Or from Python:

```python
import elephantq
await elephantq.setup()
```

## Minimal App

```python
import elephantq
from fastapi import FastAPI

elephantq.configure(database_url="postgresql://localhost/myapp")

app = FastAPI()

@elephantq.job()
async def process_upload(file_path: str):
    return f"Processed {file_path}"

@elephantq.job(retries=5, retry_delay=1, retry_backoff=True, retry_max_delay=30)
async def resilient_task():
    ...

@app.post("/upload")
async def upload(file_path: str):
    job_id = await elephantq.enqueue(process_upload, file_path=file_path)
    return {"job_id": job_id}
```

## Run Workers

```bash
# Terminal 1: app
uvicorn app:app

# Terminal 2: workers
export ELEPHANTQ_JOBS_MODULES="app"
elephantq start --concurrency 4
```

You should see output indicating that ElephantQ has successfully imported your modules:

```text
Discovering jobs in: my_app.tasks
  - Imported 'my_app.tasks'
...worker starting...
```
