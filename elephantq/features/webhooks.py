"""
Webhook System for Job Lifecycle Notifications.
HTTP notifications for job events (success, failure, dead letter).
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import hmac
import uuid
import logging

import aiohttp
import asyncpg
from elephantq.db.connection import get_pool
from .security import SecureWebhookSecret


logger = logging.getLogger(__name__)


class WebhookEvent(str, Enum):
    """Webhook event types"""
    JOB_QUEUED = "job.queued"
    JOB_STARTED = "job.started"
    JOB_COMPLETED = "job.completed"
    JOB_FAILED = "job.failed"
    JOB_RETRIED = "job.retried"
    JOB_DEAD_LETTER = "job.dead_letter"
    JOB_RESURRECTED = "job.resurrected"
    QUEUE_BACKLOG = "queue.backlog"
    SYSTEM_ALERT = "system.alert"


@dataclass
class WebhookPayload:
    """Webhook payload structure"""
    event: str
    timestamp: str
    data: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WebhookEndpoint:
    """Webhook endpoint configuration"""
    id: str
    url: str
    secret: Optional[str] = None
    events: List[str] = None  # None means all events
    active: bool = True
    max_retries: int = 3
    timeout_seconds: int = 30
    headers: Optional[Dict[str, str]] = None
    _secure_secret: Optional[SecureWebhookSecret] = None
    
    def __post_init__(self):
        if self.events is None:
            self.events = [event.value for event in WebhookEvent]
        
        # Initialize secure secret wrapper
        if self.secret:
            self._secure_secret = SecureWebhookSecret(self.secret)
            # Store encrypted version in the secret field for database storage
            self.secret = self._secure_secret.encrypted
    
    @property
    def plaintext_secret(self) -> Optional[str]:
        """Get the plaintext secret for signing/verification"""
        if self._secure_secret:
            return self._secure_secret.plaintext
        return None
    
    @property 
    def encrypted_secret(self) -> Optional[str]:
        """Get the encrypted secret for database storage"""
        return self.secret


@dataclass
class WebhookDelivery:
    """Webhook delivery record"""
    id: str
    endpoint_id: str
    event: str
    payload: Dict[str, Any]
    status: str  # pending, delivered, failed, expired
    attempts: int = 0
    max_attempts: int = 3
    next_retry_at: Optional[datetime] = None
    last_error: Optional[str] = None
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    created_at: datetime = None
    delivered_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


class WebhookSigner:
    """Webhook payload signing for security"""
    
    @staticmethod
    def sign_payload(payload: str, secret: str) -> str:
        """Sign webhook payload with HMAC-SHA256"""
        signature = hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"
    
    @staticmethod
    def verify_signature(payload: str, signature: str, secret: str) -> bool:
        """Verify webhook signature"""
        expected_signature = WebhookSigner.sign_payload(payload, secret)
        return hmac.compare_digest(signature, expected_signature)


class WebhookRegistry:
    """Registry for webhook endpoints"""
    
    def __init__(self):
        self.endpoints: Dict[str, WebhookEndpoint] = {}
        self._lock = asyncio.Lock()
    
    async def register_endpoint(self, endpoint: WebhookEndpoint) -> str:
        """Register a webhook endpoint"""
        async with self._lock:
            endpoint_id = endpoint.id or str(uuid.uuid4())
            endpoint.id = endpoint_id
            self.endpoints[endpoint_id] = endpoint
            
            # Persist to database
            await self._save_endpoint_to_db(endpoint)
            
        logger.info(f"Registered webhook endpoint: {endpoint_id} -> {endpoint.url}")
        return endpoint_id
    
    async def unregister_endpoint(self, endpoint_id: str) -> bool:
        """Unregister a webhook endpoint"""
        async with self._lock:
            if endpoint_id in self.endpoints:
                del self.endpoints[endpoint_id]
                await self._delete_endpoint_from_db(endpoint_id)
                logger.info(f"Unregistered webhook endpoint: {endpoint_id}")
                return True
        return False
    
    async def get_endpoint(self, endpoint_id: str) -> Optional[WebhookEndpoint]:
        """Get webhook endpoint by ID"""
        return self.endpoints.get(endpoint_id)
    
    async def get_endpoints_for_event(self, event: WebhookEvent) -> List[WebhookEndpoint]:
        """Get all active endpoints that subscribe to an event"""
        return [
            endpoint for endpoint in self.endpoints.values()
            if endpoint.active and (
                not endpoint.events or event.value in endpoint.events
            )
        ]
    
    async def list_endpoints(self) -> List[WebhookEndpoint]:
        """List all registered endpoints"""
        return list(self.endpoints.values())
    
    async def update_endpoint(self, endpoint_id: str, **updates) -> bool:
        """Update webhook endpoint configuration"""
        async with self._lock:
            if endpoint_id in self.endpoints:
                endpoint = self.endpoints[endpoint_id]
                for key, value in updates.items():
                    if hasattr(endpoint, key):
                        setattr(endpoint, key, value)
                
                await self._save_endpoint_to_db(endpoint)
                logger.info(f"Updated webhook endpoint: {endpoint_id}")
                return True
        return False
    
    async def _save_endpoint_to_db(self, endpoint: WebhookEndpoint):
        """Save endpoint configuration to database"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO elephantq_webhook_endpoints (
                    id, url, secret, events, active, max_retries, timeout_seconds, headers
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    url = EXCLUDED.url,
                    secret = EXCLUDED.secret,
                    events = EXCLUDED.events,
                    active = EXCLUDED.active,
                    max_retries = EXCLUDED.max_retries,
                    timeout_seconds = EXCLUDED.timeout_seconds,
                    headers = EXCLUDED.headers,
                    updated_at = NOW()
            """, 
                endpoint.id,
                endpoint.url,
                endpoint.secret,
                json.dumps(endpoint.events),
                endpoint.active,
                endpoint.max_retries,
                endpoint.timeout_seconds,
                json.dumps(endpoint.headers) if endpoint.headers else None
            )
    
    async def _delete_endpoint_from_db(self, endpoint_id: str):
        """Delete endpoint from database"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM elephantq_webhook_endpoints WHERE id = $1",
                endpoint_id
            )
    
    async def load_endpoints_from_db(self):
        """Load endpoints from database on startup"""
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                # Ensure webhook tables exist
                await self._ensure_webhook_tables(conn)
                
                # Load endpoints
                endpoints = await conn.fetch("""
                    SELECT * FROM elephantq_webhook_endpoints WHERE active = true
                """)
                
                async with self._lock:
                    for row in endpoints:
                        endpoint = WebhookEndpoint(
                            id=row['id'],
                            url=row['url'],
                            secret=row['secret'],
                            events=json.loads(row['events']) if row['events'] else None,
                            active=row['active'],
                            max_retries=row['max_retries'],
                            timeout_seconds=row['timeout_seconds'],
                            headers=json.loads(row['headers']) if row['headers'] else None
                        )
                        self.endpoints[endpoint.id] = endpoint
                
                logger.info(f"Loaded {len(endpoints)} webhook endpoints from database")
                
        except Exception as e:
            logger.error(f"Failed to load webhook endpoints: {e}")
    
    async def _ensure_webhook_tables(self, conn: asyncpg.Connection):
        """Ensure webhook tables exist"""
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS elephantq_webhook_endpoints (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                secret TEXT,
                events JSONB,
                active BOOLEAN DEFAULT true,
                max_retries INTEGER DEFAULT 3,
                timeout_seconds INTEGER DEFAULT 30,
                headers JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS elephantq_webhook_deliveries (
                id TEXT PRIMARY KEY,
                endpoint_id TEXT NOT NULL,
                event TEXT NOT NULL,
                payload JSONB NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                next_retry_at TIMESTAMP WITH TIME ZONE,
                last_error TEXT,
                response_status INTEGER,
                response_body TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                delivered_at TIMESTAMP WITH TIME ZONE,
                
                FOREIGN KEY (endpoint_id) REFERENCES elephantq_webhook_endpoints(id) ON DELETE CASCADE
            );
            
            CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON elephantq_webhook_deliveries(status);
            CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_next_retry ON elephantq_webhook_deliveries(next_retry_at);
            CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_endpoint ON elephantq_webhook_deliveries(endpoint_id);
        """)


class WebhookDispatcher:
    """Webhook event dispatcher and delivery manager"""
    
    def __init__(self, registry: WebhookRegistry, max_concurrent_deliveries: int = 10):
        self.registry = registry
        self.max_concurrent_deliveries = max_concurrent_deliveries
        self.delivery_queue: asyncio.Queue = asyncio.Queue()
        self.delivery_semaphore = asyncio.Semaphore(max_concurrent_deliveries)
        self._delivery_workers: List[asyncio.Task] = []
        self._running = False
    
    async def start(self):
        """Start webhook delivery workers"""
        if self._running:
            return
            
        self._running = True
        
        # Start delivery workers
        for i in range(self.max_concurrent_deliveries):
            worker = asyncio.create_task(self._delivery_worker(f"worker-{i}"))
            self._delivery_workers.append(worker)
        
        # Start retry processor
        retry_worker = asyncio.create_task(self._retry_processor())
        self._delivery_workers.append(retry_worker)
        
        logger.info(f"Started webhook dispatcher with {self.max_concurrent_deliveries} workers")
    
    async def stop(self):
        """Stop webhook delivery workers"""
        if not self._running:
            return
            
        self._running = False
        
        # Cancel all workers
        for worker in self._delivery_workers:
            worker.cancel()
        
        # Wait for workers to finish
        await asyncio.gather(*self._delivery_workers, return_exceptions=True)
        self._delivery_workers.clear()
        
        logger.info("Stopped webhook dispatcher")
    
    async def dispatch_event(self, event: WebhookEvent, data: Dict[str, Any], 
                           metadata: Optional[Dict[str, Any]] = None):
        """Dispatch webhook event to all subscribed endpoints"""
        endpoints = await self.registry.get_endpoints_for_event(event)
        
        if not endpoints:
            logger.debug(f"No webhook endpoints for event: {event.value}")
            return
        
        payload = WebhookPayload(
            event=event.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data,
            metadata=metadata
        )
        
        # Create delivery records for each endpoint
        for endpoint in endpoints:
            delivery = WebhookDelivery(
                id=str(uuid.uuid4()),
                endpoint_id=endpoint.id,
                event=event.value,
                payload=payload.to_dict(),
                status="pending",
                max_attempts=endpoint.max_retries
            )
            
            # Queue for delivery
            await self.delivery_queue.put(delivery)
        
        logger.info(f"Dispatched {event.value} to {len(endpoints)} endpoints")
    
    async def _delivery_worker(self, worker_name: str):
        """Worker to process webhook deliveries"""
        while self._running:
            try:
                # Get delivery from queue
                delivery = await asyncio.wait_for(
                    self.delivery_queue.get(), 
                    timeout=1.0
                )
                
                # Process delivery
                async with self.delivery_semaphore:
                    await self._process_delivery(delivery)
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.exception(f"Delivery worker {worker_name} error: {e}")
                await asyncio.sleep(5)
    
    async def _process_delivery(self, delivery: WebhookDelivery):
        """Process a single webhook delivery"""
        endpoint = await self.registry.get_endpoint(delivery.endpoint_id)
        if not endpoint or not endpoint.active:
            logger.warning(f"Endpoint {delivery.endpoint_id} not found or inactive")
            return
        
        delivery.attempts += 1
        
        try:
            # Prepare payload
            payload_json = json.dumps(delivery.payload)
            
            # Prepare headers
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'ElephantQ-Webhook/1.0',
                'X-Webhook-Event': delivery.event,
                'X-Webhook-Delivery': delivery.id,
                'X-Webhook-Timestamp': str(int(time.time()))
            }
            
            # Add custom headers
            if endpoint.headers:
                headers.update(endpoint.headers)
            
            # Add signature if secret is configured
            if endpoint.plaintext_secret:
                signature = WebhookSigner.sign_payload(payload_json, endpoint.plaintext_secret)
                headers['X-Webhook-Signature'] = signature
            
            # Send webhook
            timeout = aiohttp.ClientTimeout(total=endpoint.timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    endpoint.url,
                    data=payload_json,
                    headers=headers
                ) as response:
                    delivery.response_status = response.status
                    delivery.response_body = await response.text()
                    
                    if 200 <= response.status < 300:
                        # Success
                        delivery.status = "delivered"
                        delivery.delivered_at = datetime.now(timezone.utc)
                        logger.info(f"Webhook delivered: {delivery.id} -> {endpoint.url}")
                    else:
                        # HTTP error
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=response.status,
                            message=f"HTTP {response.status}"
                        )
        
        except Exception as e:
            # Delivery failed
            delivery.last_error = str(e)
            
            if delivery.attempts >= delivery.max_attempts:
                delivery.status = "failed"
                logger.error(f"Webhook delivery failed permanently: {delivery.id} -> {endpoint.url}: {e}")
            else:
                # Schedule retry with exponential backoff
                delay_seconds = min(300, 2 ** (delivery.attempts - 1) * 60)  # Max 5 minutes
                delivery.next_retry_at = datetime.now(timezone.utc).replace(microsecond=0) + \
                                       asyncio.timedelta(seconds=delay_seconds)
                delivery.status = "pending"
                logger.warning(f"Webhook delivery failed, will retry: {delivery.id} -> {endpoint.url}: {e}")
        
        # Save delivery record
        await self._save_delivery_record(delivery)
    
    async def _retry_processor(self):
        """Process webhook delivery retries"""
        while self._running:
            try:
                # Find deliveries ready for retry
                pool = await get_pool()
                async with pool.acquire() as conn:
                    deliveries = await conn.fetch("""
                        SELECT * FROM elephantq_webhook_deliveries
                        WHERE status = 'pending'
                        AND next_retry_at IS NOT NULL
                        AND next_retry_at <= NOW()
                        LIMIT 100
                    """)
                    
                    for row in deliveries:
                        delivery = WebhookDelivery(
                            id=row['id'],
                            endpoint_id=row['endpoint_id'],
                            event=row['event'],
                            payload=json.loads(row['payload']),
                            status=row['status'],
                            attempts=row['attempts'],
                            max_attempts=row['max_attempts'],
                            next_retry_at=row['next_retry_at'],
                            last_error=row['last_error'],
                            response_status=row['response_status'],
                            response_body=row['response_body'],
                            created_at=row['created_at'],
                            delivered_at=row['delivered_at']
                        )
                        
                        # Re-queue for delivery
                        await self.delivery_queue.put(delivery)
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.exception(f"Retry processor error: {e}")
                await asyncio.sleep(60)
    
    async def _save_delivery_record(self, delivery: WebhookDelivery):
        """Save delivery record to database"""
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO elephantq_webhook_deliveries (
                        id, endpoint_id, event, payload, status, attempts, max_attempts,
                        next_retry_at, last_error, response_status, response_body,
                        created_at, delivered_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        attempts = EXCLUDED.attempts,
                        next_retry_at = EXCLUDED.next_retry_at,
                        last_error = EXCLUDED.last_error,
                        response_status = EXCLUDED.response_status,
                        response_body = EXCLUDED.response_body,
                        delivered_at = EXCLUDED.delivered_at
                """,
                    delivery.id,
                    delivery.endpoint_id,
                    delivery.event,
                    json.dumps(delivery.payload),
                    delivery.status,
                    delivery.attempts,
                    delivery.max_attempts,
                    delivery.next_retry_at,
                    delivery.last_error,
                    delivery.response_status,
                    delivery.response_body,
                    delivery.created_at,
                    delivery.delivered_at
                )
        except Exception as e:
            logger.error(f"Failed to save delivery record: {e}")


class WebhookManager:
    """High-level webhook management interface"""
    
    def __init__(self):
        self.registry = WebhookRegistry()
        self.dispatcher = WebhookDispatcher(self.registry)
        self._started = False
    
    async def start(self):
        """Start webhook system"""
        if self._started:
            return
            
        await self.registry.load_endpoints_from_db()
        await self.dispatcher.start()
        self._started = True
        logger.info("Webhook system started")
    
    async def stop(self):
        """Stop webhook system"""
        if not self._started:
            return
            
        await self.dispatcher.stop()
        self._started = False
        logger.info("Webhook system stopped")
    
    async def register_webhook(self, url: str, events: Optional[List[str]] = None,
                              secret: Optional[str] = None, **kwargs) -> str:
        """Register a new webhook endpoint"""
        endpoint = WebhookEndpoint(
            id=str(uuid.uuid4()),
            url=url,
            secret=secret,
            events=events,
            **kwargs
        )
        return await self.registry.register_endpoint(endpoint)
    
    async def unregister_webhook(self, endpoint_id: str) -> bool:
        """Unregister a webhook endpoint"""
        return await self.registry.unregister_endpoint(endpoint_id)
    
    async def send_webhook(self, event: WebhookEvent, data: Dict[str, Any],
                          metadata: Optional[Dict[str, Any]] = None):
        """Send webhook event"""
        if not self._started:
            logger.warning("Webhook system not started, ignoring event")
            return
            
        await self.dispatcher.dispatch_event(event, data, metadata)
    
    async def get_delivery_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get webhook delivery statistics"""
        pool = await get_pool()
        async with pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_deliveries,
                    SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) as successful_deliveries,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_deliveries,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_deliveries,
                    AVG(attempts) as avg_attempts
                FROM elephantq_webhook_deliveries
                WHERE created_at >= NOW() - INTERVAL '%s hours'
            """, hours)
            
            # Get delivery trends
            trends = await conn.fetch("""
                SELECT 
                    DATE_TRUNC('hour', created_at) as hour,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) as successful
                FROM elephantq_webhook_deliveries
                WHERE created_at >= NOW() - INTERVAL '%s hours'
                GROUP BY hour
                ORDER BY hour
            """, hours)
            
            return {
                "summary": dict(stats),
                "hourly_trends": [dict(row) for row in trends]
            }


# Global webhook manager instance
_webhook_manager = WebhookManager()


# Public API
async def start_webhook_system():
    """Start the webhook system"""
    await _webhook_manager.start()


async def stop_webhook_system():
    """Stop the webhook system"""
    await _webhook_manager.stop()


async def register_webhook(url: str, events: Optional[List[str]] = None,
                          secret: Optional[str] = None, **kwargs) -> str:
    """Register a webhook endpoint"""
    return await _webhook_manager.register_webhook(url, events, secret, **kwargs)


async def unregister_webhook(endpoint_id: str) -> bool:
    """Unregister a webhook endpoint"""
    return await _webhook_manager.unregister_webhook(endpoint_id)


async def send_job_queued(job_id: str, job_name: str, queue: str, **kwargs):
    """Send job queued webhook"""
    await _webhook_manager.send_webhook(
        WebhookEvent.JOB_QUEUED,
        {"job_id": job_id, "job_name": job_name, "queue": queue, **kwargs}
    )


async def send_job_started(job_id: str, job_name: str, queue: str, attempt: int, **kwargs):
    """Send job started webhook"""
    await _webhook_manager.send_webhook(
        WebhookEvent.JOB_STARTED,
        {"job_id": job_id, "job_name": job_name, "queue": queue, "attempt": attempt, **kwargs}
    )


async def send_job_completed(job_id: str, job_name: str, queue: str, duration_ms: float, **kwargs):
    """Send job completed webhook"""
    await _webhook_manager.send_webhook(
        WebhookEvent.JOB_COMPLETED,
        {"job_id": job_id, "job_name": job_name, "queue": queue, "duration_ms": duration_ms, **kwargs}
    )


async def send_job_failed(job_id: str, job_name: str, queue: str, error: str, 
                         attempt: int, will_retry: bool, **kwargs):
    """Send job failed webhook"""
    await _webhook_manager.send_webhook(
        WebhookEvent.JOB_FAILED,
        {
            "job_id": job_id, "job_name": job_name, "queue": queue,
            "error": error, "attempt": attempt, "will_retry": will_retry, **kwargs
        }
    )


async def send_job_dead_letter(job_id: str, job_name: str, queue: str, final_error: str, **kwargs):
    """Send job moved to dead letter webhook"""
    await _webhook_manager.send_webhook(
        WebhookEvent.JOB_DEAD_LETTER,
        {"job_id": job_id, "job_name": job_name, "queue": queue, "final_error": final_error, **kwargs}
    )


async def get_webhook_endpoints() -> List[WebhookEndpoint]:
    """Get all registered webhook endpoints"""
    return await _webhook_manager.registry.list_endpoints()


async def get_delivery_stats(hours: int = 24) -> Dict[str, Any]:
    """Get webhook delivery statistics"""
    return await _webhook_manager.get_delivery_stats(hours)


def verify_webhook_signature(payload: str, signature: str, secret: str) -> bool:
    """Verify webhook signature"""
    return WebhookSigner.verify_signature(payload, signature, secret)


# Backward compatibility alias
WebhookConfig = WebhookEndpoint
