# Getting Started (60 seconds)

ElephantQ is a PostgreSQL‑backed async job queue. Workers run as **separate processes**.

## 1) Install

```bash
pip install elephantq
```

Optional extras:

```bash
pip install elephantq[dashboard]
pip install elephantq[monitoring]
pip install elephantq[all]
```

## 2) Configure

```bash
export ELEPHANTQ_DATABASE_URL="postgresql://localhost/your_db"
export ELEPHANTQ_JOBS_MODULES="my_app.tasks"
```

## 3) Define Jobs

```python
# my_app/tasks.py
import elephantq

@elephantq.job()
async def my_first_job(user_id: int):
    print(f"Hello {user_id}")
```

## 4) Migrate

```bash
elephantq setup
```

## 5) Run Worker

```bash
elephantq start --concurrency 4
```

## 6) Enqueue

```python
import elephantq
from my_app.tasks import my_first_job

await elephantq.enqueue(my_first_job, user_id=123)
```

---

### Docker Quickstart (PostgreSQL)

```bash
docker run --name elephantq-postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres:16
export ELEPHANTQ_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/postgres"
elephantq setup
```
