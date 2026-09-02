from __future__ import annotations

import json

from backend.ai.ai_policy_reconciliation import reconcile_ai_with_policy
from backend.ai.recovery_advisor import AIConfig, AIProvider, RecoveryAdvisor
from backend.ai.recovery_context import build_recovery_context
from backend.data.db import (
    get_audit_log,
    get_conn,
    get_invoice,
)
from backend.modules.decision_engine import decide_for_invoice


class ControlledAIProvider(AIProvider):
    """Deterministic test provider used to force an AI/policy conflict."""

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        return json.dumps(
            {
                "priority_score": 95,
                "urgency": "high",
                "recommended_action": "retry_payment",
                "confidence": 0.99,
                "reason": "Controlled benchmark test recommendation.",
                "customer_strategy": "Controlled benchmark test strategy.",
            }
        )


def make_advisor() -> RecoveryAdvisor:
    config = AIConfig(
        provider="test",
        api_key="test",
        model="test-model",
        enabled=True,
        timeout_seconds=5,
    )

    return RecoveryAdvisor(
        config=config,
        provider=ControlledAIProvider(),
    )


def find_card_expired_invoice() -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM invoices
            WHERE batch_id = ?
              AND failure_category = ?
              AND status = 'issued'
            ORDER BY invoice_id
            LIMIT 1
            """,
            (
                "benchmark_60_subscription_failures",
                "card_expired",
            ),
        ).fetchone()

    assert row is not None, "No eligible card_expired benchmark invoice found."
    return dict(row)


def count_payment_attempts(invoice_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM payment_attempts
            WHERE invoice_id = ?
            """,
            (invoice_id,),
        ).fetchone()

    return int(row[0])


def count_revenue_events(invoice_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM revenue_events
            WHERE invoice_id = ?
            """,
            (invoice_id,),
        ).fetchone()

    return int(row[0])


def test_real_benchmark_ai_policy_reconciliation() -> None:
    invoice = find_card_expired_invoice()
    invoice_id = invoice["invoice_id"]

    before_attempts = count_payment_attempts(invoice_id)
    before_revenue_events = count_revenue_events(invoice_id)

    context = build_recovery_context(invoice_id)

    deterministic_decision = decide_for_invoice(
        invoice_id,
        persist=True,
    )

    assert deterministic_decision is not None
    assert deterministic_decision["action_type"] == "payment_method_update"

    advisor = make_advisor()

    advisor = make_advisor()

    result = reconcile_ai_with_policy(
        context=context,
        deterministic_decision=deterministic_decision,
        advisor=advisor,
    )

    assert result.result == "disagreement"
    assert result.ai_available is True
    assert result.ai_action == "retry_payment"
    assert result.deterministic_action == "payment_method_update"

    # CRITICAL SAFETY INVARIANT:
    # The AI recommendation must not mutate the deterministic action.
    assert deterministic_decision["action_type"] == "payment_method_update"

    # Reconciliation itself must have no financial side effects.
    after_attempts = count_payment_attempts(invoice_id)
    after_revenue_events = count_revenue_events(invoice_id)

    assert after_attempts == before_attempts
    assert after_revenue_events == before_revenue_events

    latest_invoice = get_invoice(invoice_id)
    assert latest_invoice is not None
    assert latest_invoice["status"] == "issued"

    # Verify the real database audit record.
    audit_rows = get_audit_log(
        invoice_id=invoice_id,
    )

    reconciliation_rows = [
        row
        for row in audit_rows
        if row["stage"] == "ai_policy_check"
    ]

    assert reconciliation_rows, (
        "Expected a real ai_policy_check audit record."
    )

    latest_reconciliation = reconciliation_rows[-1]

    assert latest_reconciliation["result"] == "disagreement"
    assert latest_reconciliation["action_taken"] == "payment_method_update"

    detail = latest_reconciliation["detail"]
    assert "retry_payment" in detail
    assert "payment_method_update" in detail

    print(f"BENCHMARK INVOICE: {invoice_id}")
    print("FAILURE CATEGORY: card_expired")
    print("AI ACTION: retry_payment")
    print("DETERMINISTIC ACTION: payment_method_update")
    print("FINAL ACTION: payment_method_update")
    print("AI/POLICY RESULT: disagreement")
    print(f"PAYMENT ATTEMPTS BEFORE: {before_attempts}")
    print(f"PAYMENT ATTEMPTS AFTER:  {after_attempts}")
    print(f"REVENUE EVENTS BEFORE:   {before_revenue_events}")
    print(f"REVENUE EVENTS AFTER:    {after_revenue_events}")
    print("INVOICE STATUS AFTER:    issued")
    print("REAL AUDIT RECORD:       ai_policy_check")
    print()
    print("BENCHMARK-BACKED AI/POLICY RECONCILIATION PASSED")


if __name__ == "__main__":
    test_real_benchmark_ai_policy_reconciliation()
