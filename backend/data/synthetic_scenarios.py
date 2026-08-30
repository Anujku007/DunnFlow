"""
DunnFlow Phase-E synthetic UI scenarios.

Creates fresh, isolated batches for end-to-end UI testing.

Scenarios:
    1. Card expired -> recovery candidate
    2. Card expired -> successful customer recovery
    3. Card expired -> recovery candidate with previous retry
    4. Unclassified failure -> manual review

This file only creates deterministic test data.
It does not execute recovery actions.
"""

from __future__ import annotations

from backend.data.db import (
    init_db,
    create_batch_run,
    upsert_subscription,
    upsert_invoice,
    create_payment_attempt,
    record_revenue_event,
)


# ---------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------

SCENARIOS = [
    {
        "batch_id": "e2e_phase_e_card_expired_001",
        "subscription_id": "sub_e2e_phase_e_card_expired_001",
        "invoice_id": "inv_e2e_phase_e_card_expired_001",
        "customer_id": "cust_e2e_phase_e_card_expired_001",
        "customer_name": "Phase E Card Expired Customer",
        "customer_email": "phasee_card_expired@example.com",
        "razorpay_invoice_id": "inv_test_phasee_card_expired_001",
        "amount": 29900,
        "failure_category": "card_expired",
        "raw_error_code": "card_expired",
        "failure_reason": "Customer card has expired.",
        "result_detail": "Phase E UI test: card expired recovery scenario.",
    },
    {
        "batch_id": "e2e_phase_e_card_expired_success_043",
        "subscription_id": "sub_e2e_phase_e_card_expired_success_043",
        "invoice_id": "inv_e2e_phase_e_card_expired_success_043",
        "customer_id": "cust_e2e_phase_e_card_expired_success_043",
        "customer_name": "Phase E Card Expired Success Customer",
        "customer_email": "phasee_card_expired_success@example.com",
        "razorpay_invoice_id": "inv_test_phasee_card_expired_success_043",
        "amount": 29900,
        "failure_category": "card_expired",
        "raw_error_code": "card_expired",
        "failure_reason": "Customer card has expired.",
        "result_detail": "Phase E UI test: deterministic successful customer recovery scenario.",
    },
    {
        "batch_id": "e2e_phase_e_card_expired_retry_001",
        "subscription_id": "sub_e2e_phase_e_card_expired_retry_001",
        "invoice_id": "inv_e2e_phase_e_card_expired_retry_001",
        "customer_id": "cust_e2e_phase_e_card_expired_retry_001",
        "customer_name": "Phase E Card Retry Customer",
        "customer_email": "phasee_card_retry@example.com",
        "razorpay_invoice_id": "inv_test_phasee_card_expired_retry_001",
        "amount": 29900,
        "failure_category": "card_expired",
        "raw_error_code": "card_expired",
        "failure_reason": "Customer card has expired.",
        "result_detail": "Phase E UI test: card expired with previous retry.",
    },
    {
        "batch_id": "e2e_phase_e_unclassified_001",
        "subscription_id": "sub_e2e_phase_e_unclassified_001",
        "invoice_id": "inv_e2e_phase_e_unclassified_001",
        "customer_id": "cust_e2e_phase_e_unclassified_001",
        "customer_name": "Phase E Unclassified Customer",
        "customer_email": "phasee_unclassified@example.com",
        "razorpay_invoice_id": "inv_test_phasee_unclassified_001",
        "amount": 29900,
        "failure_category": "unclassified",
        "raw_error_code": "unknown_error",
        "failure_reason": "Synthetic gateway failure requiring manual review.",
        "result_detail": "Phase E UI test: unclassified/manual-review scenario.",
    },
]


def create_scenario(scenario: dict) -> None:
    """Create one isolated synthetic Phase-E scenario."""

    batch_id = scenario["batch_id"]
    subscription_id = scenario["subscription_id"]
    invoice_id = scenario["invoice_id"]

    timestamp = "2026-08-30T18:00:00+00:00"

    # -----------------------------------------------------------------
    # Batch
    # -----------------------------------------------------------------

    create_batch_run(
        batch_id,
        started_at=timestamp,
        status="running",
    )

    # -----------------------------------------------------------------
    # Subscription
    # -----------------------------------------------------------------

    upsert_subscription(
        {
            "subscription_id": subscription_id,
            "batch_id": batch_id,
            "razorpay_subscription_id": None,
            "customer_id": scenario["customer_id"],
            "customer_name": scenario["customer_name"],
            "customer_email": scenario["customer_email"],
            "plan_id": "plan_dunnflow_basic",
            "plan_name": "DunnFlow Basic",
            "amount": scenario["amount"],
            "currency": "INR",
            "status": "pending",
            "current_cycle": 1,
            "total_cycles": 12,
            "retry_count": 0,
            "last_failure_category": scenario["failure_category"],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    )

    # -----------------------------------------------------------------
    # Invoice
    # -----------------------------------------------------------------

    upsert_invoice(
        {
            "invoice_id": invoice_id,
            "batch_id": batch_id,
            "subscription_id": subscription_id,
            "razorpay_invoice_id": scenario["razorpay_invoice_id"],
            "amount": scenario["amount"],
            "currency": "INR",
            "status": "issued",
            "issued_at": timestamp,
            "paid_at": None,
            "due_at": "2026-09-02T18:00:00+00:00",
            "failure_category": scenario["failure_category"],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    )

    # -----------------------------------------------------------------
    # Initial failed payment attempt
    # -----------------------------------------------------------------

    attempt_id = create_payment_attempt(
        {
            "batch_id": batch_id,
            "invoice_id": invoice_id,
            "subscription_id": subscription_id,
            "razorpay_payment_id": f"pay_{invoice_id}_01",
            "attempt_number": 1,
            "attempt_type": "initial_charge",
            "action_type": "initial_subscription_charge",
            "scheduled_for": timestamp,
            "executed_at": timestamp,
            "result": "failed",
            "raw_error_code": scenario["raw_error_code"],
            "failure_reason": scenario["failure_reason"],
            "gateway_status": "failed",
            "result_detail": scenario["result_detail"],
            "created_at": timestamp,
        }
    )

    # -----------------------------------------------------------------
    # Initial financial events
    #
    # These are important because the normal benchmark seeding flow
    # records the financial history explicitly.
    # -----------------------------------------------------------------

    record_revenue_event(
        {
            "batch_id": batch_id,
            "subscription_id": subscription_id,
            "invoice_id": invoice_id,
            "payment_attempt_id": attempt_id,
            "event_type": "revenue_at_risk",
            "amount": scenario["amount"],
            "event_timestamp": timestamp,
            "detail": (
                f"Invoice {invoice_id} entered recovery scope "
                "after a failed subscription charge."
            ),
        }
    )

    record_revenue_event(
        {
            "batch_id": batch_id,
            "subscription_id": subscription_id,
            "invoice_id": invoice_id,
            "payment_attempt_id": attempt_id,
            "event_type": "payment_failed",
            "amount": scenario["amount"],
            "event_timestamp": timestamp,
            "detail": (
                f"Initial charge failed with "
                f"category={scenario['failure_category']}."
            ),
        }
    )

    # -----------------------------------------------------------------
    # Scenario 3 deliberately contains one previous failed recovery
    # attempt so the UI can display retry history.
    # -----------------------------------------------------------------

    if batch_id == "e2e_phase_e_card_expired_retry_001":
        create_payment_attempt(
            {
                "batch_id": batch_id,
                "invoice_id": invoice_id,
                "subscription_id": subscription_id,
                "razorpay_payment_id": f"pay_{invoice_id}_02",
                "attempt_number": 2,
                "attempt_type": "recovery_payment",
                "action_type": "retry_payment",
                "scheduled_for": "2026-08-31T18:00:00+00:00",
                "executed_at": "2026-08-31T18:05:00+00:00",
                "result": "failed",
                "raw_error_code": scenario["raw_error_code"],
                "failure_reason": scenario["failure_reason"],
                "gateway_status": "failed",
                "result_detail": (
                    "Phase E UI test: previous recovery attempt failed."
                ),
                "created_at": "2026-08-31T18:05:00+00:00",
            }
        )


def main() -> None:
    """Create all Phase-E synthetic scenarios."""

    init_db()

    print("=" * 60)
    print("DUNNFLOW PHASE-E SYNTHETIC SCENARIOS")
    print("=" * 60)

    for scenario in SCENARIOS:
        create_scenario(scenario)

        print(
            f"CREATED: {scenario['batch_id']} | "
            f"{scenario['failure_category']}"
        )

    print("=" * 60)
    print("Phase-E synthetic scenario creation complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()