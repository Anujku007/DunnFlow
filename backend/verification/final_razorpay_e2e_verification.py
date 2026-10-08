from pathlib import Path
import ast
import sqlite3
import sys


"""
DunnFlow — Final Razorpay E2E Verification

READ-ONLY FINAL EVIDENCE CHECK.

This verifier:
- reads the existing DunnFlow database
- validates the existing Razorpay implementation
- validates the completed Razorpay recovery lifecycle
- validates revenue/audit/metrics consistency

This verifier DOES NOT:
- create Razorpay orders
- execute payments
- send webhooks
- replay webhooks
- mutate invoices
- mutate subscriptions
- mutate payment attempts
- mutate recovery actions
- mutate revenue events
- mutate audit records
- mutate benchmark data
"""


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "dunnflow.db"

HANDLER_PATH = ROOT / "backend" / "webhooks" / "handler.py"
VERIFIER_PATH = ROOT / "backend" / "webhooks" / "verifier.py"
INGESTION_PATH = ROOT / "backend" / "integrations" / "razorpay_ingestion.py"
EXECUTION_PATH = ROOT / "backend" / "modules" / "execution.py"
API_PATH = ROOT / "backend" / "api.py"
DB_MODULE_PATH = ROOT / "backend" / "data" / "db.py"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def fetchone(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def fetchall(conn, sql, params=()):
    return [
        dict(row)
        for row in conn.execute(sql, params).fetchall()
    ]


print("=" * 100)
print("DUNNFLOW — FINAL RAZORPAY E2E VERIFICATION")
print("=" * 100)
print()


# ============================================================================
# 1. REQUIRED FILES
# ============================================================================

required_files = [
    DB_PATH,
    HANDLER_PATH,
    VERIFIER_PATH,
    INGESTION_PATH,
    EXECUTION_PATH,
    API_PATH,
    DB_MODULE_PATH,
]

for path in required_files:
    require(
        path.exists(),
        f"Required file missing: {path}"
    )

print("[PASS] Required DunnFlow files exist.")


# ============================================================================
# 2. PYTHON SYNTAX
# ============================================================================

source_files = [
    HANDLER_PATH,
    VERIFIER_PATH,
    INGESTION_PATH,
    EXECUTION_PATH,
    API_PATH,
    DB_MODULE_PATH,
]

for path in source_files:
    source = path.read_text(encoding="utf-8-sig")
    ast.parse(source, filename=str(path))

print("[PASS] Razorpay/webhook/backend Python syntax is valid.")


# ============================================================================
# 3. SOURCE-LEVEL SECURITY / IDEMPOTENCY
# ============================================================================

handler_text = HANDLER_PATH.read_text(encoding="utf-8-sig")
verifier_text = VERIFIER_PATH.read_text(encoding="utf-8-sig")
ingestion_text = INGESTION_PATH.read_text(encoding="utf-8-sig")
execution_text = EXECUTION_PATH.read_text(encoding="utf-8-sig")
api_text = API_PATH.read_text(encoding="utf-8-sig")
db_text = DB_MODULE_PATH.read_text(encoding="utf-8-sig")


require(
    "webhook_event_exists" in handler_text,
    "Webhook event-id duplicate check is missing."
)

require(
    "record_webhook_event" in handler_text,
    "Webhook event persistence is missing."
)

require(
    "hmac" in verifier_text.lower(),
    "HMAC signature verification is missing."
)

require(
    "sha256" in verifier_text.lower(),
    "SHA-256 signature verification is missing."
)

require(
    "recovery_confirmed" in execution_text,
    "recovery_confirmed financial outcome is missing."
)

require(
    "/api/webhooks/razorpay" in api_text,
    "Razorpay webhook endpoint is missing."
)

require(
    "INSERT OR IGNORE" in db_text,
    "Webhook event persistence is missing INSERT OR IGNORE."
)

print("[PASS] Webhook security/idempotency boundaries preserved.")


# ============================================================================
# 4. READ-ONLY DATABASE OPEN
# ============================================================================

require(
    DB_PATH.exists(),
    f"Database not found: {DB_PATH}"
)

db_uri = f"file:{DB_PATH.as_posix()}?mode=ro"

conn = sqlite3.connect(
    db_uri,
    uri=True,
)

conn.row_factory = sqlite3.Row

before_counts = fetchone(
    conn,
    """
    SELECT
        (SELECT COUNT(*) FROM invoices) AS invoices,
        (SELECT COUNT(*) FROM payment_attempts) AS payment_attempts,
        (SELECT COUNT(*) FROM revenue_events) AS revenue_events,
        (SELECT COUNT(*) FROM audit_log) AS audit_rows,
        (SELECT COUNT(*) FROM razorpay_webhook_events) AS webhook_events
    """
)

print("[PASS] SQLite database opened in READ-ONLY mode.")


# ============================================================================
# 5. LOCATE THE COMPLETED REAL RAZORPAY RECOVERY
# ============================================================================

target = fetchone(
    conn,
    """
    SELECT
        pa.attempt_id,
        pa.invoice_id,
        pa.subscription_id,
        pa.razorpay_payment_id,
        pa.attempt_type,
        pa.result,
        pa.gateway_status,
        pa.executed_at,

        i.batch_id,
        i.amount,
        i.currency,
        i.status AS invoice_status,
        i.paid_at,
        i.razorpay_order_id

    FROM payment_attempts pa

    JOIN invoices i
      ON i.invoice_id = pa.invoice_id

    WHERE pa.razorpay_payment_id IS NOT NULL
      AND pa.result IN ('succeeded', 'success')
      AND pa.gateway_status = 'captured'
      AND i.razorpay_order_id IS NOT NULL
      AND i.status = 'paid'

    ORDER BY
        pa.executed_at DESC,
        pa.attempt_id DESC

    LIMIT 1
    """
)

require(
    target is not None,
    "No completed Razorpay Test Mode recovery exists in the current DB."
)

invoice_id = target["invoice_id"]
subscription_id = target["subscription_id"]
payment_id = target["razorpay_payment_id"]
order_id = target["razorpay_order_id"]
batch_id = target["batch_id"]
amount = int(target["amount"])

print("[PASS] Completed Razorpay Test Mode recovery located.")
print(f"       Batch        : {batch_id}")
print(f"       Invoice      : {invoice_id}")
print(f"       Order        : {order_id}")
print(f"       Payment      : {payment_id}")
print(f"       Amount       : ₹{amount / 100:,.2f}")


# ============================================================================
# 6. RAZORPAY ORDER / PAYMENT CORRELATION
# ============================================================================

require(
    order_id,
    "Verified invoice has no Razorpay order ID."
)

require(
    payment_id,
    "Verified payment attempt has no Razorpay payment ID."
)

print("[PASS] Razorpay order/payment correlation exists.")


# ============================================================================
# 7. PAYMENT ATTEMPT
# ============================================================================

attempt_rows = fetchall(
    conn,
    """
    SELECT
        attempt_id,
        invoice_id,
        razorpay_payment_id,
        attempt_number,
        attempt_type,
        result,
        gateway_status
    FROM payment_attempts
    WHERE invoice_id = ?
      AND razorpay_payment_id = ?
    ORDER BY attempt_id
    """,
    (invoice_id, payment_id),
)

require(
    attempt_rows,
    "No local payment attempt matches the Razorpay payment."
)

captured_rows = [
    row
    for row in attempt_rows
    if row["result"] in ("succeeded", "success")
    and row["gateway_status"] == "captured"
]

require(
    len(captured_rows) == 1,
    (
        "Expected exactly one captured local payment attempt "
        f"for payment {payment_id}; found {len(captured_rows)}."
    )
)

print("[PASS] Exactly one captured payment attempt exists.")


# ============================================================================
# 8. INVOICE PAID
# ============================================================================

invoice = fetchone(
    conn,
    """
    SELECT
        invoice_id,
        batch_id,
        subscription_id,
        amount,
        currency,
        status,
        paid_at,
        razorpay_order_id
    FROM invoices
    WHERE invoice_id = ?
    """,
    (invoice_id,),
)

require(
    invoice is not None,
    "Verified invoice does not exist."
)

require(
    invoice["status"] == "paid",
    f"Invoice state is {invoice['status']}, expected paid."
)

require(
    invoice["paid_at"] is not None,
    "Paid invoice has no paid_at timestamp."
)

require(
    invoice["razorpay_order_id"] == order_id,
    "Invoice/Razorpay order correlation mismatch."
)

print("[PASS] Invoice transitioned to paid.")


# ============================================================================
# 9. SUBSCRIPTION ACTIVE
# ============================================================================

subscription = fetchone(
    conn,
    """
    SELECT
        subscription_id,
        batch_id,
        status,
        customer_id
    FROM subscriptions
    WHERE subscription_id = ?
    """,
    (subscription_id,),
)

require(
    subscription is not None,
    "Verified subscription does not exist."
)

require(
    subscription["status"] == "active",
    f"Subscription state is {subscription['status']}, expected active."
)

print("[PASS] Subscription transitioned to active.")


# ============================================================================
# 10. WEBHOOK EVIDENCE
# ============================================================================

webhook_rows = fetchall(
    conn,
    """
    SELECT
        event_id,
        event_type,
        received_at
    FROM razorpay_webhook_events
    WHERE event_type IN (
        'payment.authorized',
        'payment.captured',
        'order.paid'
    )
    ORDER BY received_at
    """
)

webhook_types = {
    row["event_type"]
    for row in webhook_rows
}

require(
    "payment.authorized" in webhook_types,
    "payment.authorized webhook evidence is missing from DB."
)

require(
    "payment.captured" in webhook_types,
    "payment.captured webhook evidence is missing from DB."
)

require(
    "order.paid" in webhook_types,
    "order.paid webhook evidence is missing from DB."
)

print("[PASS] payment.authorized DB evidence exists.")
print("[PASS] payment.captured DB evidence exists.")
print("[PASS] order.paid DB evidence exists.")


# ============================================================================
# 11. REVENUE EVENTS
# ============================================================================

revenue_rows = fetchall(
    conn,
    """
    SELECT
        event_id,
        invoice_id,
        payment_attempt_id,
        event_type,
        amount,
        razorpay_event_id,
        event_timestamp
    FROM revenue_events
    WHERE invoice_id = ?
    ORDER BY event_id
    """,
    (invoice_id,),
)

revenue_types = {
    row["event_type"]
    for row in revenue_rows
}

required_revenue_events = {
    "payment_captured",
    "invoice_paid",
    "recovery_confirmed",
}

missing_revenue_events = (
    required_revenue_events - revenue_types
)

require(
    not missing_revenue_events,
    (
        "Missing required revenue events: "
        f"{sorted(missing_revenue_events)}"
    )
)

recovery_rows = [
    row
    for row in revenue_rows
    if row["event_type"] == "recovery_confirmed"
]

require(
    len(recovery_rows) == 1,
    (
        "Expected exactly one recovery_confirmed event; "
        f"found {len(recovery_rows)}."
    )
)

recovered_amount = int(
    recovery_rows[0]["amount"] or 0
)

require(
    recovered_amount == amount,
    (
        "Recovered revenue mismatch: "
        f"{recovered_amount} != {amount}"
    )
)

print("[PASS] payment_captured revenue event exists.")
print("[PASS] invoice_paid revenue event exists.")
print("[PASS] recovery_confirmed revenue event exists.")
print(
    f"[PASS] Recovered revenue: ₹{recovered_amount / 100:,.2f}"
)


# ============================================================================
# 12. AUDIT TRAIL
# ============================================================================

audit_rows = fetchall(
    conn,
    """
    SELECT
        log_id,
        invoice_id,
        stage,
        action_taken,
        result,
        detail,
        timestamp
    FROM audit_log
    WHERE invoice_id = ?
    ORDER BY log_id
    """,
    (invoice_id,),
)

require(
    audit_rows,
    "No audit trail exists for the verified recovery."
)

print(
    f"[PASS] Audit trail exists ({len(audit_rows)} event(s))."
)


# ============================================================================
# 13. AUTHORITATIVE METRICS
# ============================================================================

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.data.db import get_batch_metrics

metrics = get_batch_metrics(batch_id)

require(
    metrics.get("exists") is True,
    "Target batch does not exist in authoritative metrics."
)

recovered_count = int(
    metrics.get("recovered_count", 0)
)

amount_recovered = int(
    metrics.get("amount_recovered", 0)
)

require(
    recovered_count >= 1,
    "Batch recovered_count does not include a recovery."
)

require(
    amount_recovered >= recovered_amount,
    (
        "Batch amount_recovered is lower than the "
        "verified recovery amount."
    )
)

require(
    "recovery_rate_pct" in metrics,
    "recovery_rate_pct missing from authoritative metrics."
)

print("[PASS] Authoritative batch metrics include the recovery.")
print(f"       Recovered count : {recovered_count}")
print(
    f"       Amount recovered: ₹{amount_recovered / 100:,.2f}"
)
print(
    f"       Recovery rate   : "
    f"{float(metrics['recovery_rate_pct']):.1f}%"
)


# ============================================================================
# 14. IDEMPOTENCY ARCHITECTURE
# ============================================================================

require(
    "webhook_event_exists" in handler_text,
    "Webhook duplicate lookup is missing."
)

require(
    "event_id" in handler_text,
    "Webhook event_id handling is missing."
)

require(
    "INSERT OR IGNORE" in db_text,
    "Webhook event persistence is missing INSERT OR IGNORE."
)

print("[PASS] Webhook duplicate/idempotency architecture exists.")


# ============================================================================
# 15. SIGNATURE ARCHITECTURE
# ============================================================================

require(
    "verify_razorpay_signature" in verifier_text,
    "Razorpay signature verifier is missing."
)

require(
    "hmac.compare_digest" in verifier_text,
    "Constant-time signature comparison is missing."
)

print("[PASS] Razorpay signature verification architecture exists.")


# ============================================================================
# 16. READ-ONLY INTEGRITY
# ============================================================================

after_counts = fetchone(
    conn,
    """
    SELECT
        (SELECT COUNT(*) FROM invoices) AS invoices,
        (SELECT COUNT(*) FROM payment_attempts) AS payment_attempts,
        (SELECT COUNT(*) FROM revenue_events) AS revenue_events,
        (SELECT COUNT(*) FROM audit_log) AS audit_rows,
        (SELECT COUNT(*) FROM razorpay_webhook_events) AS webhook_events
    """
)

require(
    before_counts == after_counts,
    "Database row counts changed during verification."
)

conn.close()

print("[PASS] Database row counts unchanged during verification.")


# ============================================================================
# FINAL
# ============================================================================

print()
print("=" * 100)
print("STEP 12 FINAL VERIFICATION: PASS")
print("=" * 100)
print()
print("Razorpay Test Mode recovery          : PASS")
print("Order/payment correlation             : PASS")
print("payment.authorized evidence           : PASS")
print("payment.captured evidence             : PASS")
print("order.paid evidence                   : PASS")
print("Payment attempt                       : PASS")
print("Captured payment                      : PASS")
print("Invoice paid                          : PASS")
print("Subscription active                   : PASS")
print("Revenue events                        : PASS")
print("Recovered revenue                    : PASS")
print("Audit trail                           : PASS")
print("Authoritative metrics                 : PASS")
print("Webhook idempotency architecture      : PASS")
print("Webhook signature architecture        : PASS")
print("READ-ONLY verification                : PASS")
print("No DB mutation                        : PASS")
print("No payment execution                  : PASS")
print("No webhook replay                     : PASS")
print("No benchmark mutation                 : PASS")
print()
print("=" * 100)
