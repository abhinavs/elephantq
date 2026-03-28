# Deployment

This guide covers the major deployment paths for ElephantQ. Ready-to-use configuration files live in the [`deployment/`](../../deployment/) directory.

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
createdb elephantq_prod
psql -c "CREATE USER elephantq WITH PASSWORD 'your_secure_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE elephantq_prod TO elephantq;"

export ELEPHANTQ_DATABASE_URL="postgresql://elephantq:your_secure_password@localhost/elephantq_prod"
elephantq setup
```

### Application user (Linux)

```bash
sudo useradd --system --create-home --shell /bin/bash elephantq
sudo mkdir -p /opt/elephantq /var/log/elephantq
sudo chown elephantq:elephantq /opt/elephantq /var/log/elephantq
```

---

## Systemd

Best for modern Linux servers with direct process control. Files: `deployment/elephantq-worker.service` and `deployment/elephantq-dashboard.service`.

### Worker service

```ini
[Unit]
Description=ElephantQ Worker
After=network.target

[Service]
Type=exec
User=elephantq
Group=elephantq
WorkingDirectory=/opt/elephantq
Environment=ELEPHANTQ_DATABASE_URL=postgresql://elephantq:password@localhost/elephantq_prod
Environment=ELEPHANTQ_LOG_LEVEL=INFO
Environment=ELEPHANTQ_JOBS_MODULES=myapp.jobs
ExecStart=/opt/elephantq/venv/bin/elephantq start --concurrency=4
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
ReadWritePaths=/opt/elephantq /var/log/elephantq

# Resource limits
MemoryMax=512M
CPUQuota=200%

# Graceful shutdown -- match your longest job timeout
TimeoutStopSec=310

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=elephantq-worker

[Install]
WantedBy=multi-user.target
```

### Dashboard service

```ini
[Unit]
Description=ElephantQ Dashboard
After=network.target elephantq-worker.service
Wants=elephantq-worker.service

[Service]
Type=exec
User=elephantq
Group=elephantq
WorkingDirectory=/opt/elephantq
Environment=ELEPHANTQ_DATABASE_URL=postgresql://elephantq:password@localhost/elephantq_prod
Environment=ELEPHANTQ_DASHBOARD_ENABLED=true
ExecStart=/opt/elephantq/venv/bin/elephantq dashboard --host=0.0.0.0 --port=8000
Restart=always
RestartSec=5

NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/opt/elephantq /var/log/elephantq
MemoryMax=256M

StandardOutput=journal
StandardError=journal
SyslogIdentifier=elephantq-dashboard

[Install]
WantedBy=multi-user.target
```

### Managing the services

```bash
sudo cp deployment/elephantq-worker.service /etc/systemd/system/
sudo cp deployment/elephantq-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl enable elephantq-worker elephantq-dashboard
sudo systemctl start elephantq-worker elephantq-dashboard

# Check status
sudo systemctl status elephantq-worker

# View logs
sudo journalctl -u elephantq-worker -f

# Restart
sudo systemctl restart elephantq-worker
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
      POSTGRES_DB: elephantq_prod
      POSTGRES_USER: elephantq
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U elephantq -d elephantq_prod"]
      interval: 10s
      timeout: 5s
      retries: 5

  elephantq_worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    restart: always
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      ELEPHANTQ_DATABASE_URL: postgresql://elephantq:${POSTGRES_PASSWORD:-changeme}@postgres:5432/elephantq_prod
      ELEPHANTQ_JOBS_MODULES: myapp.jobs
      ELEPHANTQ_TIMEOUTS_ENABLED: "true"
      ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED: "true"
    command: ["elephantq", "start", "--concurrency=4"]
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "1.0"

  elephantq_dashboard:
    build:
      context: .
      dockerfile: Dockerfile.dashboard
    restart: always
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      ELEPHANTQ_DATABASE_URL: postgresql://elephantq:${POSTGRES_PASSWORD:-changeme}@postgres:5432/elephantq_prod
      ELEPHANTQ_DASHBOARD_ENABLED: "true"
    ports:
      - "8000:8000"
    command: ["elephantq", "dashboard", "--host=0.0.0.0", "--port=8000"]

volumes:
  postgres_data:
```

### Scaling workers

```bash
docker-compose up -d --scale elephantq_worker=3
```

---

## Kubernetes

Best for containerized environments with autoscaling. File: `deployment/kubernetes.yaml`.

### Secret and ConfigMap

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: elephantq-secrets
  namespace: elephantq
type: Opaque
data:
  # echo -n "postgresql://user:pass@host/db" | base64
  ELEPHANTQ_DATABASE_URL: <base64-encoded-url>

---
apiVersion: v1
kind: ConfigMap
metadata:
  name: elephantq-config
  namespace: elephantq
data:
  ELEPHANTQ_LOG_LEVEL: "INFO"
  ELEPHANTQ_JOBS_MODULES: "myapp.jobs"
  ELEPHANTQ_TIMEOUTS_ENABLED: "true"
  ELEPHANTQ_DEAD_LETTER_QUEUE_ENABLED: "true"
  ELEPHANTQ_METRICS_ENABLED: "true"
```

### Worker Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: elephantq-worker
  namespace: elephantq
spec:
  replicas: 3
  selector:
    matchLabels:
      app: elephantq-worker
  template:
    metadata:
      labels:
        app: elephantq-worker
    spec:
      terminationGracePeriodSeconds: 310  # match your longest job timeout
      containers:
      - name: worker
        image: elephantq/worker:latest
        args: ["elephantq", "start", "--concurrency=4"]
        env:
        - name: ELEPHANTQ_DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: elephantq-secrets
              key: ELEPHANTQ_DATABASE_URL
        envFrom:
        - configMapRef:
            name: elephantq-config
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          exec:
            command: ["elephantq", "health"]
          initialDelaySeconds: 30
          periodSeconds: 30
        readinessProbe:
          exec:
            command: ["elephantq", "ready"]
          initialDelaySeconds: 5
          periodSeconds: 10
```

### Dashboard Deployment + Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: elephantq-dashboard
  namespace: elephantq
spec:
  replicas: 2
  selector:
    matchLabels:
      app: elephantq-dashboard
  template:
    metadata:
      labels:
        app: elephantq-dashboard
    spec:
      containers:
      - name: dashboard
        image: elephantq/dashboard:latest
        args: ["elephantq", "dashboard", "--host=0.0.0.0", "--port=8000"]
        env:
        - name: ELEPHANTQ_DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: elephantq-secrets
              key: ELEPHANTQ_DATABASE_URL
        envFrom:
        - configMapRef:
            name: elephantq-config
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
  name: elephantq-dashboard
  namespace: elephantq
spec:
  selector:
    app: elephantq-dashboard
  ports:
  - port: 80
    targetPort: 8000
  type: ClusterIP
```

### Autoscaling

```bash
kubectl autoscale deployment elephantq-worker \
  --namespace=elephantq \
  --cpu-percent=70 \
  --min=2 --max=10
```

The `deployment/kubernetes.yaml` file also includes an HPA manifest and a ServiceMonitor for Prometheus.

---

## Supervisor

Good for older setups or shared environments. File: `deployment/supervisor.conf`.

```ini
[group:elephantq]
programs=elephantq_worker,elephantq_dashboard

[program:elephantq_worker]
command=/opt/elephantq/venv/bin/elephantq start --concurrency=4
directory=/opt/elephantq
user=elephantq
autostart=true
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/var/log/elephantq/worker.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=5
environment=ELEPHANTQ_DATABASE_URL="postgresql://elephantq:password@localhost/elephantq_prod",ELEPHANTQ_LOG_LEVEL="INFO",ELEPHANTQ_JOBS_MODULES="myapp.jobs"

[program:elephantq_dashboard]
command=/opt/elephantq/venv/bin/elephantq dashboard --host=0.0.0.0 --port=8000
directory=/opt/elephantq
user=elephantq
autostart=true
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/var/log/elephantq/dashboard.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=5
environment=ELEPHANTQ_DATABASE_URL="postgresql://elephantq:password@localhost/elephantq_prod",ELEPHANTQ_DASHBOARD_ENABLED="true"
```

### Managing with Supervisor

```bash
sudo cp deployment/supervisor.conf /etc/supervisor/conf.d/elephantq.conf
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start elephantq_worker
sudo supervisorctl status
```

---

## Queue routing

When different queues have different throughput or latency needs, run separate worker processes per queue group. Each scales independently.

```bash
# Email workers -- high concurrency, IO-bound
elephantq start --concurrency=8 --queues=emails,notifications

# Media workers -- low concurrency, CPU-bound
elephantq start --concurrency=2 --queues=media,transcode
```

In Kubernetes, use separate Deployments. In Docker Compose, use separate services. In Supervisor, use separate `[program:]` blocks. See the `deployment/` directory for examples with queue routing already configured.

---

## Performance tuning

### Worker sizing

- **Memory:** 512 MB per worker process minimum. Jobs with large in-memory data need more.
- **CPU:** 1 core per 4 concurrent jobs is a reasonable starting point. CPU-bound jobs need dedicated cores.
- **Concurrency:** Start with 4, measure, adjust. IO-bound workloads (HTTP calls, email sending) can go to 16-32. CPU-bound workloads should stay at 1-2 per core.

### Graceful shutdown

Always stop workers with `SIGTERM`, not `SIGKILL`. ElephantQ handles `SIGTERM` by finishing in-flight jobs before exiting.

- **Systemd:** Set `TimeoutStopSec` to match your longest job timeout plus a buffer.
- **Kubernetes:** Set `terminationGracePeriodSeconds` the same way. Default is 30s, which is too short for most production workloads.
- **Supervisor:** Set `stopwaitsecs` in the program config.

If a worker is killed with `SIGKILL` (or OOM-killed), its in-flight jobs become stuck. See the [reliability guide](reliability.md) for recovery.

### Database connection pressure

Each worker process maintains its own connection pool. With many workers, total connections add up fast.

```
total_connections = num_workers * pool_max_size
```

Make sure your Postgres `max_connections` can handle this, with room for your application and admin connections. See [PostgreSQL tuning](postgres.md) for pool sizing details.
