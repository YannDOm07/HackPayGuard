"""The heart of PayGuard: an idempotent, crash-proof payment state machine.

Rules:
  1. WRITE-AHEAD  — every transition is committed to CockroachDB BEFORE the
     corresponding action is taken.
  2. IDEMPOTENCY  — each payment carries a deterministic idempotency key
     (unique constraint) and the PSP deduplicates on it.
  3. NO RAM STATE — on startup the engine always asks the database
     "where was I?" (recover()) before doing anything else.

State machine:
  INTENT -> VALIDATED -> EXECUTING -> EXECUTED -> CONFIRMED
  (any state) -> FAILED | BLOCKED
"""
import json
import os
import sys
from datetime import datetime, timezone

import psycopg

from . import config, psp
from .db import audit, get_conn

TERMINAL = ("CONFIRMED", "FAILED", "BLOCKED")

# Crash injection points, in execution order:
CRASH_POINTS = [
    "AFTER_INTENT",           # intent written, nothing else done
    "AFTER_VALIDATED",        # checks passed, not yet executing
    "AFTER_EXECUTING_WRITE",  # we said "I'm about to send money" ... then died
    "AFTER_PSP_CALL",         # MONEY SENT but our DB does not know yet (worst case)
    "AFTER_EXECUTED",         # psp confirmed, final confirmation not written
]


class TransitionError(Exception):
    pass


def maybe_crash(point: str) -> None:
    """Simulate the process dying at an exact point (kill -9 semantics)."""
    if config.CRASH_AT == point or os.environ.get("CRASH_AT") == point:
        print(f"[CRASH] simulated crash at {point}", flush=True)
        os._exit(137)


def _transition(conn: psycopg.Connection, payment_id, from_status: str, to_status: str, note: str = "") -> None:
    """Compare-and-swap transition: only succeeds if the payment is exactly in
    `from_status`. Safe even if two engine instances run by accident."""
    entry = json.dumps([{
        "from": from_status,
        "to": to_status,
        "at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }])
    cur = conn.execute(
        """
        UPDATE payments
        SET status = %s,
            step_history = step_history || %s::jsonb,
            updated_at = now()
        WHERE id = %s AND status = %s
        RETURNING id
        """,
        (to_status, entry, payment_id, from_status),
    )
    if cur.fetchone() is None:
        conn.rollback()
        raise TransitionError(f"payment {payment_id}: illegal transition {from_status} -> {to_status}")
    conn.commit()  # WRITE-AHEAD: state is durable before we act on it


def create_payment(conn: psycopg.Connection, invoice_id: str) -> dict:
    """Create (or fetch) the payment INTENT for an invoice.

    The idempotency key is DERIVED from the invoice id, so even creating the
    intent is idempotent: a second call returns the same payment row.
    """
    idem = f"inv-{invoice_id}"
    inv = conn.execute(
        "SELECT id, amount, status FROM invoices WHERE id = %s", (invoice_id,)
    ).fetchone()
    if inv is None:
        raise ValueError(f"invoice {invoice_id} not found")

    conn.execute(
        """
        INSERT INTO payments (idempotency_key, invoice_id, amount, status, step_history)
        VALUES (%s, %s, %s, 'INTENT', %s::jsonb)
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (idem, invoice_id, inv["amount"],
         json.dumps([{"from": None, "to": "INTENT",
                      "at": datetime.now(timezone.utc).isoformat(),
                      "note": "intent written BEFORE any action"}])),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM payments WHERE idempotency_key = %s", (idem,)
    ).fetchone()


def _validate(conn: psycopg.Connection, payment: dict) -> None:
    """INTENT -> VALIDATED (or BLOCKED if the anti-fraud memory objects)."""
    from . import fraud  # local import: keeps the engine usable without Bedrock

    verdict = fraud.check_invoice(conn, str(payment["invoice_id"]))
    if verdict["blocked"]:
        entry = json.dumps([{
            "from": "INTENT", "to": "BLOCKED",
            "at": datetime.now(timezone.utc).isoformat(),
            "note": verdict["reason"],
        }])
        conn.execute(
            """UPDATE payments SET status='BLOCKED', block_reason=%s,
               step_history = step_history || %s::jsonb, updated_at=now()
               WHERE id=%s AND status='INTENT'""",
            (verdict["reason"], entry, payment["id"]),
        )
        conn.execute("UPDATE invoices SET status='BLOCKED' WHERE id=%s", (payment["invoice_id"],))
        audit(conn, "engine", "payment_blocked", {"payment_id": payment["id"], "reason": verdict["reason"]})
        conn.commit()
        return
    _transition(conn, payment["id"], "INTENT", "VALIDATED", "anti-fraud + budget checks passed")
    maybe_crash("AFTER_VALIDATED")


def _execute(conn: psycopg.Connection, payment: dict) -> None:
    """VALIDATED -> EXECUTING -> (psp call) -> EXECUTED."""
    inv = conn.execute(
        """SELECT i.payment_account AS inv_account, s.payment_account AS sup_account
           FROM invoices i JOIN suppliers s ON s.id = i.supplier_id
           WHERE i.id = %s""",
        (payment["invoice_id"],),
    ).fetchone()
    account = (inv["inv_account"] or inv["sup_account"]) if inv else "unknown"

    # WRITE-AHEAD: record "I am about to send money" BEFORE calling the PSP.
    _transition(conn, payment["id"], "VALIDATED", "EXECUTING", "about to call PSP")
    maybe_crash("AFTER_EXECUTING_WRITE")

    result = psp.execute_payment(conn, payment["idempotency_key"], payment["amount"], account)
    maybe_crash("AFTER_PSP_CALL")  # <- money moved, our DB doesn't know yet

    note = "PSP settled" + (" (deduplicated: already processed)" if result["already_processed"] else "")
    _transition(conn, payment["id"], "EXECUTING", "EXECUTED", note)
    maybe_crash("AFTER_EXECUTED")


def _confirm(conn: psycopg.Connection, payment: dict) -> None:
    """EXECUTED -> CONFIRMED after reconciliation with the PSP ledger."""
    ledger = psp.check_payment(conn, payment["idempotency_key"])
    if ledger is None:
        raise TransitionError(f"payment {payment['id']} EXECUTED but absent from PSP ledger!")
    _transition(conn, payment["id"], "EXECUTED", "CONFIRMED", "reconciled with PSP ledger")
    conn.execute("UPDATE invoices SET status='PAID' WHERE id=%s", (payment["invoice_id"],))
    audit(conn, "engine", "payment_confirmed", {
        "payment_id": payment["id"],
        "idempotency_key": payment["idempotency_key"],
        "amount": payment["amount"],
    })
    conn.commit()


def process_payment(conn: psycopg.Connection, invoice_id: str) -> dict:
    """Full pipeline for one invoice. Resumable from ANY state."""
    payment = create_payment(conn, invoice_id)
    maybe_crash("AFTER_INTENT")
    return resume(conn, payment)


def resume(conn: psycopg.Connection, payment: dict) -> dict:
    """Drive a payment forward from whatever state it is in."""
    while True:
        payment = conn.execute(
            "SELECT * FROM payments WHERE id = %s", (payment["id"],)
        ).fetchone()
        status = payment["status"]
        if status in TERMINAL:
            return payment
        if status == "INTENT":
            _validate(conn, payment)
        elif status == "VALIDATED":
            _execute(conn, payment)
        elif status == "EXECUTING":
            # Crashed mid-execution: ask the PSP before ANY retry.
            ledger = psp.check_payment(conn, payment["idempotency_key"])
            if ledger is not None:
                _transition(conn, payment["id"], "EXECUTING", "EXECUTED",
                            "recovery: PSP confirms payment already settled — NOT retrying")
            else:
                # Money never left. Safe to (re)call the PSP: it dedups anyway.
                inv = conn.execute(
                    """SELECT i.payment_account AS inv_account, s.payment_account AS sup_account
                       FROM invoices i JOIN suppliers s ON s.id = i.supplier_id WHERE i.id=%s""",
                    (payment["invoice_id"],),
                ).fetchone()
                account = (inv["inv_account"] or inv["sup_account"]) if inv else "unknown"
                result = psp.execute_payment(conn, payment["idempotency_key"], payment["amount"], account)
                note = "recovery: PSP had no trace, executed" + (
                    " (deduplicated)" if result["already_processed"] else "")
                _transition(conn, payment["id"], "EXECUTING", "EXECUTED", note)
        elif status == "EXECUTED":
            _confirm(conn, payment)
        else:
            raise TransitionError(f"unknown status {status}")


def recover(conn: psycopg.Connection) -> list[dict]:
    """Startup routine: find every unfinished payment and finish it.
    This is the agent's FIRST action every time it boots. No RAM state."""
    orphans = conn.execute(
        "SELECT * FROM payments WHERE status NOT IN ('CONFIRMED','FAILED','BLOCKED') ORDER BY created_at"
    ).fetchall()
    results = []
    for p in orphans:
        print(f"[recover] payment {p['id']} found in state {p['status']} — resuming...", flush=True)
        done = resume(conn, p)
        print(f"[recover] payment {p['id']} -> {done['status']}", flush=True)
        audit(conn, "engine", "recovered_payment", {
            "payment_id": p["id"], "from_status": p["status"], "to_status": done["status"],
        })
        conn.commit()
        results.append(done)
    if not orphans:
        print("[recover] no orphan payments. Memory is clean.", flush=True)
    return results


if __name__ == "__main__":
    # allows: python -m payguard.engine pay <invoice_id> (used by crash tests)
    if len(sys.argv) >= 3 and sys.argv[1] == "pay":
        with get_conn() as c:
            p = process_payment(c, sys.argv[2])
            print(f"payment {p['id']} -> {p['status']}")
