"""Anti-fraud RAG on top of CockroachDB's distributed vector index.

Semantic memory: every historical invoice is embedded (Titan Embeddings v2,
1024 dims) and stored in invoices.embedding. A new invoice is compared to the
supplier's history — if the bank account suddenly changes after N consistent
invoices, the payment is BLOCKED pending human review.
"""
import hashlib
import json
import math

import psycopg

from . import config

_bedrock = None


def _bedrock_client():
    global _bedrock
    if _bedrock is None:
        import boto3
        _bedrock = boto3.client("bedrock-runtime", region_name=config.AWS_REGION)
    return _bedrock


def _fake_embedding(text: str) -> list[float]:
    """Deterministic pseudo-embedding (offline mode / tests). Same text ->
    same vector, similar prefixes -> loosely similar vectors."""
    vec = []
    for i in range(config.EMBED_DIMS):
        h = hashlib.sha256(f"{i}:{text}".encode()).digest()
        vec.append(int.from_bytes(h[:4], "big") / 2**32 - 0.5)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed_text(text: str) -> list[float]:
    if config.EMBEDDINGS_PROVIDER == "fake":
        return _fake_embedding(text)
    resp = _bedrock_client().invoke_model(
        modelId=config.EMBED_MODEL_ID,
        body=json.dumps({"inputText": text[:8000], "dimensions": config.EMBED_DIMS, "normalize": True}),
    )
    return json.loads(resp["body"].read())["embedding"]


def invoice_text(supplier_name: str, amount, currency: str, account: str) -> str:
    return f"invoice supplier={supplier_name} amount={amount} {currency} account={account}"


def similar_invoices(conn: psycopg.Connection, embedding: list[float], limit: int = 5) -> list[dict]:
    """Vector search: nearest historical invoices (cosine distance)."""
    vec = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"
    try:
        return conn.execute(
            """
            SELECT i.id, i.amount, i.currency, i.payment_account, i.status,
                   s.name AS supplier_name,
                   i.embedding <=> %s::vector AS distance
            FROM invoices i JOIN suppliers s ON s.id = i.supplier_id
            WHERE i.embedding IS NOT NULL
            ORDER BY i.embedding <=> %s::vector
            LIMIT %s
            """,
            (vec, vec, limit),
        ).fetchall()
    except psycopg.Error:
        conn.rollback()
        return []


def check_invoice(conn: psycopg.Connection, invoice_id: str) -> dict:
    """Verdict for a new invoice: OK, or BLOCKED with evidence from memory."""
    inv = conn.execute(
        """SELECT i.*, s.name AS supplier_name, s.payment_account AS supplier_account
           FROM invoices i JOIN suppliers s ON s.id = i.supplier_id WHERE i.id = %s""",
        (invoice_id,),
    ).fetchone()
    if inv is None:
        return {"blocked": True, "reason": f"invoice {invoice_id} not found", "evidence": []}

    # Rule 1 — hard check on the long-term transactional memory:
    # how many PAID invoices does this supplier have, and on which account?
    history = conn.execute(
        """SELECT payment_account, count(*) AS n
           FROM invoices
           WHERE supplier_id = %s AND status = 'PAID' AND payment_account IS NOT NULL
           GROUP BY payment_account ORDER BY n DESC""",
        (inv["supplier_id"],),
    ).fetchall()

    inv_account = inv["payment_account"] or inv["supplier_account"]
    if history:
        known_accounts = {h["payment_account"] for h in history}
        total_paid = sum(h["n"] for h in history)
        if inv_account not in known_accounts:
            return {
                "blocked": True,
                "reason": (
                    f"ACCOUNT CHANGE DETECTED: supplier '{inv['supplier_name']}' was paid "
                    f"{total_paid} time(s) on account(s) {sorted(known_accounts)} but this "
                    f"invoice asks for '{inv_account}'. Human validation required."
                ),
                "evidence": [dict(h) for h in history],
            }

    # Rule 2 — semantic memory: is this invoice wildly unlike anything seen?
    if inv["embedding"] is not None:
        sims = similar_invoices(conn, _parse_vec(inv["embedding"]), limit=5)
        evidence = [
            {"supplier": s["supplier_name"], "amount": str(s["amount"]), "distance": float(s["distance"])}
            for s in sims if str(s["id"]) != str(inv["id"])
        ]
        return {"blocked": False, "reason": "checks passed", "evidence": evidence}

    return {"blocked": False, "reason": "checks passed (no embedding available)", "evidence": []}


def _parse_vec(raw) -> list[float]:
    if isinstance(raw, list):
        return raw
    return [float(x) for x in str(raw).strip("[]").split(",")]
