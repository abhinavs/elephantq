# 🚀 ElephantQ Production Deployment Guide

**Deploy ElephantQ to production with confidence** - This guide covers everything from simple process management to Kubernetes orchestration.

## Which Deployment Path Should You Use?

- **Systemd**: Best for single Linux servers with direct process control.
- **Supervisor**: Good for older setups or shared environments.
- **Docker Compose**: Ideal for staging or small production environments.
- **Kubernetes**: Best for containerized environments with scaling and autoscaling.

---

## 📋 Quick Start

Choose your deployment method:

| Method                                           | Best For                 | Complexity      |
| ------------------------------------------------ | ------------------------ | --------------- |
| [**Supervisor**](#supervisor-deployment)         | Simple production setups | ⭐ Easy         |
| [**systemd**](#systemd-deployment)               | Modern Linux servers     | ⭐⭐ Medium     |
| [**Docker Compose**](#docker-compose-deployment) | Containerized apps       | ⭐⭐ Medium     |
| [**Kubernetes**](#kubernetes-deployment)         | Large scale deployments  | ⭐⭐⭐ Advanced |

---

## 🔧 Prerequisites

### ✅ System Requirements

**Minimum Requirements:**

- Python 3.10+
- PostgreSQL 12+
- 2GB RAM, 2 CPU cores

**Recommended for Production:**

- Python 3.12+
- PostgreSQL 15+
- 4GB+ RAM, 4+ CPU cores
- Fast SSD storage for database

### 🗄️ Database Setup

ElephantQ works with **any PostgreSQL setup** - local, remote, or cloud:

```bash
# 1. Create database
createdb elephantq_prod

# 2. Create dedicated user (recommended)
psql -c "CREATE USER elephantq WITH PASSWORD 'your_secure_password';"
psql -c "GRANT ALL PRIVILEGES ON DATABASE elephantq_prod TO elephantq;"

# 3. Set connection URL
export ELEPHANTQ_DATABASE_URL="postgresql://elephantq:your_secure_password@localhost/elephantq_prod"

# For remote databases (AWS RDS, Google Cloud SQL, etc.)
# export ELEPHANTQ_DATABASE_URL="postgresql://user:pass@your-db-host:5432/elephantq_prod"

# 4. Initialize schema
elephantq migrate
```

✅ **Database is ready!** ElephantQ will connect automatically.

### 👤 Application User (Linux)

```bash
# Create dedicated system user
sudo useradd --system --create-home --shell /bin/bash elephantq

# Create application directories
sudo mkdir -p /opt/elephantq /var/log/elephantq
sudo chown elephantq:elephantq /opt/elephantq /var/log/elephantq
```

---

## 🎯 Deployment Methods

### 1. Supervisor Deployment ⭐

**Perfect for:** Simple production setups, shared hosting, traditional servers

#### Install Supervisor

```bash
# Ubuntu/Debian
sudo apt install supervisor

# CentOS/RHEL
sudo yum install supervisor
```

#### Setup ElephantQ

```bash
# Install in virtual environment
sudo -u elephantq python3 -m venv /opt/elephantq/venv
sudo -u elephantq /opt/elephantq/venv/bin/pip install elephantq

# Copy configuration
sudo cp supervisor.conf /etc/supervisor/conf.d/elephantq.conf

# Update database URL in the config file
sudo nano /etc/supervisor/conf.d/elephantq.conf
```

#### Start Services

```bash
# Reload supervisor configuration
sudo supervisorctl reread
sudo supervisorctl update

# Start ElephantQ services
sudo supervisorctl start elephantq_worker
sudo supervisorctl start elephantq_dashboard  # Dashboard (optional)

# Check status
sudo supervisorctl status
```

**✅ Done!** Workers are running and will auto-restart if they crash.

---

### 2. systemd Deployment ⭐⭐

**Perfect for:** Modern Linux servers, automated deployments, production environments

#### Setup ElephantQ

```bash
# Install ElephantQ
sudo -u elephantq python3 -m venv /opt/elephantq/venv
sudo -u elephantq /opt/elephantq/venv/bin/pip install elephantq

# Copy service files
sudo cp elephantq-worker.service /etc/systemd/system/
sudo cp elephantq-dashboard.service /etc/systemd/system/  # Dashboard (optional)

# Update database URLs in service files
sudo nano /etc/systemd/system/elephantq-worker.service
```

#### Configure Services

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable services (auto-start on boot)
sudo systemctl enable elephantq-worker
sudo systemctl enable elephantq-dashboard  # Dashboard (optional)

# Start services
sudo systemctl start elephantq-worker
sudo systemctl start elephantq-dashboard  # Dashboard (optional)
```

#### Monitor Services

```bash
# Check status
sudo systemctl status elephantq-worker

# View logs
sudo journalctl -u elephantq-worker -f

# Restart if needed
sudo systemctl restart elephantq-worker
```

**✅ Done!** Services are running and managed by systemd.

---

### 3. Docker Compose Deployment ⭐⭐

**Perfect for:** Containerized environments, development-to-production consistency

#### Prerequisites

- Docker 20.04+
- Docker Compose 2.0+

#### Deploy Stack

```bash
# Copy docker-compose.yml
cp docker-compose.yml /opt/elephantq/

# Set environment variables
export POSTGRES_PASSWORD=your_secure_password

# Start the complete stack
cd /opt/elephantq
docker-compose up -d
```

#### Stack Components

- **postgres** - PostgreSQL database
- **elephantq-worker** - Job processing workers
- **elephantq-dashboard** - Web dashboard (optional)

#### Monitor Stack

```bash
# View running containers
docker-compose ps

# View logs
docker-compose logs -f elephantq-worker

# Scale workers
docker-compose up -d --scale elephantq-worker=3
```

**✅ Done!** Complete ElephantQ stack running in containers.

---

### 4. Kubernetes Deployment ⭐⭐⭐

**Perfect for:** Large scale deployments, high availability, cloud environments

#### Prerequisites

- Kubernetes cluster 1.20+
- kubectl configured
- External PostgreSQL database

#### Deploy to Kubernetes

```bash
# Update database connection in kubernetes.yaml
# (Base64 encode your database URL)
echo -n "postgresql://user:pass@host/db" | base64

# Apply configuration
kubectl apply -f kubernetes.yaml

# Verify deployment
kubectl get pods -l app=elephantq
kubectl get services -l app=elephantq
```

#### Scale Workers

```bash
# Scale workers based on load
kubectl scale deployment elephantq-worker --replicas=5

# Auto-scaling (requires metrics-server)
kubectl autoscale deployment elephantq-worker --cpu-percent=70 --min=2 --max=10
```

#### Monitor Deployment

```bash
# View pod status
kubectl get pods

# View logs
kubectl logs -l app=elephantq -f

# View metrics
kubectl top pods
```

**✅ Done!** ElephantQ running in Kubernetes with scaling and monitoring.

---

## 📊 Monitoring & Maintenance

### Health Checks

```bash
# Basic health check
elephantq health --verbose

# Readiness probe (for load balancers)
elephantq ready
```

### Job Management

```bash
# View job status
elephantq jobs list --status failed --limit 20

# Monitor queues
elephantq status

# Manual job operations
elephantq jobs retry <job-id>
elephantq jobs cancel <job-id>
```

### Database Monitoring

```bash
# Check for stuck jobs
psql $ELEPHANTQ_DATABASE_URL -c "
  SELECT COUNT(*) FROM elephantq_jobs
  WHERE status='queued' AND created_at < NOW() - INTERVAL '1 hour';
"

# Connection monitoring
psql $ELEPHANTQ_DATABASE_URL -c "SELECT * FROM pg_stat_activity;"
```

### Backup Strategy

```bash
#!/bin/bash
# Daily backup script
DATE=$(date +%Y%m%d_%H%M%S)
pg_dump $ELEPHANTQ_DATABASE_URL > /backup/elephantq_backup_$DATE.sql
find /backup -name "elephantq_backup_*.sql" -mtime +7 -delete
```

---

## 🔧 Performance Tuning

### Worker Optimization

- **Memory**: 512MB per worker process minimum
- **CPU**: 1 core per 4 concurrent jobs recommended
- **Queues**: Separate queues by priority and type

  ```bash
  # Process all queues (default behavior)
  elephantq start --concurrency 4

  # Or target specific queues only
  elephantq start --queues urgent,background --concurrency 4
  ```

### Database Optimization

```sql
-- Add performance indexes
CREATE INDEX CONCURRENTLY idx_elephantq_jobs_status_queue ON elephantq_jobs(status, queue);
CREATE INDEX CONCURRENTLY idx_elephantq_jobs_scheduled_at ON elephantq_jobs(scheduled_at) WHERE scheduled_at IS NOT NULL;

-- Optimize PostgreSQL settings (in postgresql.conf)
shared_buffers = 256MB
work_mem = 4MB
max_connections = 200
```

### Connection Pooling

ElephantQ includes built-in connection pooling. For high-scale deployments:

```python
# In your ElephantQ configuration
ELEPHANTQ_DB_POOL_MIN_SIZE = 10
ELEPHANTQ_DB_POOL_MAX_SIZE = 50
```

---

## 🚨 Troubleshooting

### Common Issues

**Workers not processing jobs**

```bash
# Check database connectivity
elephantq health --verbose

# Check for stuck jobs
psql $ELEPHANTQ_DATABASE_URL -c "SELECT COUNT(*) FROM elephantq_jobs WHERE status='queued';"

# Restart workers
sudo systemctl restart elephantq-worker
```

**High memory usage**

```bash
# Reduce worker concurrency
elephantq worker --concurrency 2

# Check for memory leaks in job functions
# Monitor with: htop or ps aux
```

**Database connection errors**

```bash
# Verify connection string
echo $ELEPHANTQ_DATABASE_URL

# Test connection manually
psql $ELEPHANTQ_DATABASE_URL -c "SELECT 1;"

# Check connection limits
psql $ELEPHANTQ_DATABASE_URL -c "SELECT * FROM pg_stat_activity;"
```

### Log Analysis

```bash
# systemd logs
sudo journalctl -u elephantq-worker --since "1 hour ago"

# Supervisor logs
sudo tail -f /var/log/supervisor/elephantq_worker.log

# Docker logs
docker-compose logs --since 1h elephantq-worker
```

---

## 📞 Support

- **Documentation**: [ElephantQ Docs](https://docs.elephantq.dev)
- **Issues**: [GitHub Issues](https://github.com/abhinavs/elephantq/issues)
- **Email**: abhinav@apiclabs.com

Built by [Abhinav Saxena](https://github.com/abhinavs) with ❤️
