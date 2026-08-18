"""Tools exposed to the Claude agent. Every answer the agent gives about money
comes from these tools — i.e. from CockroachDB — never from its context window."""
import json
import re

import psycopg

from . import engine, fraud

TOOL_DEFS = [
    {
        "name": "list_invoices",
        "description": "List invoices, optionally filtered by status (RECEIVED, PAID, BLOCKED). Returns supplier name, amount, currency, due date, status.",
        "input_schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "description": "Optional status filter"}},
        },
    },
    {
        "name": "pay_invoice",
        "description": "Create and execute the payment for an invoice through the idempotent state machine (INTENT -> VALIDATED -> EXECUTING -> EXECUTED -> CONFIRMED). Safe to call twice: the idempotency key guarantees the supplier can never be paid twice. May return BLOCKED if the anti-fraud memory detects an anomaly.",
        "input_schema": {
            "type": "object",
            "properties": {"invoice_id": {"type": "string", "description": "UUID of the invoice to pay"}},
            "required": ["invoice_id"],
        },
    },
    {
        "name": "get_payment_status",
        "description": "Get the full state of a payment: current status, idempotency key, and the complete timestamped step_history of every state transition.",
        "input_schema": {
            "type": "object",
            "properties": {"invoice_id": {"type": "string", "description": "UUID of the invoice"}},
            "required": ["invoice_id"],
        },
    },
    {
        "name": "list_payments",
        "description": "List all payments with status and amounts. Use this to answer 'which payments have you made?' — the answer comes from the database, the agent's real memory.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "recover_orphans",
        "description": "Startup routine: find every payment left in a non-terminal state (e.g. after a crash) and finish it safely — checking with the PSP before any retry so nothing is ever paid twice.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_invoice_fraud",
        "description": "Run the anti-fraud check on an invoice: compares its bank account to the supplier's paid history and retrieves the most similar historical invoices via vector search.",
        "input_schema": {
            "type": "object",
            "properties": {"invoice_id": {"type": "string"}},
            "required": ["invoice_id"],
        },
    },
    {
        "name": "get_invoice_document",
        "description": "Get a time-limited link to the original invoice PDF stored in Amazon S3. Use it when the user asks to see, check or audit the source document behind an invoice — especially after a payment was BLOCKED for fraud.",
        "input_schema": {
            "type": "object",
            "properties": {"invoice_id": {"type": "string", "description": "UUID of the invoice"}},
            "required": ["invoice_id"],
        },
    },
    {
        "name": "audit_query",
        "description": "Run a read-only SQL SELECT against the PayGuard database (tables: suppliers, invoices, payments, audit_log, psp_ledger, conversations). Use for natural-language audit questions like 'all payments above 100000 XOF in March'. Only SELECT is allowed.",
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SELECT statement"}},
            "required": ["sql"],
        },
    },
]


def run_tool(conn: psycopg.Connection, name: str, args: dict) -> str:
    try:
        result = _dispatch(conn, name, args)
        return json.dumps(result, default=str, ensure_ascii=False)
    except Exception as e:  # tool errors go back to the model, never crash the loop
        conn.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def _dispatch(conn, name, args):
    if name == "list_invoices":
        q = """SELECT i.id, s.name AS supplier, i.amount, i.currency, i.status, i.due_date
               FROM invoices i JOIN suppliers s ON s.id = i.supplier_id"""
        params = ()
        if args.get("status"):
            q += " WHERE i.status = %s"
            params = (args["status"],)
        q += " ORDER BY i.created_at DESC LIMIT 100"
        return conn.execute(q, params).fetchall()

    if name == "pay_invoice":
        p = engine.process_payment(conn, args["invoice_id"])
        return {"payment_id": p["id"], "status": p["status"],
                "idempotency_key": p["idempotency_key"],
                "block_reason": p.get("block_reason"),
                "step_history": p["step_history"]}

    if name == "get_payment_status":
        row = conn.execute(
            "SELECT * FROM payments WHERE invoice_id = %s ORDER BY created_at DESC LIMIT 1",
            (args["invoice_id"],),
        ).fetchone()
        return row or {"info": "no payment exists for this invoice"}

    if name == "list_payments":
        return conn.execute(
            """SELECT p.id, p.status, p.amount, p.idempotency_key, p.created_at, s.name AS supplier
               FROM payments p
               LEFT JOIN invoices i ON i.id = p.invoice_id
               LEFT JOIN suppliers s ON s.id = i.supplier_id
               ORDER BY p.created_at DESC LIMIT 100"""
        ).fetchall()

    if name == "recover_orphans":
        results = engine.recover(conn)
        return {"recovered": len(results),
                "details": [{"payment_id": r["id"], "final_status": r["status"]} for r in results]}

    if name == "check_invoice_fraud":
        return fraud.check_invoice(conn, args["invoice_id"])

    if name == "get_invoice_document":
        from . import s3
        row = conn.execute(
            "SELECT s3_key FROM invoices WHERE id = %s", (args["invoice_id"],)
        ).fetchone()
        if row is None:
            return {"error": "invoice not found"}
        if not row["s3_key"]:
            return {"info": "no document stored in S3 for this invoice"}
        if not s3.enabled():
            return {"s3_key": row["s3_key"], "info": "S3 is not configured in this environment"}
        return {"s3_key": row["s3_key"], "url": s3.presigned_url(row["s3_key"]),
                "expires_in_seconds": 3600}

    if name == "audit_query":
        sql = args["sql"].strip().rstrip(";")
        if not re.match(r"(?is)^\s*SELECT\b", sql) or ";" in sql:
            raise ValueError("only a single SELECT statement is allowed")
        return conn.execute(sql).fetchall()[:200]

    raise ValueError(f"unknown tool {name}")
