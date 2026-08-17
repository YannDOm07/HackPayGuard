"""Simulated Payment Service Provider (PSP).

This module stands in for an external payment rail (bank / mobile money).
Its ledger lives in its own table (`psp_ledger`) to mimic the provider's
OWN database — the source of truth for "did the money actually move?".

Like every serious real-world PSP (Stripe, Wave, MTN MoMo...), it
deduplicates on an idempotency key: sending the same key twice charges once.
"""
import os
import time

import psycopg

from . import config


class PSPError(Exception):
    pass


def _maybe_latency() -> None:
    if config.PSP_LATENCY_MS > 0:
        time.sleep(config.PSP_LATENCY_MS / 1000)


def execute_payment(
    conn: psycopg.Connection, idempotency_key: str, amount, destination_account: str
) -> dict:
    """Send money. Returns {'status', 'already_processed'}.

    INSERT ... ON CONFLICT DO NOTHING on the PSP's primary key is the
    dedup guarantee: a retry with the same key is a no-op.
    """
    _maybe_latency()
    if os.environ.get("PSP_FAIL_NEXT") == "1":
        # one-shot injected outage (network drop, provider 500...)
        os.environ["PSP_FAIL_NEXT"] = "0"
        raise PSPError("PSP unavailable (injected failure)")

    cur = conn.execute(
        """
        INSERT INTO psp_ledger (idempotency_key, amount, destination_account, status)
        VALUES (%s, %s, %s, 'SETTLED')
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING idempotency_key
        """,
        (idempotency_key, amount, destination_account),
    )
    inserted = cur.fetchone() is not None
    conn.commit()
    return {"status": "SETTLED", "already_processed": not inserted}


def check_payment(conn: psycopg.Connection, idempotency_key: str) -> dict | None:
    """Reconciliation API: 'did you receive this payment?' — the question the
    agent asks after a crash, BEFORE any retry."""
    cur = conn.execute(
        "SELECT idempotency_key, amount, status, created_at FROM psp_ledger WHERE idempotency_key = %s",
        (idempotency_key,),
    )
    return cur.fetchone()
