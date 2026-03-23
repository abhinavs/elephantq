-- Optional feature tables: dead letter queue, webhooks, and structured logging.
-- These are created by migrations so `elephantq setup` handles everything.
-- The feature modules also use CREATE TABLE IF NOT EXISTS as a safety net.

-- Dead letter queue (permanently failed jobs)
CREATE TABLE IF NOT EXISTS elephantq_dead_letter_jobs (
  id UUID PRIMARY KEY,
  job_name TEXT NOT NULL,
  args JSONB NOT NULL,
  queue TEXT NOT NULL,
  priority INTEGER NOT NULL,
  max_attempts INTEGER NOT NULL,
  attempts INTEGER NOT NULL,
  last_error TEXT,
  dead_letter_reason TEXT NOT NULL,
  original_created_at TIMESTAMP WITH TIME ZONE NOT NULL,
  moved_to_dead_letter_at TIMESTAMP WITH TIME ZONE NOT NULL,
  resurrection_count INTEGER DEFAULT 0,
  last_resurrection_at TIMESTAMP WITH TIME ZONE,
  tags JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_elephantq_dead_letter_jobs_job_name
  ON elephantq_dead_letter_jobs (job_name);
CREATE INDEX IF NOT EXISTS idx_elephantq_dead_letter_jobs_queue
  ON elephantq_dead_letter_jobs (queue);
CREATE INDEX IF NOT EXISTS idx_elephantq_dead_letter_jobs_reason
  ON elephantq_dead_letter_jobs (dead_letter_reason);
CREATE INDEX IF NOT EXISTS idx_elephantq_dead_letter_jobs_moved_at
  ON elephantq_dead_letter_jobs (moved_to_dead_letter_at);

-- Webhook endpoints and delivery tracking
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
  endpoint_id TEXT NOT NULL REFERENCES elephantq_webhook_endpoints(id) ON DELETE CASCADE,
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
  delivered_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status
  ON elephantq_webhook_deliveries (status);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_next_retry
  ON elephantq_webhook_deliveries (next_retry_at);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_endpoint
  ON elephantq_webhook_deliveries (endpoint_id);

-- Structured logging
CREATE TABLE IF NOT EXISTS elephantq_logs (
  id SERIAL PRIMARY KEY,
  timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
  level TEXT NOT NULL,
  message TEXT NOT NULL,
  logger_name TEXT NOT NULL,
  module TEXT,
  function TEXT,
  line_number INTEGER,
  request_id TEXT,
  job_id TEXT,
  job_name TEXT,
  queue TEXT,
  extra_data JSONB,
  exception_data JSONB,
  performance_data JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_elephantq_logs_timestamp
  ON elephantq_logs (timestamp);
CREATE INDEX IF NOT EXISTS idx_elephantq_logs_job_id
  ON elephantq_logs (job_id);
CREATE INDEX IF NOT EXISTS idx_elephantq_logs_level
  ON elephantq_logs (level);
CREATE INDEX IF NOT EXISTS idx_elephantq_logs_request_id
  ON elephantq_logs (request_id);
