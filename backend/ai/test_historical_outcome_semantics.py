from backend.ai.historical_decision_context import (
    HistoricalCase,
    _determine_outcome,
    _build_learning_signal,
)


def test_payment_captured_without_recovery_confirmation():
    """Capture alone must not count as confirmed recovery."""
    (
        outcome,
        recovered_amount,
        recovery_confirmed,
        payment_captured,
    ) = _determine_outcome(
        [],
        [
            {
                "event_type": "payment_captured",
                "amount": 29900,
            }
        ],
    )

    assert outcome != "recovered"
    assert recovered_amount == 0
    assert recovery_confirmed is False
    assert payment_captured is True


def test_unresolved_cases_are_not_negative_outcome_evidence():
    """A cohort with no resolved outcomes must not be labelled unfavorable."""
    cases = [
        HistoricalCase(
            invoice_id=f"inv-test-{i}",
            failure_category="card_expired",
            amount=29900,
            deterministic_action="no_action",
            deterministic_status="pending",
            guardrail_hit=None,
            ai_recommendation=None,
            ai_result=None,
            outcome="in_progress",
            recovered_amount=0,
            recovery_confirmed=False,
            payment_captured=False,
            created_at=None,
        )
        for i in range(20)
    ]

    signal = _build_learning_signal(cases)

    assert signal["signal"] != "historically_unfavorable"
    assert signal.get("historical_recovery_rate") is None
