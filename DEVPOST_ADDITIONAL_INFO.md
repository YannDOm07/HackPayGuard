# 📋 Devpost — "Additional info" answers (ready to paste)

## URL to your functional demo application
```
https://github.com/YannDOm07/HackPayGuard
```
(CLI application — installable and runnable from the repository; setup in README Quickstart, works as depicted in the video.)

## Testing credentials / instructions for your functional demo app
```
PayGuard is a Python CLI application (Python 3.12+).

Setup (5 minutes):
1. git clone https://github.com/YannDOm07/HackPayGuard && cd HackPayGuard
2. pip install -r requirements.txt
3. Copy .env.example to .env and set DATABASE_URL to any CockroachDB Cloud
   connection string (free Basic cluster works). Set EMBEDDINGS_PROVIDER=fake
   to run fully offline — no AWS account needed for the core proofs.
4. python -m payguard init-db     (applies schema: tables + vector index)
5. python -m payguard seed        (15 suppliers, ~60 invoices incl. 1 fraud —
                                   prints the invoice IDs to use below)

The proofs:
- pytest tests/ -v               -> kills the process at EVERY step of the
  payment state machine and asserts the supplier is charged exactly once.
- python -m payguard status      -> live view of the agent's memory (run in a
  second terminal).
- python -m payguard pay <clean_invoice_id>   -> full payment pipeline.
- $env:CRASH_AT="AFTER_PSP_CALL"; python -m payguard pay <id>  -> crash right
  after the money left; then: $env:CRASH_AT=""; python -m payguard recover
  -> finishes the payment WITHOUT double-charging.
- python -m payguard pay <fraud_invoice_id>  -> BLOCKED, citing the supplier's
  14 historical invoices on the previous account.
- python -m payguard chat        -> Bedrock Claude agent (requires AWS
  credentials in .env and Bedrock model access; every factual answer comes
  from the database via tools).

We can provide connection details to our live demo cluster on request.
```

## URL to your open source and public code repository
```
https://github.com/YannDOm07/HackPayGuard
```

## URL to your open-source license file
```
https://github.com/YannDOm07/HackPayGuard/blob/main/LICENSE
```

## Which CockroachDB tools are used? (select all that apply)
- ✅ **MCP Server** (managed MCP endpoint — config in `.mcp.json`, natural-language audit of the agent's memory)
- ✅ **Vector indexing / vector search** (`VECTOR(1024)` + `CREATE VECTOR INDEX` — anti-fraud RAG)
- ✅ **ccloud CLI** — only if it's in the list AND you actually used it; otherwise leave unchecked.

## Which AWS Services are used? (select all that apply)
- ✅ Amazon Bedrock
- ✅ AWS Lambda
- ✅ Amazon S3

## Please explain how your project meaningfully integrated the selected CockroachDB and AWS components
```
CockroachDB is not a datastore bolted onto our agent — it IS the agent's memory,
and the product only works because of it. Four memory types live in one cluster:
(1) transactional memory — suppliers, invoices and payments in ACID tables;
(2) task-state memory — every payment's position in our idempotent state machine
(INTENT -> VALIDATED -> EXECUTING -> EXECUTED -> CONFIRMED), with each transition
committed via compare-and-swap BEFORE the corresponding action is taken
(write-ahead), plus a timestamped JSONB step history; (3) semantic memory — every
historical invoice is embedded and stored in a VECTOR(1024) column under a
distributed VECTOR INDEX, so fraud detection is a single SQL query (ORDER BY
embedding <=> $1) over the same consistent database as the money — no separate
vector store to drift out of sync; (4) conversational memory — every chat turn is
persisted. Our automated test suite kills the agent process at every single step
of the state machine and proves, against a live CockroachDB Cloud cluster, that
the supplier is charged exactly once every time. The managed MCP server adds an
independent audit channel: judges can interrogate the agent's memory in natural
language directly against the cluster, proving the memory is real, inspectable
state rather than LLM hallucination.

On AWS: Amazon Bedrock powers both halves of the intelligence — Claude drives
the agent's reasoning and tool-use loop through the official Anthropic Bedrock
SDK (7 tools; every factual answer is fetched from CockroachDB, never invented),
and Titan Embeddings v2 produces the 1024-dimension invoice embeddings that feed
the vector index. AWS Lambda executes payment steps, scheduled recovery sweeps
and due-date reminders serverlessly against the same cluster. Amazon S3 stores
the source invoice documents; the agent serves them through presigned URLs via a
dedicated tool, so a human reviewer can pull up the original PDF behind any
BLOCKED payment.
```

## What date did you start this project? (MM-DD-YY)
```
08-17-26
```

## Please explain any pre-existing code or work incorporated into the Project
```
All code was written during the Submission Period. We used standard development
tools and open-source libraries (Python, psycopg, boto3, the official Anthropic
SDK, pytest, rich, matplotlib for the architecture diagram) and AI coding
assistants (Claude Code) as permitted by the rules. The only pre-existing
material was our own project concept/planning document (pitch and roadmap);
no pre-existing code was incorporated.
```

## Optional: architectural diagram upload
Upload the file **`docs/architecture.png`** from the repo (PNG, well under 35 MB).
