"""AWS Lambda — serverless execution of payment steps & scheduled reminders.

Deploy with the `payguard` package + psycopg bundled (or a layer), and
DATABASE_URL in the function's environment variables.

Events:
  {"action": "recover"}                      -> finish every orphan payment (cron: rate(5 minutes))
  {"action": "pay", "invoice_id": "<uuid>"}  -> execute one payment
  {"action": "due_reminders"}                -> list invoices due within 7 days
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from payguard import engine  # noqa: E402
from payguard.db import get_conn  # noqa: E402


def lambda_handler(event, context):
    action = event.get("action", "recover")
    with get_conn() as conn:
        if action == "recover":
            results = engine.recover(conn)
            return _ok({"recovered": len(results)})
        if action == "pay":
            p = engine.process_payment(conn, event["invoice_id"])
            return _ok({"payment_id": str(p["id"]), "status": p["status"]})
        if action == "due_reminders":
            rows = conn.execute(
                """SELECT i.id, s.name, i.amount, i.due_date FROM invoices i
                   JOIN suppliers s ON s.id = i.supplier_id
                   WHERE i.status = 'RECEIVED' AND i.due_date <= current_date + 7
                   ORDER BY i.due_date"""
            ).fetchall()
            return _ok({"due_soon": [dict(r) for r in rows]})
    return _ok({"error": f"unknown action {action}"}, code=400)


def _ok(body, code=200):
    return {"statusCode": code, "body": json.dumps(body, default=str)}
