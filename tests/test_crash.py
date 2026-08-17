"""Crash-proof tests — the core proof of PayGuard.

For EACH step of the state machine we:
  1. create a fresh invoice,
  2. run the payment in a subprocess with CRASH_AT=<step> (process dies mid-flight),
  3. run the recovery routine,
  4. assert: payment ends CONFIRMED and the PSP ledger holds EXACTLY ONE row
     for its idempotency key -> the supplier was paid exactly once. Always.

Requires DATABASE_URL pointing at a CockroachDB cluster (schema applied).
Run:  pytest tests/ -v
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from payguard import engine  # noqa: E402
from payguard.db import get_conn  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set"
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _make_invoice(conn) -> str:
    sup = conn.execute(
        "INSERT INTO suppliers (name, payment_account) VALUES ('CrashTest Corp', 'CI-TEST-0000') RETURNING id"
    ).fetchone()
    inv = conn.execute(
        """INSERT INTO invoices (supplier_id, amount, currency, payment_account, status)
           VALUES (%s, 99000, 'XOF', 'CI-TEST-0000', 'RECEIVED') RETURNING id""",
        (sup["id"],),
    ).fetchone()
    conn.commit()
    return str(inv["id"])


def _run_pay_subprocess(invoice_id: str, crash_at: str) -> int:
    env = {**os.environ, "CRASH_AT": crash_at, "EMBEDDINGS_PROVIDER": "fake", "PSP_LATENCY_MS": "0"}
    proc = subprocess.run(
        [sys.executable, "-m", "payguard", "pay", invoice_id],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
    )
    return proc.returncode


@pytest.mark.parametrize("crash_at", engine.CRASH_POINTS)
def test_crash_then_recover_pays_exactly_once(crash_at):
    with get_conn() as conn:
        invoice_id = _make_invoice(conn)

        rc = _run_pay_subprocess(invoice_id, crash_at)
        assert rc != 0, f"process should have crashed at {crash_at}"

        # rebirth: the recovery routine finishes the job
        os.environ.pop("CRASH_AT", None)
        engine.recover(conn)

        payment = conn.execute(
            "SELECT * FROM payments WHERE invoice_id = %s", (invoice_id,)
        ).fetchone()
        assert payment is not None, "intent must have been written before the crash (except pre-intent crashes)"
        assert payment["status"] == "CONFIRMED", f"expected CONFIRMED after recovery, got {payment['status']}"

        ledger = conn.execute(
            "SELECT count(*) AS n FROM psp_ledger WHERE idempotency_key = %s",
            (payment["idempotency_key"],),
        ).fetchone()
        assert ledger["n"] == 1, f"supplier must be paid EXACTLY once, ledger has {ledger['n']} rows"


def test_double_processing_is_idempotent():
    """Even calling the whole pipeline twice must charge once."""
    with get_conn() as conn:
        invoice_id = _make_invoice(conn)
        os.environ["EMBEDDINGS_PROVIDER"] = "fake"
        os.environ["PSP_LATENCY_MS"] = "0"

        p1 = engine.process_payment(conn, invoice_id)
        p2 = engine.process_payment(conn, invoice_id)

        assert p1["id"] == p2["id"], "same invoice -> same payment row (idempotency key)"
        assert p2["status"] == "CONFIRMED"
        n = conn.execute(
            "SELECT count(*) AS n FROM psp_ledger WHERE idempotency_key = %s",
            (p1["idempotency_key"],),
        ).fetchone()["n"]
        assert n == 1
