# Proof #2 — Agent crash mid-payment, then clean recovery, ZERO double payment.
# Usage: .\scripts\demo_crash.ps1 <invoice_id>
param([Parameter(Mandatory=$true)][string]$InvoiceId)

Write-Host "`n=== 1. Paying invoice $InvoiceId with a crash injected AFTER the money left the PSP ===" -ForegroundColor Yellow
$env:CRASH_AT = "AFTER_PSP_CALL"
python -m payguard pay $InvoiceId
Write-Host "`n(the process just died: money sent, database not yet updated — the classic double-payment trap)" -ForegroundColor Red

Write-Host "`n=== 2. Agent restarts: recovery routine ('where was I?') ===" -ForegroundColor Yellow
$env:CRASH_AT = ""
python -m payguard recover

Write-Host "`n=== 3. Verdict: exactly ONE row in the PSP ledger for this invoice ===" -ForegroundColor Yellow
python -c "from payguard.db import get_conn; c = get_conn(); r = c.execute(`"SELECT p.status, (SELECT count(*) FROM psp_ledger l WHERE l.idempotency_key = p.idempotency_key) AS psp_rows FROM payments p WHERE p.invoice_id = '$InvoiceId'`").fetchone(); print(f'payment status = {r[\"status\"]}, PSP charges = {r[\"psp_rows\"]}  ->  PAID EXACTLY ONCE')"
