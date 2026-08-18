"""PayGuard Web Dashboard — Flask backend.

Reuses the existing PayGuardAgent, engine, tools, and db modules.
All memory still lives in CockroachDB; this is just a nicer frontend.
"""
import json
import sys
import os
import traceback
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Ensure the project root is on the path so `payguard` can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from payguard.agent import PayGuardAgent
from payguard.db import get_conn
from payguard import engine

app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)

# Single agent instance (same as the CLI — one session per server process)
agent = PayGuardAgent()
_conn = None


def _get_conn():
    """Lazy, reusable connection (reconnects if dropped)."""
    global _conn
    if _conn is None or _conn.closed:
        _conn = get_conn()
    return _conn


# ── Startup recovery ────────────────────────────────────────────────
with app.app_context():
    try:
        conn = _get_conn()
        engine.recover(conn)
        print(f"[dashboard] PayGuard ready — session {agent.session_id}")
    except Exception as e:
        print(f"[dashboard] startup recovery warning: {e}")


# ── Static ──────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ── Chat API ────────────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "empty message"}), 400

    tool_calls = []

    def on_tool(name, args):
        tool_calls.append({"name": name, "args": args})

    try:
        conn = _get_conn()
        reply = agent.chat(conn, user_message, on_tool=on_tool)
        return jsonify({
            "reply": reply,
            "tool_calls": tool_calls,
            "session_id": agent.session_id,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e), "tool_calls": tool_calls}), 500


# ── Payments (live status) ──────────────────────────────────────────
@app.route("/api/payments")
def payments():
    try:
        conn = _get_conn()
        conn.rollback()  # fresh snapshot
        rows = conn.execute(
            """SELECT p.id, p.status, p.amount, p.idempotency_key,
                      p.block_reason, p.step_history,
                      p.created_at, p.updated_at,
                      s.name AS supplier
               FROM payments p
               LEFT JOIN invoices i ON i.id = p.invoice_id
               LEFT JOIN suppliers s ON s.id = i.supplier_id
               ORDER BY p.updated_at DESC LIMIT 50"""
        ).fetchall()
        return jsonify([_serialize(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Invoices ────────────────────────────────────────────────────────
@app.route("/api/invoices")
def invoices():
    try:
        conn = _get_conn()
        conn.rollback()
        rows = conn.execute(
            """SELECT i.id, i.amount, i.currency, i.status, i.due_date,
                      i.s3_key, i.created_at,
                      s.name AS supplier
               FROM invoices i
               JOIN suppliers s ON s.id = i.supplier_id
               ORDER BY i.created_at DESC LIMIT 100"""
        ).fetchall()
        return jsonify([_serialize(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Suppliers ───────────────────────────────────────────────────────
@app.route("/api/suppliers")
def suppliers():
    try:
        conn = _get_conn()
        conn.rollback()
        rows = conn.execute(
            """SELECT s.id, s.name, s.payment_account, s.created_at,
                      COUNT(i.id) AS invoice_count,
                      COALESCE(SUM(i.amount), 0) AS total_amount
               FROM suppliers s
               LEFT JOIN invoices i ON i.supplier_id = s.id
               GROUP BY s.id, s.name, s.payment_account, s.created_at
               ORDER BY s.name"""
        ).fetchall()
        return jsonify([_serialize(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Stats ───────────────────────────────────────────────────────────
@app.route("/api/stats")
def stats():
    try:
        conn = _get_conn()
        conn.rollback()
        row = conn.execute(
            """SELECT
                 COUNT(*) AS total_payments,
                 COUNT(*) FILTER (WHERE status = 'CONFIRMED') AS confirmed,
                 COUNT(*) FILTER (WHERE status = 'BLOCKED') AS blocked,
                 COUNT(*) FILTER (WHERE status NOT IN ('CONFIRMED','FAILED','BLOCKED')) AS in_progress,
                 COALESCE(SUM(amount) FILTER (WHERE status = 'CONFIRMED'), 0) AS total_confirmed_amount
               FROM payments"""
        ).fetchone()
        inv = conn.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()
        sup = conn.execute("SELECT COUNT(*) AS n FROM suppliers").fetchone()
        return jsonify({
            "total_payments": row["total_payments"],
            "confirmed": row["confirmed"],
            "blocked": row["blocked"],
            "in_progress": row["in_progress"],
            "total_confirmed_amount": str(row["total_confirmed_amount"]),
            "total_invoices": inv["n"],
            "total_suppliers": sup["n"],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _serialize(row):
    """Convert a psycopg dict row to JSON-safe dict."""
    out = {}
    for k, v in dict(row).items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, (list, dict)):
            out[k] = v
        else:
            out[k] = str(v) if v is not None else None
    return out


def run_dashboard(host="0.0.0.0", port=5000, debug=False):
    """Entry point called by `python -m payguard dashboard`."""
    print(f"[dashboard] Starting PayGuard Dashboard on http://localhost:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_dashboard(debug=True)
