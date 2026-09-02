
"""
DunnFlow controlled AI/orchestrator integration test.

This is the final controlled Phase 4.6 benchmark proof.

It:
1. Resets and seeds the deterministic 60-case benchmark.
2. Runs the REAL DunnFlow orchestrator.
3. Injects a controlled AI advisor.
4. Forces AI to recommend retry_payment for every case.
5. Verifies AI/policy agreements and deliberate disagreements.
6. Verifies deterministic policy remains authoritative.
7. Verifies final financial metrics match the frozen deterministic baseline.
8. Verifies ai_policy_check audit records.
"""

from __future__ import annotations

from backend.ai.recovery_advisor import (
    AIConfig,
    AIProvider,
    RecoveryAdvisor,
)
from backend.data.db import (
    get_batch_metrics,
    get_conn,
)
from backend.data.seed_data import seed_benchmark
from orchestrator import run_batch


BATCH_ID = "benchmark_60_subscription_failures"

EXPECTED = {
    "historical_invoices_at_risk": 60,
    "historical_amount_at_risk": 6354000,
    "recovered_count": 29,
    "amount_recovered": 3147100,
    "recovery_rate_pct": 49.5,
    "in_progress_count": 21,
    "blocked_count": 4,
    "manual_review_count": 6,
    "outcome_count_total": 60,
    "average_recovery_attempts": 0.52,
}


class ControlledAIProvider(AIProvider):
    """
    Intentionally unsafe recommendation.

    retry_payment is correct for insufficient_funds, but deliberately
    conflicts with card_expired, auth_failed, and other deterministic
    policies. This proves AI cannot authorize execution.
    """

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        return """
{
  "priority_score": 90,
  "urgency": "high",
  "recommended_action": "retry_payment",
  "confidence": 0.99,
  "reason": "Controlled integration test recommendation.",
  "customer_strategy": "Controlled integration test strategy."
}
""".strip()


def make_controlled_advisor() -> RecoveryAdvisor:
    config = AIConfig(
        provider="test",
        api_key="controlled-test-key",
        model="controlled-test-model",
        enabled=True,
        timeout_seconds=5,
    )

    return RecoveryAdvisor(
        config=config,
        provider=ControlledAIProvider(),
    )


def fetch_ai_policy_audit_rows() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                invoice_id,
                failure_category,
                action_taken,
                result,
                detail
            FROM audit_log
            WHERE batch_id = ?
              AND stage = 'ai_policy_check'
            ORDER BY timestamp, invoice_id
            """,
            (BATCH_ID,),
        ).fetchall()

    return [dict(row) for row in rows]


def main() -> None:
    print("=" * 72)
    print("DUNNFLOW CONTROLLED AI / ORCHESTRATOR INTEGRATION TEST")
    print("=" * 72)
    print()

    # ------------------------------------------------------------
    # Start from a completely clean deterministic benchmark.
    # ------------------------------------------------------------

    print("SEEDING CLEAN 60-CASE BENCHMARK")
    print("-" * 72)

    seed_benchmark(
        reset=True,
        size=60,
    )

    print("Clean benchmark seeded.")
    print()

    # ------------------------------------------------------------
    # Run the REAL orchestrator with controlled AI injected.
    # ------------------------------------------------------------

    advisor = make_controlled_advisor()

    report = run_batch(
        BATCH_ID,
        ai_advisor=advisor,
    )

    reconciliation = report["ai_reconciliation"]

    print("ORCHESTRATOR RESULT")
    print("-" * 72)
    print(f"AI enabled:       {reconciliation['enabled']}")
    print(f"AI cases checked: {reconciliation['checked']}")
    print(f"AI agreements:    {reconciliation['agreements']}")
    print(f"AI disagreements: {reconciliation['disagreements']}")
    print(f"AI unavailable:   {reconciliation['ai_unavailable']}")
    print()

    # ------------------------------------------------------------
    # 60 fresh eligible benchmark invoices must reach AI.
    # ------------------------------------------------------------

    assert reconciliation["checked"] == 60, (
        f"Expected AI reconciliation for all 60 benchmark invoices, "
        f"got {reconciliation['checked']}."
    )

    assert (
        reconciliation["agreements"]
        + reconciliation["disagreements"]
        + reconciliation["ai_unavailable"]
        == 60
    ), (
        "AI reconciliation counts do not sum to 60."
    )

    assert reconciliation["ai_unavailable"] == 0, (
        "Controlled AI provider unexpectedly became unavailable."
    )

    # ------------------------------------------------------------
    # Controlled AI recommends retry_payment everywhere.
    #
    # The deterministic policy must override that recommendation
    # whenever the policy requires another action.
    # ------------------------------------------------------------

    results = reconciliation["results"]

    disagreements = [
        row
        for row in results
        if row["result"] == "disagreement"
    ]

    assert disagreements, (
        "Expected controlled AI/policy disagreements."
    )

    card_expired_conflicts = [
        row
        for row in results
        if (
            row["ai_action"] == "retry_payment"
            and row["deterministic_action"] == "payment_method_update"
            and row["result"] == "disagreement"
        )
    ]

    assert card_expired_conflicts, (
        "Expected card_expired payment_method_update conflicts."
    )

    # ------------------------------------------------------------
    # Verify real ai_policy_check audit records.
    # ------------------------------------------------------------

    audit_rows = fetch_ai_policy_audit_rows()

    assert len(audit_rows) == 60, (
        f"Expected 60 ai_policy_check audit rows, got {len(audit_rows)}."
    )

    # ------------------------------------------------------------
    # Final benchmark metrics MUST match the frozen deterministic
    # baseline.
    #
    # This is the strongest proof that AI advice cannot alter
    # financial execution.
    # ------------------------------------------------------------

    metrics = get_batch_metrics(BATCH_ID)

    for key, expected_value in EXPECTED.items():
        actual_value = metrics[key]

        assert actual_value == expected_value, (
            f"Metric mismatch for {key}: "
            f"expected {expected_value}, got {actual_value}."
        )

    # ------------------------------------------------------------
    # Verify financial outcome counts remain internally consistent.
    # ------------------------------------------------------------

    assert metrics["outcome_count_matches_invoice_count"] is True, (
        "Outcome count does not match invoice count."
    )

    # ------------------------------------------------------------
    # Display proof.
    # ------------------------------------------------------------

    example = card_expired_conflicts[0]

    print("SAFETY VERIFICATION")
    print("-" * 72)
    print(f"AI policy audit rows:      {len(audit_rows)}")
    print(f"AI/policy disagreements:   {len(disagreements)}")
    print(f"Final recovered count:     {metrics['recovered_count']}")
    print(
        f"Final recovered amount:    "
        f"?{metrics['amount_recovered'] / 100:,.0f}"
    )
    print(f"Final recovery rate:       {metrics['recovery_rate_pct']}%")
    print(f"Final in-progress count:   {metrics['in_progress_count']}")
    print(f"Final blocked count:       {metrics['blocked_count']}")
    print(f"Final manual-review count: {metrics['manual_review_count']}")
    print()

    print("CARD_EXPIRED CONFLICT EXAMPLE")
    print("-" * 72)
    print(f"Invoice:              {example['invoice_id']}")
    print(f"AI action:            {example['ai_action']}")
    print(f"Deterministic action: {example['deterministic_action']}")
    print(f"Reconciliation:       {example['result']}")
    print()

    print("=" * 72)
    print("CONTROLLED AI / ORCHESTRATOR INTEGRATION PASSED")
    print("=" * 72)
    print()
    print("PROOF:")
    print("  Fresh 60-case benchmark -> real DunnFlow orchestrator")
    print("  Controlled AI recommendation injected")
    print("  60/60 cases reconciled")
    print("  AI intentionally disagrees with deterministic policy")
    print("  Deterministic action remains FINAL")
    print("  Final financial metrics match frozen deterministic baseline")
    print("  60 ai_policy_check audit records persisted")
    print("=" * 72)


if __name__ == "__main__":
    main()
