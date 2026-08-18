# 📋 Devpost submission — ready to paste

## Project name
PayGuard — the financial agent that never pays twice

## Elevator pitch (tagline)
An autonomous CFO agent whose memory lives in CockroachDB: it verifies invoices, blocks fraud, and executes payments with a structural guarantee — no payment lost, no payment duplicated, even through crashes.

## Inspiration
2026 is the year of agentic payments — but an AI agent that moves money has one deadly failure mode: it sends the transfer, crashes before recording it, and pays again on restart. LLMs are amnesiac by nature; their memory must be external, always available, and transactionally reliable. That memory is the product.

## What it does
PayGuard is an autonomous CFO agent for small businesses. It ingests supplier invoices, checks each one against its long-term memory (a supplier that suddenly changes bank accounts after 14 identical invoices gets BLOCKED with the evidence cited), executes payments through a persisted state machine, and answers natural-language audit questions straight from the database. Kill the agent at ANY point of a payment — even right after the money left the payment provider — and on restart it reads its state from CockroachDB, reconciles with the provider, and finishes the job without ever double-paying.

## How we built it
- **Idempotent state machine** (Python): INTENT → VALIDATED → EXECUTING → EXECUTED → CONFIRMED, every transition committed to CockroachDB BEFORE the action (write-ahead), compare-and-swap updates, idempotency key under a UNIQUE constraint.
- **CockroachDB as the agent's entire memory**: ACID tables (transactional), status + JSONB step history (task state), VECTOR(1024) with a distributed vector index (semantic anti-fraud memory), conversations table (conversational memory).
- **Amazon Bedrock**: Claude drives the tool-use agent loop (7 tools, official Anthropic Bedrock SDK); Titan Embeddings v2 produces the 1024-dim invoice embeddings.
- **AWS Lambda** runs payment steps / recovery sweeps serverlessly; **Amazon S3** stores the source invoice documents (presigned URLs served by an agent tool).
- **Automated chaos**: pytest kills the process at every step of the state machine and asserts the PSP ledger holds exactly one charge.

## Challenges we ran into
Getting crash-recovery truly safe required treating the payment provider as the source of truth: after a crash in EXECUTING, the agent must ASK the PSP "did you get it?" before any retry. We also hit Bedrock's daily token quotas on a fresh AWS account mid-hackathon — our offline embeddings mode and engine-level demo path kept every proof reproducible.

## Accomplishments we're proud of
6/6 automated crash tests passing against a live CockroachDB Cloud cluster — including the worst case (money sent, database not yet updated). The fraud scenario working end-to-end with real evidence cited from vector + SQL memory.

## What we learned
Memory is not a feature — it's what separates a toy from a production agent. Keeping ALL state out of RAM makes crash recovery a query, not a prayer.

## What's next
Real PSP integrations (mobile money APIs), a web dashboard on the same live-memory view, and multi-region CockroachDB for cross-border resilience.

## Built with
`python` `cockroachdb` `cockroachdb-vector-index` `cockroachdb-mcp` `amazon-bedrock` `claude` `titan-embeddings` `aws-lambda` `amazon-s3` `psycopg` `pytest`

## Links
- Repo (public, MIT): https://github.com/YannDOm07/HackPayGuard
- Video: <YOUTUBE_URL_HERE>
- Try it: clone + `pip install -r requirements.txt` + `.env` (see README quickstart)

## CockroachDB tools used (≥2)
1. **Distributed vector indexing** — `VECTOR(1024)` + `CREATE VECTOR INDEX` powering the anti-fraud RAG, no separate vector DB.
2. **Managed MCP server** — the cluster is queryable in natural language from any MCP client (config in `.mcp.json`), proving the agent's memory is inspectable state, not hallucination.
3. *(bonus)* ccloud CLI during development.

## AWS services used (≥1)
Amazon Bedrock (Claude + Titan Embeddings v2), AWS Lambda, Amazon S3.
