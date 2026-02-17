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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0f1220;
            --bg-soft: #161a2e;
            --panel: #1b213b;
            --panel-2: #141a30;
            --text: #eef1ff;
            --muted: #b6bdd8;
            --accent: #f4b266;
            --accent-2: #72e3a7;
            --danger: #ff6b6b;
            --warning: #ffd166;
            --shadow: rgba(0, 0, 0, 0.35);
            --border: rgba(255, 255, 255, 0.08);
        }

        [data-theme="light"] {
            --bg: #f6f4ef;
            --bg-soft: #f2efe9;
            --panel: #ffffff;
            --panel-2: #f5f2ec;
            --text: #1c1c1c;
            --muted: #5b6270;
            --accent: #ffb04a;
            --accent-2: #2aa07a;
            --danger: #e04b4b;
            --warning: #d9a441;
            --shadow: rgba(0, 0, 0, 0.12);
            --border: rgba(0, 0, 0, 0.08);
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: 'Space Grotesk', system-ui, sans-serif;
            background: radial-gradient(1200px 800px at 20% -10%, var(--bg-soft) 0%, var(--bg) 55%) fixed;
            color: var(--text);
        }
        .page {
            max-width: 1200px;
            margin: 0 auto;
            padding: 28px 20px 60px;
        }
        .topbar {
            display: flex;
            gap: 16px;
            align-items: center;
            justify-content: space-between;
            background: linear-gradient(135deg, #2d2f55 0%, #1c2542 100%);
            border: 1px solid var(--border);
            padding: 18px 22px;
            border-radius: 16px;
            box-shadow: 0 12px 30px var(--shadow);
            margin-bottom: 22px;
        }
        .title {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .title h1 {
            font-size: 28px;
            margin: 0;
            letter-spacing: 0.5px;
        }
        .title p {
            margin: 0;
            color: var(--muted);
            font-size: 14px;
        }
        .pill {
            font-family: 'IBM Plex Mono', ui-monospace, monospace;
            font-size: 12px;
            padding: 6px 10px;
            border-radius: 999px;
            background: var(--panel-2);
            border: 1px solid var(--border);
            color: var(--muted);
        }
        .topbar-actions {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: linear-gradient(160deg, #202749 0%, #141a30 100%);
            border: 1px solid var(--border);
            padding: 18px;
            border-radius: 14px;
            box-shadow: 0 10px 22px var(--shadow);
        }
        .stat-number {
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 6px;
        }
        .stat-label {
            color: var(--muted);
            font-size: 13px;
        }
        .section {
            background: var(--panel);
            border: 1px solid var(--border);
            padding: 18px;
            border-radius: 16px;
            margin-bottom: 18px;
            box-shadow: 0 10px 22px var(--shadow);
        }
        .section h2 {
            margin: 0 0 12px 0;
            font-size: 18px;
            color: var(--accent);
        }
        .table-wrap {
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            min-width: 720px;
        }
        th, td {
            padding: 12px 10px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            text-align: left;
            font-size: 13px;
            color: var(--text);
        }
        th {
            color: var(--muted);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            font-size: 11px;
        }
        .status-badge {
            padding: 4px 8px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .status-done { background: rgba(114, 227, 167, 0.18); color: #bdf7d9; }
        .status-queued { background: rgba(255, 209, 102, 0.18); color: #ffe2a3; }
        .status-failed { background: rgba(255, 107, 107, 0.18); color: #ffc0c0; }
        .status-dead_letter { background: rgba(255, 107, 107, 0.12); color: #ffb0b0; }
        .loading {
            text-align: center;
            padding: 16px;
            color: var(--muted);
            font-size: 14px;
        }
        .refresh-info {
            text-align: center;
            color: var(--muted);
            font-size: 12px;
            margin-top: 20px;
        }
        .notice {
            background: rgba(255, 209, 102, 0.16);
            border: 1px solid rgba(255, 209, 102, 0.4);
            color: #ffe2a3;
            padding: 10px 14px;
            border-radius: 10px;
            font-size: 12px;
            margin-bottom: 14px;
        }
        .btn {
            background: var(--accent);
            color: #1a1a1a;
            border: none;
            padding: 7px 12px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 12px;
            margin: 2px;
            font-weight: 600;
        }
        .btn-ghost {
            background: transparent;
            color: var(--text);
            border: 1px solid var(--border);
        }
        .btn:hover { opacity: 0.9; }
        .btn-danger {
            background: var(--danger);
            color: #1a1a1a;
        }
        @media (max-width: 820px) {
            .topbar { flex-direction: column; align-items: flex-start; }
            table { min-width: 540px; }
        }
        @media (max-width: 520px) {
            .page { padding: 18px 14px 40px; }
            .stat-number { font-size: 24px; }
        }
    </style>
</head>
<body>
    <div class="page">
        <div class="topbar">
            <div class="title">
                <h1>ElephantQ Dashboard</h1>
                <p>Real-time job monitoring and system signals</p>
            </div>
            <div class="topbar-actions">
                <button class="btn btn-ghost" id="theme-toggle" type="button">Theme: system</button>
                <div class="pill">Auto-refresh: 30s</div>
            </div>
        </div>

        <div id="mode-notice"></div>
        <div class="stats-grid" id="stats-grid">
            <div class="loading">Loading statistics...</div>
        </div>

        <div class="section">
            <h2>Recent Jobs</h2>
            <div class="table-wrap" id="jobs-table">
                <div class="loading">Loading jobs...</div>
            </div>
        </div>

        <div class="section">
            <h2>Queue Statistics</h2>
            <div class="table-wrap" id="queue-stats">
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
    </div>

    <script>
        const CAN_WRITE = __ELEPHANTQ_CAN_WRITE__;
        const THEME_KEY = 'elephantq_theme';
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');

        function applyTheme(theme) {
            if (theme === 'system') {
                document.documentElement.removeAttribute('data-theme');
            } else {
                document.documentElement.setAttribute('data-theme', theme);
            }
            const label = theme === 'system' ? (prefersDark.matches ? 'dark (system)' : 'light (system)') : theme;
            const btn = document.getElementById('theme-toggle');
            if (btn) btn.textContent = `Theme: ${label}`;
        }

        function getStoredTheme() {
            return localStorage.getItem(THEME_KEY) || 'system';
        }

        function cycleTheme() {
            const current = getStoredTheme();
            const next = current === 'system' ? 'light' : current === 'light' ? 'dark' : 'system';
            localStorage.setItem(THEME_KEY, next);
            applyTheme(next);
        }

        window.addEventListener('DOMContentLoaded', () => {
            applyTheme(getStoredTheme());
            const btn = document.getElementById('theme-toggle');
            if (btn) btn.addEventListener('click', cycleTheme);
            prefersDark.addEventListener('change', () => {
                if (getStoredTheme() === 'system') applyTheme('system');
            });
        });


        async function fetchData(url) {
            try {
                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return await response.json();
            } catch (error) {
                console.error('Error fetching data:', error);
                return null;
            }
        }

        function formatDate(dateStr) {
            if (!dateStr) return '-';
            const date = new Date(dateStr);
            return date.toLocaleString();
        }

        function formatDuration(ms) {
            if (!ms) return '-';
            if (ms < 1000) return `${ms.toFixed(0)}ms`;
            if (ms < 60000) return `${(ms/1000).toFixed(1)}s`;
            return `${(ms/60000).toFixed(1)}m`;
        }

        async function updateStats() {
            const stats = await fetchData('/api/stats');
            if (!stats) return;

            const html = `
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
                    <div class="stat-label">Done</div>
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

            document.getElementById('stats-grid').innerHTML = html;
        }

        function updateModeNotice() {
            const notice = document.getElementById('mode-notice');
            if (!notice) return;
            if (CAN_WRITE !== 'true') {
                notice.innerHTML = '<div class="notice">Dashboard is in read-only mode. Set ELEPHANTQ_DASHBOARD_WRITE_ENABLED=true to enable actions.</div>';
            } else {
                notice.innerHTML = '';
            }
        }

        async function updateJobs() {
            const jobs = await fetchData('/api/jobs');
            if (!jobs) return;

            let html = `
                <table>
                    <thead>
                        <tr>
                            <th>Job</th>
                            <th>Status</th>
                            <th>Queue</th>
                            <th>Attempts</th>
                            <th>Created</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            jobs.forEach(job => {
                html += `
                    <tr>
                        <td>${job.job_name.split('.').pop()}</td>
                        <td><span class="status-badge status-${job.status}">${job.status}</span></td>
                        <td>${job.queue}</td>
                        <td>${job.attempts}/${job.max_attempts}</td>
                        <td>${formatDate(job.created_at)}</td>
                        <td>
                            ${CAN_WRITE === 'true' ? `
                                <button class="btn" onclick="retryJob('${job.id}')">Retry</button>
                                <button class="btn btn-danger" onclick="deleteJob('${job.id}')">Delete</button>
                            ` : ''}
                        </td>
                    </tr>
                `;
            });

            html += '</tbody></table>';
            document.getElementById('jobs-table').innerHTML = html;
        }

        async function updateQueueStats() {
            try {
                const queues = await fetchData('/api/queues');
                if (!queues) return;

                if (!Array.isArray(queues) || queues.length === 0) {
                    document.getElementById('queue-stats').innerHTML = '<div class="loading">No queues yet</div>';
                    return;
                }

                let html = `
                    <table>
                        <thead>
                            <tr>
                                <th>Queue</th>
                                <th>Total</th>
                                <th>Queued</th>
                                <th>Done</th>
                                <th>Failed</th>
                                <th>Dead Letter</th>
                                <th>Avg Processing</th>
                            </tr>
                        </thead>
                        <tbody>
                `;

                queues.forEach(queue => {
                    html += `
                        <tr>
                            <td>${queue.queue}</td>
                            <td>${queue.total_jobs}</td>
                            <td>${queue.queued}</td>
                            <td>${queue.done}</td>
                            <td>${queue.failed}</td>
                            <td>${queue.dead_letter}</td>
                            <td>${formatDuration(queue.avg_processing_time_ms)}</td>
                        </tr>
                    `;
                });

                html += '</tbody></table>';
                document.getElementById('queue-stats').innerHTML = html;
            } catch (error) {
                console.error('Error updating queue stats:', error);
                document.getElementById('queue-stats').innerHTML = '<div class="loading">Unable to load queue stats</div>';
            }
        }

        async function updateMetrics() {
            const metrics = await fetchData('/api/metrics');
            if (!metrics) return;

            const html = `
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-number">${metrics.total_processed}</div>
                        <div class="stat-label">Processed</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${metrics.successful}</div>
                        <div class="stat-label">Successful</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${metrics.failed}</div>
                        <div class="stat-label">Failed</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${metrics.success_rate}%</div>
                        <div class="stat-label">Success Rate</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${formatDuration(metrics.avg_processing_time_ms)}</div>
                        <div class="stat-label">Avg Time</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number">${metrics.jobs_per_hour}</div>
                        <div class="stat-label">Jobs/Hour</div>
                    </div>
                </div>
            `;

            document.getElementById('metrics').innerHTML = html;
        }

        async function retryJob(jobId) {
            if (!confirm('Retry this job?')) return;
            try {
                const response = await fetch(`/api/jobs/${jobId}/retry`, { method: 'POST' });
                if (response.ok) {
                    await updateAll();
                }
            } catch (error) {
                console.error('Error retrying job:', error);
            }
        }

        async function deleteJob(jobId) {
            if (!confirm('Delete this job?')) return;
            try {
                const response = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
                if (response.ok) {
                    await updateAll();
                }
            } catch (error) {
                console.error('Error deleting job:', error);
            }
        }

        async function updateAll() {
            updateModeNotice();
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
