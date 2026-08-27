"""
Diagnosis module for DunnFlow.

Takes a payment's raw_error_code (as returned by Razorpay's test-mode API /
mock bank page) and classifies it into one of a small set of actionable
failure_category values. This is deliberately rule-based, not ML — every
classification must be explainable in one line, which is exactly what the
buildathon's "explainable and bounded" bar asks for.

Mapping source: Razorpay's documented test-mode decline reasons
(https://razorpay.com/docs/payments/payments/test-card-details/,
https://razorpay.com/docs/errors/payments/cards/).
"""

from backend.data.db import get_failed_payments, upsert_payment, log_audit_entry

# raw_error_code -> failure_category
# Keep this table as the single source of truth for the mapping — if you add
# a new raw error code anywhere (seed data or real API), it must be added here
# too, or it will fall through to "unclassified" and get flagged, not silently
# mis-handled.
CATEGORY_MAP = {
    "insufficient_fund": "insufficient_funds",
    "payment_timed_out": "bank_timeout",
    "authentication_failed": "auth_failed",
    "card_expired": "card_expired",
}

# One-line human explanation per category, reused in audit log + UI so the
# reasoning is visible everywhere, not just buried in code.
CATEGORY_EXPLANATION = {
    "insufficient_funds": "Customer's account did not have enough balance at the time of the charge.",
    "bank_timeout": "Bank/gateway failed to respond in time — likely a transient, bank-side issue.",
    "auth_failed": "Customer failed OTP/authentication step during the charge.",
    "card_expired": "The card on file has expired and needs to be updated.",
    "unclassified": "Raw error code not recognized by the current mapping — needs manual review.",
}


def classify(raw_error_code: str) -> str:
    """Pure function: raw_error_code -> failure_category. Falls back to
    'unclassified' rather than guessing, so nothing gets a silent wrong label."""
    return CATEGORY_MAP.get(raw_error_code, "unclassified")


def diagnose_payment(payment: dict) -> dict:
    """Classify a single payment record, persist the category, and write an
    audit entry explaining the decision. Returns the updated payment dict."""
    category = classify(payment["raw_error_code"])

    payment["failure_category"] = category
    upsert_payment(payment)

    log_audit_entry({
        "payment_id": payment["payment_id"],
        "customer_id": payment["customer_id"],
        "stage": "diagnose",
        "failure_category": category,
        "action_taken": "classified",
        "guardrail_hit": None,
        "result": "n/a" if category != "unclassified" else "flagged",
        "detail": (
            f"raw_error_code='{payment['raw_error_code']}' classified as "
            f"'{category}'. {CATEGORY_EXPLANATION[category]}"
        ),
    })

    return payment


def diagnose_all_undiagnosed() -> list[dict]:
    """Run diagnosis over every payment that hasn't been categorized yet.
    This is what the orchestrator calls after detection."""
    payments = get_failed_payments(status="failed")
    diagnosed = []
    for p in payments:
        if not p.get("failure_category"):
            diagnosed.append(diagnose_payment(p))
    return diagnosed


if __name__ == "__main__":
    # Quick manual test: diagnose whatever's currently in the DB
    results = diagnose_all_undiagnosed()
    for r in results:
        print(f"{r['payment_id']}: {r['raw_error_code']} -> {r['failure_category']}")
    print(f"\nDiagnosed {len(results)} payments.")