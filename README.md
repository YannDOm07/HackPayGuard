# PayGuard — the financial agent that never pays twice

**CockroachDB × AWS Hackathon** — an autonomous CFO agent for small businesses that verifies invoices, detects fraud, and executes supplier payments with one absolute guarantee: **no payment lost, no payment duplicated — ever.** Its entire memory lives in CockroachDB and survives agent crashes, restarts, and even database node failures.

> *"Memory is not a feature. It's what separates a toy from a production agent."*

## The problem

2026 is the year of agentic payments. But an AI agent that moves money has one deadly failure mode:

1. The agent sends the wire transfer ✅
2. The agent crashes **before** recording that the money left 💥
3. On restart it finds no trace of the payment
4. It pays again → **the supplier is paid twice**

LLMs are amnesiac by nature. Their memory must be externalized — and that external memory must be **always available and transactionally reliable**.

## The solution

PayGuard keeps **zero state in RAM**. Every payment goes through a persisted state machine with a strict **write-ahead** discipline: each transition is committed to CockroachDB *before* the corresponding action is taken.

```
INTENT ──► VALIDATED ──► EXECUTING ──► EXECUTED ──► CONFIRMED
             │              │ crash here? on restart the agent asks
             ▼              ▼ the PSP "did you get it?" BEFORE any retry
          BLOCKED        (idempotency key = unique constraint = no duplicates)
```

- **Idempotency key** derived from the invoice → a `UNIQUE` constraint makes double payment structurally impossible.
- **Compare-and-swap transitions** (`UPDATE ... WHERE status = expected`) → safe even with two agent instances running.
- **Startup = recovery**: the agent's first action is always `SELECT ... WHERE status NOT IN ('CONFIRMED','FAILED','BLOCKED')`, then it finishes each orphan safely.
- **Anti-fraud RAG**: every historical invoice is embedded (Titan v2, 1024 dims) into CockroachDB's distributed vector index. A supplier that changes bank accounts after 14 consistent invoices gets **BLOCKED** with the evidence cited.

## The 4 memory types demonstrated

| Type | Content | CockroachDB storage |
|---|---|---|
| Transactional | payments, invoices, suppliers | ACID SQL tables |
| Task state | current step of each payment + timestamped transitions | `payments.status` + `step_history` (JSONB) |
| Semantic | invoice embeddings (anti-fraud) | `VECTOR(1024)` + distributed vector index |
| Conversational | chat history and decisions | `conversations` table |

## Architecture

```
        USER (terminal chat + live SQL view)
                    │
          ┌─────────▼──────────┐
          │  PayGuard agent    │   Amazon Bedrock (Claude, official
          │  tool-use loop     │   Anthropic Bedrock SDK client)
          └───┬──────────┬─────┘
              │          │
     ┌────────▼───┐  ┌───▼─────────────────┐
     │ AWS Lambda │  │ CockroachDB MCP     │
     │ (payment   │  │ server (NL queries  │
     │ steps +    │  │ straight to cluster)│
     │ reminders) │  └───┬─────────────────┘
     └──────┬─────┘      │
     ┌──────▼────────────▼───────────────────┐
     │   COCKROACHDB CLUSTER (multi-node)    │
     │  SQL ACID · VECTOR index · task state │
     └──────┬────────────────────────────────┘
     ┌──────▼──────┐
     │  Amazon S3  │  (invoice PDFs)
     └─────────────┘
```

### CockroachDB tools used (≥2 required)

1. **Distributed vector indexing** — `VECTOR(1024)` column + `CREATE VECTOR INDEX` on `invoices.embedding`, powering the anti-fraud RAG with no separate vector database.
2. **Managed MCP server** — the CockroachDB Cloud MCP endpoint (`https://cockroachlabs.cloud/mcp`) lets any MCP client (Claude Desktop / Claude Code) query the agent's memory in natural language. Enable it in the CockroachDB Cloud console, then add to your MCP client config:
   ```json
   { "mcpServers": { "cockroachdb": { "url": "https://cockroachlabs.cloud/mcp" } } }
   ```
   Ask it: *"show all payments above 100000 XOF and their step history"* — the answer comes straight from the cluster, proving the agent's memory is real, inspectable state, not hallucination.
3. *(bonus)* **ccloud CLI** — used during development to monitor cluster health and connection info.

### AWS services used (≥1 required)

1. **Amazon Bedrock** — Claude (reasoning + tool-use agent loop, via the official `anthropic[bedrock]` SDK) and **Titan Embeddings v2** (1024-dim invoice embeddings).
2. **AWS Lambda** — serverless execution of payment steps, recovery sweeps and due-date reminders (`lambda/handler.py`).
3. **Amazon S3** — invoice PDF storage. Every invoice gets a generated PDF at `s3://<bucket>/invoices/<invoice_id>.pdf`, referenced by `invoices.s3_key`. The agent's `get_invoice_document` tool returns a presigned link, so when a payment is **BLOCKED** the user can open the exact document that was rejected. CockroachDB holds the state; S3 holds the source document behind it.

## Quickstart

```bash
git clone <this repo> && cd HackPayGuard
pip install -r requirements.txt
cp .env.example .env        # paste your CockroachDB Cloud connection string
                            # + AWS credentials via `aws configure`

python -m payguard init-db   # apply schema (tables + vector index)
python -m payguard s3-check  # verify bucket access before seeding (optional)
python -m payguard seed      # 15 suppliers, ~60 invoices incl. 1 fraud, PDFs -> S3
python -m payguard chat      # talk to the agent
```

No Bedrock access yet? Set `EMBEDDINGS_PROVIDER=fake` in `.env` — the engine, crash tests and fraud detection all work offline; only the chat needs Bedrock. Leaving `S3_BUCKET` empty disables S3 the same way; `python -m payguard s3-sync` backfills the PDFs later, whenever you're ready.

## The five proofs of persistence

| # | Proof | How to run it |
|---|---|---|
| 1 | **Amnesia test** | Quit the chat, restart `python -m payguard chat` (fresh LLM context) and ask *"what payments have you made?"* → exact answer, fetched from CockroachDB |
| 2 | **Agent crash** | `.\scripts\demo_crash.ps1 <invoice_id>` — kills the process right after the money left the PSP, restarts, proves **exactly one** charge |
| 3 | **CockroachDB chaos** | Kill a node of the cluster mid-write → the agent continues, zero loss (the hackathon's thesis) |
| 4 | **Split-screen SQL** | `python -m payguard status` in a second terminal — watch statuses change live while the agent works |
| 5 | **Supplier anomaly** | Ask the agent to pay the "Fournisseur BTP Yamoussoukro" invoice → **BLOCKED**, citing the 14 historical invoices on the old account |

All crash scenarios are also automated: `pytest tests/ -v` kills the process at **every** step of the state machine and asserts the supplier is paid exactly once.

## Feedback on CockroachDB AI tools

- The **vector type + vector index** made the anti-fraud RAG a one-liner (`ORDER BY embedding <=> $1`) — no second database to keep consistent with the transactional data, which is exactly what an agent's memory needs.
- The **managed MCP server** turns the cluster into an inspectable memory: judges (or auditors!) can interrogate the agent's state in natural language without trusting the agent's own words.

## License

MIT — see [LICENSE](LICENSE).
