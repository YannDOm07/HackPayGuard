"""Amazon S3 — invoice PDF storage.

Every invoice in the agent's memory has a matching PDF document in S3, keyed by
invoice id (`invoices.s3_key`). The database holds the *state*; S3 holds the
*source document* the state was derived from — which is exactly what an auditor
asks for when the agent blocks a payment: "show me the invoice you rejected".

Everything here degrades to a no-op when S3_BUCKET is unset, so the engine, the
crash tests and the fraud RAG all keep working offline.
"""
import psycopg

from . import config

_client = None


def enabled() -> bool:
    return bool(config.S3_BUCKET)


def client():
    global _client
    if _client is None:
        import boto3
        _client = boto3.client("s3", region_name=config.S3_REGION)
    return _client


# --- minimal PDF writer (no external dependency) ---------------------------

def _escape(text: str) -> bytes:
    """PDF string escaping, encoded for WinAnsi (handles é, è, ç in supplier names)."""
    out = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return out.encode("cp1252", "replace")


def build_invoice_pdf(lines: list[str]) -> bytes:
    """A single-page A4 PDF containing `lines`. Hand-built so the demo needs no
    reportlab/weasyprint install."""
    text_ops = [b"BT", b"/F1 12 Tf", b"50 780 Td", b"16 TL"]
    for line in lines:
        text_ops.append(b"(" + _escape(line) + b") Tj T*")
    text_ops.append(b"ET")
    stream = b"\n".join(text_ops)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"

    xref_at = len(pdf)
    pdf += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
    pdf += b"startxref\n" + str(xref_at).encode() + b"\n%%EOF\n"
    return bytes(pdf)


# --- storage ----------------------------------------------------------------

def invoice_key(invoice_id) -> str:
    return f"invoices/{invoice_id}.pdf"


def upload_invoice(invoice_id, supplier: str, amount, currency: str,
                   account: str, status: str) -> str:
    """Upload one invoice PDF. Returns the S3 key."""
    pdf = build_invoice_pdf([
        "PayGuard - FACTURE FOURNISSEUR",
        "",
        f"Facture      : {invoice_id}",
        f"Fournisseur  : {supplier}",
        f"Montant      : {amount} {currency}",
        f"Compte de reglement : {account}",
        f"Statut       : {status}",
        "",
        "Document de reference conserve dans Amazon S3.",
        "L'etat du paiement vit dans CockroachDB.",
    ])
    key = invoice_key(invoice_id)
    client().put_object(
        Bucket=config.S3_BUCKET, Key=key, Body=pdf,
        ContentType="application/pdf",
    )
    return key


def presigned_url(key: str, expires: int = 3600) -> str:
    """Time-limited link — what the agent hands the user to inspect a document."""
    return client().generate_presigned_url(
        "get_object",
        Params={"Bucket": config.S3_BUCKET, "Key": key},
        ExpiresIn=expires,
    )


def sync_invoices(conn: psycopg.Connection) -> int:
    """Upload a PDF for every invoice that doesn't have one yet. Idempotent —
    safe to re-run before the demo."""
    if not enabled():
        print("[s3] S3_BUCKET not set — skipping (the rest of PayGuard works without it).")
        return 0

    rows = conn.execute(
        """SELECT i.id, i.amount, i.currency, i.status,
                  COALESCE(i.payment_account, s.payment_account) AS account,
                  s.name AS supplier
           FROM invoices i JOIN suppliers s ON s.id = i.supplier_id
           WHERE i.s3_key IS NULL"""
    ).fetchall()

    for r in rows:
        key = upload_invoice(r["id"], r["supplier"], r["amount"],
                             r["currency"], r["account"], r["status"])
        conn.execute("UPDATE invoices SET s3_key = %s WHERE id = %s", (key, r["id"]))
    conn.commit()
    print(f"[s3] {len(rows)} invoice PDF(s) uploaded to s3://{config.S3_BUCKET}/invoices/")
    return len(rows)


def check() -> None:
    """Pre-demo smoke test: credentials, bucket, write AND read."""
    if not enabled():
        print("[s3] S3_BUCKET is empty in .env — S3 disabled.")
        return
    key = "invoices/_payguard_check.pdf"
    body = build_invoice_pdf(["PayGuard S3 connectivity check"])
    client().put_object(Bucket=config.S3_BUCKET, Key=key, Body=body,
                        ContentType="application/pdf")
    got = client().get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read()
    assert got == body, "S3 round-trip mismatch"
    client().delete_object(Bucket=config.S3_BUCKET, Key=key)
    print(f"[s3] OK — bucket '{config.S3_BUCKET}' ({config.S3_REGION}): put/get/delete all succeeded.")
