# Dashboard

The dashboard is an optional feature for monitoring jobs and queues. Write actions (retry/delete/cancel) are disabled by default.

```bash
pip install elephantq[dashboard]
export ELEPHANTQ_DASHBOARD_ENABLED=true
elephantq dashboard --host 0.0.0.0 --port 6161
```

Open `http://localhost:6161`.

Enable write actions (optional):

```bash
export ELEPHANTQ_DASHBOARD_WRITE_ENABLED=true
```

## Mounting inside your FastAPI app

Instead of running the dashboard as a standalone process, you can mount it as a sub-application:

```python
from fastapi import FastAPI
from elephantq.dashboard import create_dashboard_app

app = FastAPI()

# Mount the dashboard at /admin/queue
dashboard_app = create_dashboard_app()
app.mount("/admin/queue", dashboard_app)
```

The dashboard is then accessible at `http://localhost:8000/admin/queue`. This is useful when you want to serve the dashboard behind your existing auth middleware or reverse proxy.
