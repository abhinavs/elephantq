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
