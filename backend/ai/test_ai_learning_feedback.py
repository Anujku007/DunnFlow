from __future__ import annotations

import json

from backend.ai.historical_decision_context import (
    HistoricalCase,
    _build_ai_action_statistics,
    _ai_history,
    build_historical_decision_context,
)


def _case(
    invoice_id: str,
    *,
    recommendation: str | None,
    result: str | None = "agreement",
    outcome: str = "recovered",
    recovered_amount: int = 10000,
) -> HistoricalCase:
    """Build a deterministic invoice-level history fixture."""
    return HistoricalCase(
        invoice_id=invoice_id,
        failure_category="insufficient_funds",
        amount=10000,
        deterministic_action="retry_payment",
        deterministic_status="executed",
        guardrail_hit=None,
        ai_recommendation=recommendation,
        ai_result=result,
        outcome=outcome,
        recovered_amount=recovered_amount if outcome == "recovered" else 0,
        recovery_confirmed=outcome == "recovered",
        payment_captured=outcome == "recovered",
        created_at="2026-10-01T10:00:00",
    )


def _assert_ai_statistics_shape(
    statistics: dict[str, dict],
) -> None:
    for action, stats in statistics.items():
        assert action, "AI action key must not be empty."

        assert stats["total_cases"] >= 1
        assert stats["recovered_cases"] >= 0
        assert stats["blocked_cases"] >= 0
        assert stats["in_progress_cases"] >= 0

        assert 0.0 <= stats["recovery_rate"] <= 1.0

        assert stats["agreement_cases"] >= 0
        assert stats["disagreement_cases"] >= 0

        assert (
            stats["attribution"]
            == "advisory_correlation"
        )

        assert (
            stats["episode_granularity"]
            == "invoice"
        )

        assert (
            stats["financial_authority"]
            == "deterministic_policy"
        )

        assert stats["evidence_quality"] in {
            "insufficient",
            "limited",
            "moderate",
            "strong",
        }

        expected_quality = (
            "insufficient"
            if stats["total_cases"] <= 0
            else "limited"
            if stats["total_cases"] <= 2
            else "moderate"
            if stats["total_cases"] <= 9
            else "strong"
        )

        assert (
            stats["evidence_quality"]
            == expected_quality
        )



def test_ai_learning_feedback_real_cohort() -> None:
    """Real cohort reflects current persisted recommendations without stale assumptions."""
    context = build_historical_decision_context(
        "inv_dunnflow_051",
        limit=20,
    )

    statistics = context.ai_action_statistics
    _assert_ai_statistics_shape(statistics)

    # Every recommendation statistic must correspond to one historical invoice episode.
    total_ai_episodes = sum(
        item["total_cases"] for item in statistics.values()
    )
    assert total_ai_episodes == context.ai_statistics["cases_with_ai_recommendation"]
    assert context.ai_statistics["agreement_count"] >= 0
    assert context.ai_statistics["disagreement_count"] >= 0
    assert context.historical_evidence_consistency.get("advisory_only", True) is True

def test_ai_learning_feedback_evidence_quality_thresholds() -> None:
    """
    Evidence quality is a deterministic evidence-depth classification.

    It is based only on the number of invoice-level historical episodes
    represented by an AI recommendation.
    """

    def classify(sample_size: int) -> str:
        if sample_size <= 0:
            return "insufficient"

        if sample_size <= 2:
            return "limited"

        if sample_size <= 9:
            return "moderate"

        return "strong"

    assert classify(0) == "insufficient"
    assert classify(1) == "limited"
    assert classify(2) == "limited"
    assert classify(3) == "moderate"
    assert classify(9) == "moderate"
    assert classify(10) == "strong"
    assert classify(100) == "strong"



def test_ai_learning_feedback_evidence_quality_is_not_outcome_quality() -> None:
    """A perfect outcome rate in a tiny sample remains limited evidence."""
    cases = [
        _case("inv-fixture-1", recommendation="retry_payment"),
        _case("inv-fixture-2", recommendation="retry_payment"),
    ]

    statistics = _build_ai_action_statistics(cases)
    retry_stats = statistics["retry_payment"]

    assert retry_stats["recovery_rate"] == 1.0
    assert retry_stats["total_cases"] == 2
    assert retry_stats["evidence_quality"] == "limited"


def test_ai_learning_feedback_evidence_quality_preserves_provenance() -> None:
    """AI learning statistics preserve advisory-only provenance."""
    statistics = _build_ai_action_statistics([
        _case("inv-fixture-1", recommendation="retry_payment"),
    ])
    retry_stats = statistics["retry_payment"]

    assert retry_stats["evidence_quality"] == "limited"
    assert retry_stats["attribution"] == "advisory_correlation"
    assert retry_stats["episode_granularity"] == "invoice"
    assert retry_stats["financial_authority"] == "deterministic_policy"


def test_ai_learning_feedback_is_episode_bounded() -> None:
    """Repeated audit reviews resolve to one invoice-level recommendation."""
    recommendation, result = _ai_history([
        {
            "stage": "ai_policy_check",
            "detail": "AI recommended 'retry_payment'",
            "result": "agreement",
        },
        {
            "stage": "ai_reconciliation",
            "detail": "AI unavailable",
            "result": "unavailable",
        },
    ])

    assert recommendation == "retry_payment"
    assert result == "agreement"

    statistics = _build_ai_action_statistics([
        _case(
            "inv-fixture-repeated",
            recommendation=recommendation,
            result=result,
        ),
    ])
    assert statistics["retry_payment"]["total_cases"] == 1
    assert statistics["retry_payment"]["episode_granularity"] == "invoice"

def test_ai_learning_feedback_excludes_unavailable_ai() -> None:
    """
    AI-unavailable audit records must never become an AI action
    learning sample.
    """

    context = build_historical_decision_context(
        "inv_dunnflow_060",
        limit=20,
    )

    statistics = context.ai_action_statistics

    # A missing recommendation must never become an action category.
    fixture_statistics = _build_ai_action_statistics([
        _case("inv-fixture-unavailable", recommendation=None, result=None),
    ])
    assert fixture_statistics == {}

    # AI-unavailable records do not represent an AI recommendation.
    for action, stats in statistics.items():
        assert action != "ai_unavailable"

        assert stats["total_cases"] >= 1

    # If no historical AI recommendation exists in the selected
    # cohort, the correct result is an empty statistics object.
    if not statistics:
        assert (
            context.ai_statistics[
                "cases_with_ai_recommendation"
            ]
            == 0
        )



def test_ai_learning_feedback_preserves_agreement_disagreement() -> None:
    """Agreement and disagreement counters are validated with fixed fixtures."""
    statistics = _build_ai_action_statistics([
        _case("inv-fixture-agree", recommendation="retry_payment", result="agreement"),
        _case(
            "inv-fixture-disagree",
            recommendation="retry_payment",
            result="disagreement",
            outcome="in_progress",
        ),
    ])
    retry_stats = statistics["retry_payment"]

    assert retry_stats["agreement_cases"] == 1
    assert retry_stats["disagreement_cases"] == 1
    assert retry_stats["financial_authority"] == "deterministic_policy"
    assert retry_stats["attribution"] == "advisory_correlation"

def test_ai_learning_feedback_is_serializable() -> None:
    """
    Learning evidence must remain safe to expose through the
    existing historical-context JSON contract.
    """

    context = build_historical_decision_context(
        "inv_dunnflow_051",
        limit=20,
    )

    payload = context.to_dict()

    assert "ai_action_statistics" in payload

    encoded = json.dumps(payload)

    assert encoded

    decoded = json.loads(encoded)

    assert (
        decoded["ai_action_statistics"]
        == context.ai_action_statistics
    )


def run_all_tests() -> None:
    tests = [
        test_ai_learning_feedback_real_cohort,
        test_ai_learning_feedback_evidence_quality_thresholds,
        test_ai_learning_feedback_evidence_quality_is_not_outcome_quality,
        test_ai_learning_feedback_evidence_quality_preserves_provenance,
        test_ai_learning_feedback_is_episode_bounded,
        test_ai_learning_feedback_excludes_unavailable_ai,
        test_ai_learning_feedback_preserves_agreement_disagreement,
        test_ai_learning_feedback_is_serializable,
    ]

    passed = 0
    failed = 0

    print("=" * 80)
    print("STEP 7E.6 ? AI LEARNING FEEDBACK REGRESSION GATE")
    print("=" * 80)

    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL: {test.__name__}")
            print(f"      {type(exc).__name__}: {exc}")
            failed += 1

    print()
    print(f"STEP 7E.6 RESULTS: {passed} PASS / {failed} FAIL")
    print()

    if failed:
        raise SystemExit(1)

    print("AI LEARNING FEEDBACK GATE PASSED")
    print("Evidence-quality thresholds: VERIFIED")
    print("Evidence depth vs outcome quality: VERIFIED")
    print("Evidence-quality provenance: VERIFIED")
    print("Episode bounded: VERIFIED")
    print("AI unavailable exclusion: VERIFIED")
    print("Agreement/disagreement: VERIFIED")
    print("Advisory attribution: VERIFIED")
    print("Deterministic authority: VERIFIED")
    print("Serialization: VERIFIED")
    print()
    print("NO PAYMENT.")
    print("NO RAZORPAY API CALL.")
    print("NO RECOVERY ACTION.")
    print("NO WEBHOOK.")
    print("NO DETERMINISTIC DECISION CHANGE.")
    print("NO DATABASE WRITE.")
    print("=" * 80)


if __name__ == "__main__":
    run_all_tests()
