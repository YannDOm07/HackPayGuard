"""Connection helpers for CockroachDB (PostgreSQL wire protocol via psycopg 3)."""
import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from . import config

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def get_conn() -> psycopg.Connection:
    if not config.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and paste your "
            "CockroachDB Cloud connection string."
        )
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=False)


def init_db() -> None:
    """Apply the schema. Idempotent (CREATE ... IF NOT EXISTS)."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_conn() as conn:
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            try:
                conn.execute(stmt)
            except psycopg.Error as e:
                # Vector index may not be supported on older clusters — degrade gracefully.
                if "VECTOR INDEX" in stmt.upper():
                    conn.rollback()
                    print(f"[init-db] vector index skipped ({e.diag.message_primary or e})")
                else:
                    raise
        conn.commit()
    print("[init-db] schema applied.")


def audit(conn: psycopg.Connection, actor: str, action: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor, action, payload) VALUES (%s, %s, %s)",
        (actor, action, json.dumps(payload, default=str)),
    )
