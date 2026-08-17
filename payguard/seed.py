"""Realistic demo dataset: 15 suppliers, ~60 invoices.

- ~55 historical PAID invoices (they build the anti-fraud memory)
- 4 clean pending invoices (RECEIVED) ready to be paid in the demo
- 1 FRAUD invoice: 'Fournisseur BTP Yamoussoukro' suddenly asks for a NEW
  bank account after 14 identical invoices -> the agent must BLOCK it.
"""
import random

from . import fraud
from .db import get_conn

random.seed(42)  # deterministic dataset

SUPPLIERS = [
    ("Imprimerie Abidjan Services", "CI-BANK-0001-4471"),
    ("Fournisseur BTP Yamoussoukro", "CI-BANK-0002-8832"),   # <- fraud target
    ("SODECI (Eau)", "CI-BANK-0003-1290"),
    ("CIE (Electricité)", "CI-BANK-0004-5511"),
    ("Orange CI (Internet)", "MOMO-ORANGE-0102030405"),
    ("Transport Logistique Konan", "MOMO-MTN-0504030201"),
    ("Papeterie Moderne Plateau", "CI-BANK-0007-9021"),
    ("Sécurité Vigile Plus", "CI-BANK-0008-3344"),
    ("Nettoyage ProClean", "MOMO-WAVE-0708091011"),
    ("Cabinet Comptable Diaby", "CI-BANK-0010-7788"),
    ("Location Véhicules Bassam", "CI-BANK-0011-2299"),
    ("Traiteur Akwaba", "MOMO-ORANGE-0605040302"),
    ("Informatique Sankara Tech", "CI-BANK-0013-6543"),
    ("Assurance NSIA", "CI-BANK-0014-8710"),
    ("Maintenance Clim Froid+", "MOMO-MTN-0908070605"),
]

FRAUD_SUPPLIER = "Fournisseur BTP Yamoussoukro"
FRAUD_ACCOUNT = "CI-BANK-9999-0666"  # brand new account nobody has ever paid


def seed() -> None:
    with get_conn() as conn:
        existing = conn.execute("SELECT count(*) AS n FROM suppliers").fetchone()["n"]
        if existing:
            print(f"[seed] {existing} suppliers already present — skipping (truncate manually to reseed).")
            return

        sup_ids = {}
        for name, account in SUPPLIERS:
            row = conn.execute(
                "INSERT INTO suppliers (name, payment_account) VALUES (%s, %s) RETURNING id",
                (name, account),
            ).fetchone()
            sup_ids[name] = (row["id"], account)
        conn.commit()

        n_hist = 0
        for name, (sid, account) in sup_ids.items():
            # 14 historical invoices for the fraud target (the '14 identical invoices' story),
            # 2-4 for everyone else.
            count = 14 if name == FRAUD_SUPPLIER else random.randint(2, 4)
            base = random.choice([45000, 120000, 250000, 380000, 780000])
            for _ in range(count):
                amount = base + random.randint(-5000, 5000)
                emb = fraud.embed_text(fraud.invoice_text(name, amount, "XOF", account))
                conn.execute(
                    """INSERT INTO invoices (supplier_id, amount, currency, payment_account, embedding, status)
                       VALUES (%s, %s, 'XOF', %s, %s::vector, 'PAID')""",
                    (sid, amount, account, _vec(emb)),
                )
                n_hist += 1
        conn.commit()
        print(f"[seed] {n_hist} historical PAID invoices inserted (anti-fraud memory built).")

        # 4 clean pending invoices
        pending = []
        for name in ["Imprimerie Abidjan Services", "Orange CI (Internet)",
                     "Nettoyage ProClean", "Informatique Sankara Tech"]:
            sid, account = sup_ids[name]
            amount = random.choice([85000, 150000, 320000, 610000])
            emb = fraud.embed_text(fraud.invoice_text(name, amount, "XOF", account))
            row = conn.execute(
                """INSERT INTO invoices (supplier_id, amount, currency, payment_account, embedding, status, due_date)
                   VALUES (%s, %s, 'XOF', %s, %s::vector, 'RECEIVED', current_date + 7) RETURNING id""",
                (sid, amount, account, _vec(emb)),
            ).fetchone()
            pending.append((name, row["id"], amount))

        # THE fraud invoice: same supplier, NEW account
        sid, _ = sup_ids[FRAUD_SUPPLIER]
        emb = fraud.embed_text(fraud.invoice_text(FRAUD_SUPPLIER, 382000, "XOF", FRAUD_ACCOUNT))
        row = conn.execute(
            """INSERT INTO invoices (supplier_id, amount, currency, payment_account, embedding, status, due_date)
               VALUES (%s, 382000, 'XOF', %s, %s::vector, 'RECEIVED', current_date + 3) RETURNING id""",
            (sid, FRAUD_ACCOUNT, _vec(emb)),
        ).fetchone()
        conn.commit()

        print("\n[seed] pending invoices ready for the demo:")
        for name, iid, amount in pending:
            print(f"  CLEAN  {iid}  {name}  {amount} XOF")
        print(f"  FRAUD  {row['id']}  {FRAUD_SUPPLIER}  382000 XOF  (new account {FRAUD_ACCOUNT})")


def _vec(emb: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in emb) + "]"


if __name__ == "__main__":
    seed()
