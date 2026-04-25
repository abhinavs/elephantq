-- Add the soniq_task_registry observability table.
--
-- Plan section 14.4 / 15.8: workers populate this table with the names
-- they handle so the dashboard can answer questions like 'which workers
-- across the fleet handle billing.invoices.send.v2?' and so a deploy-skew
-- detector can flag rows queued for names no worker has ever registered.
--
-- LOAD-BEARING INVARIANT: this table is OBSERVABILITY METADATA ONLY. The
-- enqueue path never reads it. Adding a fallback in Soniq.enqueue that
-- consults this table would turn it into distributed coordination, which
-- is explicitly out of scope (plan section 14.4 'Architectural boundary
-- statement'). Tests in tests/unit/test_enqueue.py and
-- tests/integration/test_cross_service_enqueue.py pin this invariant.
--
-- Composite primary key (task_name, worker_id) gives per-worker visibility
-- across the fleet without a future schema migration when phase 4's
-- routing UI wants to surface fleet topology.
--
-- Forward-only migration. Reverting requires dropping the table manually.

CREATE TABLE IF NOT EXISTS soniq_task_registry (
  task_name TEXT NOT NULL,
  worker_id TEXT NOT NULL,
  last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
  args_model_repr TEXT,
  PRIMARY KEY (task_name, worker_id)
);

CREATE INDEX IF NOT EXISTS idx_soniq_task_registry_task_name
  ON soniq_task_registry (task_name);
