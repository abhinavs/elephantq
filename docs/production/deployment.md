# Deployment

This guide covers the major deployment paths for Soniq. Ready-to-use configuration files live in the [`deployment/`](../../deployment/) directory.

## Prerequisites

**Minimum requirements:**

- Python 3.10+
- PostgreSQL 12+
- 2 GB RAM, 2 CPU cores

**Recommended for production:**

- Python 3.12+
- PostgreSQL 15+
- 4 GB+ RAM, 4+ CPU cores
- SSD storage for the database

### Database setup

```bash
createdb soniq_prod
psql -c "CREATE USER soniq WITH PASSWORD 'your_secure_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE soniq_prod TO soniq;"

export SONIQ_DATABASE_URL="postgresql://soniq:your_secure_password@localhost/soniq_prod"
soniq setup
```

### Application user (Linux)

```bash
sudo useradd --system --create-home --shell /bin/bash soniq
sudo mkdir -p /opt/soniq /var/log/soniq
sudo chown soniq:soniq /opt/soniq /var/log/soniq
```

---

## Recurring jobs require a scheduler sidecar

If your application uses `@app.periodic(...)` jobs, deploy a separate `soniq scheduler` process alongside `soniq start`. The worker process **does not** evaluate due recurring jobs; that responsibility lives with the scheduler so worker scaling does not duplicate scheduler work.

If `soniq start` finds `@periodic` decorators registered and no scheduler-sidecar process holds the leadership lock, it prints a one-time WARN at startup. To silence the WARN once you have configured the sidecar (or if you intentionally do not run recurring jobs), set `SONIQ_SCHEDULER_SUPPRESS_WARNING=1` in the worker environment.

The scheduler is a standard subcommand (`soniq scheduler`); it is not a separate package and shares the same `soniq` CLI entry point. Multiple instances coordinate via the `soniq.maintenance` Postgres advisory lock - duplicates are safe but only one is needed.

The shipped deployment templates include the sidecar:

- Systemd: `deployment/soniq-scheduler.service`
- Docker Compose: the `soniq_scheduler` service in `deployment/docker-compose.yml`
- Kubernetes: the `soniq-scheduler` Deployment in `deployment/kubernetes.yaml`
- Supervisor: the `[program:soniq_scheduler]` block in `deployment/supervisor.conf`

---

## Systemd

Best for modern Linux servers with direct process control. Files: `deployment/soniq-worker.service`, `deployment/soniq-scheduler.service`, and `deployment/soniq-dashboard.service`.

### Worker service

```ini
[Unit]
Description=Soniq Worker
After=network.target

[Service]
Type=exec
User=soniq
Group=soniq
WorkingDirectory=/opt/soniq
Environment=SONIQ_DATABASE_URL=postgresql://soniq:password@localhost/soniq_prod
Environment=SONIQ_LOG_LEVEL=INFO
Environment=SONIQ_JOBS_MODULES=myapp.jobs
ExecStart=/opt/soniq/venv/bin/soniq start --concurrency=4
ExecReload=/bin/kill -HUP $MAINPID
KillMode=mixed
Restart=always
RestartSec=5
StartLimitIntervalSec=0

# Security hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/soniq /var/log/soniq

# Resource limits
MemoryMax=512M
CPUQuota=200%

# Graceful shutdown -- match your longest job timeout
TimeoutStopSec=310

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=soniq-worker

[Install]
WantedBy=multi-user.target
```

### Dashboard service

```ini
[Unit]
Description=Soniq Dashboard
After=network.target soniq-worker.service
Wants=soniq-worker.service

[Service]
Type=exec
User=soniq
Group=soniq
WorkingDirectory=/opt/soniq
Environment=SONIQ_DATABASE_URL=postgresql://soniq:password@localhost/soniq_prod
Environment=SONIQ_DASHBOARD_ENABLED=true
ExecStart=/opt/soniq/venv/bin/soniq dashboard --host=0.0.0.0 --port=8000
Restart=always
RestartSec=5

NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/soniq /var/log/soniq
MemoryMax=256M

StandardOutput=journal
StandardError=journal
SyslogIdentifier=soniq-dashboard

[Install]
WantedBy=multi-user.target
```

### Managing the services

```bash
sudo cp deployment/soniq-worker.service /etc/systemd/system/
sudo cp deployment/soniq-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl enable soniq-worker soniq-dashboard
sudo systemctl start soniq-worker soniq-dashboard

# Check status
sudo systemctl status soniq-worker

# View logs
sudo journalctl -u soniq-worker -f

# Restart
sudo systemctl restart soniq-worker
```

---

## Docker Compose

Good for staging or small production environments. File: `deployment/docker-compose.yml`.

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:15-alpine
    restart: always
    environment:
      POSTGRES_DB: soniq_prod
      POSTGRES_USER: soniq
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U soniq -d soniq_prod"]
      interval: 10s
      timeout: 5s
      retries: 5

  soniq_worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    restart: always
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      SONIQ_DATABASE_URL: postgresql://soniq:${POSTGRES_PASSWORD:-changeme}@postgres:5432/soniq_prod
      SONIQ_JOBS_MODULES: myapp.jobs
      SONIQ_TIMEOUTS_ENABLED: "true"
      SONIQ_DEAD_LETTER_QUEUE_ENABLED: "true"
    command: ["soniq", "start", "--concurrency=4"]
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"

  soniq_dashboard:
    build:
      context: .
      dockerfile: Dockerfile.dashboard
    restart: always
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      SONIQ_DATABASE_URL: postgresql://soniq:${POSTGRES_PASSWORD:-changeme}@postgres:5432/soniq_prod
      SONIQ_DASHBOARD_ENABLED: "true"
    ports:
      - "8000:8000"
    command: ["soniq", "dashboard", "--host=0.0.0.0", "--port=8000"]

volumes:
  postgres_data:
```

### Scaling workers

```bash
docker-compose up -d --scale soniq_worker=3
```

---

## Kubernetes

Best for containerized environments with autoscaling. File: `deployment/kubernetes.yaml`.

### Secret and ConfigMap

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: soniq-secrets
  namespace: soniq
type: Opaque
data:
  # echo -n "postgresql://user:pass@host/db" | base64
  SONIQ_DATABASE_URL: <base64-encoded-url>

---
apiVersion: v1
kind: ConfigMap
metadata:
  name: soniq-config
  namespace: soniq
data:
  SONIQ_LOG_LEVEL: "INFO"
  SONIQ_JOBS_MODULES: "myapp.jobs"
  SONIQ_TIMEOUTS_ENABLED: "true"
  SONIQ_DEAD_LETTER_QUEUE_ENABLED: "true"
  SONIQ_METRICS_ENABLED: "true"
```

### Worker Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: soniq-worker
  namespace: soniq
spec:
  replicas: 3
  selector:
    matchLabels:
      app: soniq-worker
  template:
    metadata:
      labels:
        app: soniq-worker
    spec:
      terminationGracePeriodSeconds: 310  # match your longest job timeout
      containers:
      - name: worker
        image: soniq/worker:latest
        args: ["soniq", "start", "--concurrency=4"]
        env:
        - name: SONIQ_DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: soniq-secrets
              key: SONIQ_DATABASE_URL
        envFrom:
        - configMapRef:
            name: soniq-config
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          exec:
            command: ["soniq", "health"]
          initialDelaySeconds: 30
          periodSeconds: 30
        readinessProbe:
          exec:
            command: ["soniq", "ready"]
          initialDelaySeconds: 5
          periodSeconds: 10
```

### Dashboard Deployment + Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: soniq-dashboard
  namespace: soniq
spec:
  replicas: 2
  selector:
    matchLabels:
      app: soniq-dashboard
  template:
    metadata:
      labels:
        app: soniq-dashboard
    spec:
      containers:
      - name: dashboard
        image: soniq/dashboard:latest
        args: ["soniq", "dashboard", "--host=0.0.0.0", "--port=8000"]
        env:
        - name: SONIQ_DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: soniq-secrets
              key: SONIQ_DATABASE_URL
        envFrom:
        - configMapRef:
            name: soniq-config
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          periodSeconds: 10

---
apiVersion: v1
kind: Service
metadata:
  name: soniq-dashboard
  namespace: soniq
spec:
  selector:
    app: soniq-dashboard
  ports:
  - port: 80
    targetPort: 8000
  type: ClusterIP
```

### Autoscaling

```bash
kubectl autoscale deployment soniq-worker \
  --namespace=soniq \
  --cpu-percent=70 \
  --min=2 --max=10
```

The `deployment/kubernetes.yaml` file also includes an HPA manifest and a ServiceMonitor for Prometheus.

---

## Supervisor

Good for older setups or shared environments. File: `deployment/supervisor.conf`.

```ini
[group:soniq]
programs=soniq_worker,soniq_dashboard

[program:soniq_worker]
command=/opt/soniq/venv/bin/soniq start --concurrency=4
directory=/opt/soniq
user=soniq
autostart=true
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/var/log/soniq/worker.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=5
environment=SONIQ_DATABASE_URL="postgresql://soniq:password@localhost/soniq_prod",SONIQ_LOG_LEVEL="INFO",SONIQ_JOBS_MODULES="myapp.jobs"

[program:soniq_dashboard]
command=/opt/soniq/venv/bin/soniq dashboard --host=0.0.0.0 --port=8000
directory=/opt/soniq
user=soniq
autostart=true
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/var/log/soniq/dashboard.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=5
environment=SONIQ_DATABASE_URL="postgresql://soniq:password@localhost/soniq_prod",SONIQ_DASHBOARD_ENABLED="true"
```

### Managing with Supervisor

```bash
sudo cp deployment/supervisor.conf /etc/supervisor/conf.d/soniq.conf
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start soniq_worker
sudo supervisorctl status
```

---

## Queue routing

When different queues have different throughput or latency needs, run separate worker processes per queue group. Each scales independently.

```bash
# Email workers -- high concurrency, IO-bound
soniq start --concurrency=8 --queues=emails,notifications

# Media workers -- low concurrency, CPU-bound
soniq start --concurrency=2 --queues=media,transcode
```

In Kubernetes, use separate Deployments. In Docker Compose, use separate services. In Supervisor, use separate `[program:]` blocks. See the `deployment/` directory for examples with queue routing already configured.

---

## Performance tuning

### Worker sizing

- **Memory:** 512 MB per worker process minimum. Jobs with large in-memory data need more.
- **CPU:** 1 core per 4 concurrent jobs is a reasonable starting point. CPU-bound jobs need dedicated cores.
- **Concurrency:** Start with 4, measure, adjust. IO-bound workloads (HTTP calls, email sending) can go to 16-32. CPU-bound workloads should stay at 1-2 per core.

### Graceful shutdown

Always stop workers with `SIGTERM`, not `SIGKILL`. Soniq handles `SIGTERM` by finishing in-flight jobs before exiting.

- **Systemd:** Set `TimeoutStopSec` to match your longest job timeout plus a buffer.
- **Kubernetes:** Set `terminationGracePeriodSeconds` the same way. Default is 30s, which is too short for most production workloads.
- **Supervisor:** Set `stopwaitsecs` in the program config.

If a worker is killed with `SIGKILL` (or OOM-killed), its in-flight jobs become stuck. See the [reliability guide](reliability.md) for recovery.

### Database connection pressure

Each worker process maintains its own connection pool. With many workers, total connections add up fast.

```
total_connections = num_workers * pool_max_size
```

Make sure your PostgreSQL `max_connections` can handle this, with room for your application and admin connections. See [PostgreSQL tuning](postgres.md) for pool sizing details.
