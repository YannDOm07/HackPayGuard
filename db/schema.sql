-- PayGuard schema — CockroachDB
-- The 4 memory types:
--   transactional  -> suppliers / invoices / payments (ACID)
--   task state     -> payments.status + payments.step_history (write-ahead state machine)
--   semantic       -> invoices.embedding (VECTOR 1024, Titan Embeddings v2)
--   conversational -> conversations

CREATE TABLE IF NOT EXISTS suppliers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name STRING NOT NULL,
  payment_account STRING NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invoices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id UUID REFERENCES suppliers(id),
  amount DECIMAL NOT NULL,
  currency STRING DEFAULT 'XOF',
  payment_account STRING,               -- account printed on THIS invoice (fraud signal if != supplier's)
  s3_key STRING,                        -- PDF in S3 (optional)
  embedding VECTOR(1024),               -- semantic memory (Titan v2 = 1024 dims)
  status STRING NOT NULL DEFAULT 'RECEIVED',  -- RECEIVED | PAID | BLOCKED
  due_date DATE,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key STRING UNIQUE NOT NULL,     -- anti-duplicate guarantee
  invoice_id UUID REFERENCES invoices(id),
  amount DECIMAL NOT NULL,
  status STRING NOT NULL DEFAULT 'INTENT',    -- INTENT -> VALIDATED -> EXECUTING -> EXECUTED -> CONFIRMED | FAILED | BLOCKED
  step_history JSONB NOT NULL DEFAULT '[]',   -- timestamped transitions (audit)
  block_reason STRING,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor STRING NOT NULL,                      -- 'agent' | 'engine' | user id
  action STRING NOT NULL,
  payload JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id STRING NOT NULL,
  role STRING NOT NULL,                       -- 'user' | 'assistant'
  content STRING NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- The PSP ledger simulates the EXTERNAL payment provider's own database.
-- A real PSP deduplicates on the idempotency key: so do we.
CREATE TABLE IF NOT EXISTS psp_ledger (
  idempotency_key STRING PRIMARY KEY,
  amount DECIMAL NOT NULL,
  destination_account STRING,
  status STRING NOT NULL DEFAULT 'SETTLED',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Distributed vector index for the anti-fraud RAG (CockroachDB C-SPANN index).
-- If your cluster version does not support it yet, queries still work (seq scan).
CREATE VECTOR INDEX IF NOT EXISTS invoices_embedding_idx ON invoices (embedding);
