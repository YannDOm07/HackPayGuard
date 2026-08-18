"""CLI entry point: python -m payguard <command>"""
import argparse
import sys

from .db import get_conn, init_db


def main() -> None:
    parser = argparse.ArgumentParser(prog="payguard", description="PayGuard — the agent that never pays twice")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="apply the CockroachDB schema")
    sub.add_parser("seed", help="load the demo dataset (15 suppliers, ~60 invoices)")
    sub.add_parser("chat", help="interactive chat with the Bedrock agent")
    sub.add_parser("recover", help="startup recovery: finish every orphan payment")
    sub.add_parser("status", help="live view of payments (the split-screen)")
    sub.add_parser("s3-check", help="verify S3 credentials and bucket access")
    sub.add_parser("s3-sync", help="upload a PDF to S3 for every invoice missing one")
    sub.add_parser("dashboard", help="launch the web dashboard (chat + live status)")

    pay = sub.add_parser("pay", help="pay an invoice through the state machine (no LLM)")
    pay.add_argument("invoice_id")

    args = parser.parse_args()

    if args.cmd == "init-db":
        init_db()
    elif args.cmd == "seed":
        from . import seed
        seed.seed()
    elif args.cmd == "chat":
        from .agent import run_chat_cli
        run_chat_cli()
    elif args.cmd == "recover":
        from . import engine
        with get_conn() as conn:
            engine.recover(conn)
    elif args.cmd == "pay":
        from . import engine
        with get_conn() as conn:
            p = engine.process_payment(conn, args.invoice_id)
            print(f"payment {p['id']} -> {p['status']}"
                  + (f"  [{p.get('block_reason')}]" if p.get("block_reason") else ""))
            sys.exit(0 if p["status"] == "CONFIRMED" else 2)
    elif args.cmd == "s3-check":
        from . import s3
        s3.check()
    elif args.cmd == "s3-sync":
        from . import s3
        with get_conn() as conn:
            s3.sync_invoices(conn)
    elif args.cmd == "dashboard":
        from dashboard.app import run_dashboard
        run_dashboard()
    elif args.cmd == "status":
        _status()


def _status() -> None:
    """Live 'memory view' — run it next to the agent for the split-screen demo."""
    import time
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table

    console = Console()

    def render(conn) -> Table:
        t = Table(title="PayGuard — live memory (CockroachDB)", expand=True)
        for col in ("supplier", "amount", "payment status", "idempotency key", "updated"):
            t.add_column(col)
        rows = conn.execute(
            """SELECT s.name, p.amount, p.status, p.idempotency_key, p.updated_at
               FROM payments p
               LEFT JOIN invoices i ON i.id = p.invoice_id
               LEFT JOIN suppliers s ON s.id = i.supplier_id
               ORDER BY p.updated_at DESC LIMIT 15"""
        ).fetchall()
        colors = {"CONFIRMED": "green", "BLOCKED": "red", "EXECUTING": "yellow",
                  "EXECUTED": "cyan", "VALIDATED": "blue", "INTENT": "magenta"}
        for r in rows:
            c = colors.get(r["status"], "white")
            t.add_row(str(r["name"]), str(r["amount"]), f"[{c}]{r['status']}[/{c}]",
                      r["idempotency_key"], str(r["updated_at"])[:19])
        return t

    with get_conn() as conn, Live(console=console, refresh_per_second=2) as live:
        while True:
            conn.rollback()  # fresh snapshot each tick
            live.update(render(conn))
            time.sleep(1)


if __name__ == "__main__":
    main()
