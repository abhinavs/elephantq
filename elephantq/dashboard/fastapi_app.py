"""
FastAPI web dashboard for ElephantQ.
"""

from typing import Dict, List, Any, Optional

try:
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from .app import (
    get_job_stats,
    get_recent_jobs,
    get_queue_stats,
    get_job_metrics,
    get_job_details,
    retry_job,
    delete_job,
    cancel_job,
    get_worker_stats,
    get_job_timeline,
    get_job_types_stats,
    search_jobs,
    get_system_health,
)
from elephantq.settings import get_settings


def create_dashboard_app() -> "FastAPI":
    """Create FastAPI dashboard application"""
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI is required for dashboard. Install with: pip install fastapi uvicorn")

    settings = get_settings()
    if not settings.dashboard_enabled:
        raise RuntimeError("Dashboard is disabled. Set ELEPHANTQ_DASHBOARD_ENABLED=true")
    
    app = FastAPI(
        title="ElephantQ Dashboard",
        description="Real-time job monitoring and management",
        version="1.0.0"
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/", response_class=HTMLResponse)
    async def dashboard_home():
        """Main dashboard page"""
        return get_dashboard_html()
    
    @app.get("/api/stats")
    async def api_job_stats() -> Dict[str, int]:
        """Get job statistics by status"""
        return await get_job_stats()
    
    @app.get("/api/jobs")
    async def api_recent_jobs(limit: int = 50, queue: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent jobs"""
        return await get_recent_jobs(limit=limit, queue=queue)
    
    @app.get("/api/queues")
    async def api_queue_stats() -> List[Dict[str, Any]]:
        """Get queue statistics"""
        return await get_queue_stats()
    
    @app.get("/api/metrics")
    async def api_job_metrics(hours: int = 24) -> Dict[str, Any]:
        """Get job processing metrics"""
        return await get_job_metrics(hours=hours)
    
    @app.get("/api/jobs/{job_id}")
    async def api_job_details(job_id: str) -> Dict[str, Any]:
        """Get job details"""
        job = await get_job_details(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job
    
    @app.post("/api/jobs/{job_id}/retry")
    async def api_retry_job(job_id: str) -> Dict[str, str]:
        """Retry a failed job"""
        if not settings.dashboard_write_enabled:
            raise HTTPException(status_code=403, detail="Dashboard write actions are disabled")
        success = await retry_job(job_id)
        if not success:
            raise HTTPException(status_code=400, detail="Unable to retry job")
        return {"message": "Job queued for retry"}
    
    @app.delete("/api/jobs/{job_id}")
    async def api_delete_job(job_id: str) -> Dict[str, str]:
        """Delete a job"""
        if not settings.dashboard_write_enabled:
            raise HTTPException(status_code=403, detail="Dashboard write actions are disabled")
        success = await delete_job(job_id)
        if not success:
            raise HTTPException(status_code=400, detail="Unable to delete job")
        return {"message": "Job deleted"}
    
    @app.post("/api/jobs/{job_id}/cancel")
    async def api_cancel_job(job_id: str) -> Dict[str, str]:
        """Cancel a queued job"""
        if not settings.dashboard_write_enabled:
            raise HTTPException(status_code=403, detail="Dashboard write actions are disabled")
        success = await cancel_job(job_id)
        if not success:
            raise HTTPException(status_code=400, detail="Unable to cancel job")
        return {"message": "Job cancelled"}
    
    @app.get("/api/workers/stats")
    async def api_worker_stats() -> Dict[str, Any]:
        """Get worker statistics and health information"""
        return await get_worker_stats()
    
    @app.get("/api/jobs/timeline")
    async def api_job_timeline(hours: int = 24) -> List[Dict[str, Any]]:
        """Get job processing timeline for visualization"""
        return await get_job_timeline(hours=hours)
    
    @app.get("/api/jobs/types")
    async def api_job_types_stats() -> List[Dict[str, Any]]:
        """Get statistics grouped by job type/name"""
        return await get_job_types_stats()
    
    @app.get("/api/jobs/search")
    async def api_search_jobs(
        query: Optional[str] = None,
        status: Optional[str] = None,
        queue: Optional[str] = None,
        job_name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Search and filter jobs with pagination"""
        return await search_jobs(
            query=query,
            status=status,
            queue=queue,
            job_name=job_name,
            limit=limit,
            offset=offset
        )
    
    @app.get("/api/system/health")
    async def api_system_health() -> Dict[str, Any]:
        """Get overall system health metrics"""
        return await get_system_health()
    
    return app


def get_dashboard_html() -> str:
    """Generate dashboard HTML"""
    from elephantq.settings import get_settings

    can_write = str(get_settings().dashboard_write_enabled).lower()
    html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ElephantQ Dashboard</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f7fa;
            color: #333;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }
        .stat-number {
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 5px;
        }
        .stat-label {
            color: #666;
            font-size: 0.9em;
        }
        .section {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .section h2 {
            margin-top: 0;
            color: #667eea;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        th {
            background-color: #f8f9fa;
            font-weight: 600;
        }
        .status-badge {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            font-weight: bold;
        }
        .status-done { background-color: #d4edda; color: #155724; }
        .status-queued { background-color: #fff3cd; color: #856404; }
        .status-failed { background-color: #f8d7da; color: #721c24; }
        .status-dead_letter { background-color: #f5c6cb; color: #491217; }
        .loading {
            text-align: center;
            padding: 20px;
            color: #666;
        }
        .refresh-info {
            text-align: center;
            color: #666;
            font-size: 0.9em;
            margin-top: 20px;
        }
        .btn {
            background: #667eea;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.9em;
            margin: 2px;
        }
        .btn:hover {
            background: #5a6fd8;
        }
        .btn-danger {
            background: #dc3545;
        }
        .btn-danger:hover {
            background: #c82333;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>ElephantQ Dashboard</h1>
        <p>Real-time job monitoring and management</p>
    </div>

    <div class="stats-grid" id="stats-grid">
        <div class="loading">Loading statistics...</div>
    </div>

    <div class="section">
        <h2>Recent Jobs</h2>
        <div id="jobs-table">
            <div class="loading">Loading jobs...</div>
        </div>
    </div>

    <div class="section">
        <h2>Queue Statistics</h2>
        <div id="queue-stats">
            <div class="loading">Loading queue stats...</div>
        </div>
    </div>

    <div class="section">
        <h2>Performance Metrics (24h)</h2>
        <div id="metrics">
            <div class="loading">Loading metrics...</div>
        </div>
    </div>

    <div class="refresh-info">
        Dashboard auto-refreshes every 30 seconds
    </div>

    <script>
        const CAN_WRITE = __ELEPHANTQ_CAN_WRITE__;
        async function fetchData(url) {
            try {
                const response = await fetch(url);
                return await response.json();
            } catch (error) {
                console.error('Error fetching data:', error);
                return null;
            }
        }

        function formatDate(dateString) {
            return new Date(dateString).toLocaleString();
        }

        function createStatusBadge(status) {
            return `<span class="status-badge status-${status}">${status}</span>`;
        }

        async function updateStats() {
            const stats = await fetchData('/api/stats');
            if (!stats) return;

            document.getElementById('stats-grid').innerHTML = `
                <div class="stat-card">
                    <div class="stat-number">${stats.total}</div>
                    <div class="stat-label">Total Jobs</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${stats.queued}</div>
                    <div class="stat-label">Queued</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${stats.done}</div>
                    <div class="stat-label">Completed</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${stats.failed}</div>
                    <div class="stat-label">Failed</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">${stats.dead_letter}</div>
                    <div class="stat-label">Dead Letter</div>
                </div>
            `;
        }

        async function updateJobs() {
            const jobs = await fetchData('/api/jobs?limit=20');
            if (!jobs) return;

            let tableHtml = `
                <table>
                    <thead>
                        <tr>
                            <th>Job Name</th>
                            <th>Status</th>
                            <th>Queue</th>
                            <th>Priority</th>
                            <th>Attempts</th>
                            <th>Created</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            jobs.forEach(job => {
                tableHtml += `
                    <tr>
                        <td>${job.job_name}</td>
                        <td>${createStatusBadge(job.status)}</td>
                        <td>${job.queue}</td>
                        <td>${job.priority}</td>
                        <td>${job.attempts}/${job.max_attempts}</td>
                        <td>${formatDate(job.created_at)}</td>
                        <td>
                            ${CAN_WRITE && (job.status === 'failed' || job.status === 'dead_letter') ? 
                                `<button class="btn" onclick="retryJob('${job.id}')">Retry</button>` : ''
                            }
                            ${CAN_WRITE ? `<button class="btn btn-danger" onclick="deleteJob('${job.id}')">Delete</button>` : ''}
                        </td>
                    </tr>
                `;
            });

            tableHtml += '</tbody></table>';
            document.getElementById('jobs-table').innerHTML = tableHtml;
        }

        async function updateQueueStats() {
            const queues = await fetchData('/api/queues');
            if (!queues) return;

            let tableHtml = `
                <table>
                    <thead>
                        <tr>
                            <th>Queue</th>
                            <th>Total Jobs</th>
                            <th>Queued</th>
                            <th>Done</th>
                            <th>Failed</th>
                            <th>Avg Processing (ms)</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            queues.forEach(queue => {
                tableHtml += `
                    <tr>
                        <td><strong>${queue.queue}</strong></td>
                        <td>${queue.total_jobs}</td>
                        <td>${queue.queued}</td>
                        <td>${queue.done}</td>
                        <td>${queue.failed + queue.dead_letter}</td>
                        <td>${queue.avg_processing_time_ms ? Math.round(queue.avg_processing_time_ms) : 'N/A'}</td>
                    </tr>
                `;
            });

            tableHtml += '</tbody></table>';
            document.getElementById('queue-stats').innerHTML = tableHtml;
        }

        async function updateMetrics() {
            const metrics = await fetchData('/api/metrics');
            if (!metrics) return;

            document.getElementById('metrics').innerHTML = `
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-number">${metrics.total_processed}</div>
                        <div class="stat-label">Jobs Processed</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${metrics.success_rate}%</div>
                        <div class="stat-label">Success Rate</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${metrics.avg_processing_time_ms}ms</div>
                        <div class="stat-label">Avg Processing Time</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${metrics.jobs_per_hour}</div>
                        <div class="stat-label">Jobs/Hour</div>
                    </div>
                </div>
            `;
        }

        async function retryJob(jobId) {
            if (!CAN_WRITE) return;
            try {
                const response = await fetch(`/api/jobs/${jobId}/retry`, { method: 'POST' });
                if (response.ok) {
                    alert('Job queued for retry');
                    await updateAll();
                } else {
                    alert('Failed to retry job');
                }
            } catch (error) {
                alert('Error retrying job');
            }
        }

        async function deleteJob(jobId) {
            if (!CAN_WRITE) return;
            if (!confirm('Are you sure you want to delete this job?')) return;
            
            try {
                const response = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
                if (response.ok) {
                    alert('Job deleted');
                    await updateAll();
                } else {
                    alert('Failed to delete job');
                }
            } catch (error) {
                alert('Error deleting job');
            }
        }

        async function updateAll() {
            await Promise.all([
                updateStats(),
                updateJobs(),
                updateQueueStats(),
                updateMetrics()
            ]);
        }

        // Initial load
        updateAll();

        // Auto-refresh every 30 seconds
        setInterval(updateAll, 30000);
    </script>
</body>
</html>
'''
    return html.replace("__ELEPHANTQ_CAN_WRITE__", can_write)


async def run_dashboard(host: str = "127.0.0.1", port: int = 6161):
    """Run the dashboard server"""
    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI is required for dashboard. Install with: pip install fastapi uvicorn")
    
    app = create_dashboard_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    
    print(f"ElephantQ Dashboard starting at http://{host}:{port}")
    print("Press Ctrl+C to stop")
    
    await server.serve()
