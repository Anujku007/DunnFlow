import ast
from pathlib import Path

import pytest

import backend.ai.historical_decision_context as h


def make_case(invoice_id, outcome, amount=49900, created_at="2026-10-01T12:00:00+00:00"):
    return h.HistoricalCase(
        invoice_id=invoice_id,
        failure_category="insufficient_funds",
        amount=amount,
        deterministic_action="retry_payment",
        deterministic_status="executed",
        guardrail_hit=None,
        ai_recommendation="retry_payment",
        ai_result="available",
        outcome=outcome,
        recovered_amount=amount if outcome == "recovered" else 0,
        recovery_confirmed=outcome == "recovered",
        payment_captured=outcome == "recovered",
        created_at=created_at,
    )


def rate_dicts(value):
    result = []
    if isinstance(value, dict):
        if "recovery_rate" in value:
            result.append(value)
        for child in value.values():
            result.extend(rate_dicts(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            result.extend(rate_dicts(child))
    return result


@pytest.mark.parametrize("function_name", [
    "_build_action_statistics",
    "_build_ai_statistics",
    "_build_ai_action_statistics",
    "_build_amount_band_learning",
])
def test_statistics_exclude_unresolved_from_recovery_rate(function_name):
    cases = [
        make_case("recovered", "recovered"),
        make_case("failed", "executed_no_recovery"),
        make_case("pending1", "in_progress"),
        make_case("pending2", "in_progress"),
    ]
    if function_name == "_build_amount_band_learning":
        result = h._build_amount_band_learning(49900, cases)
        assert result["recovery_rate"] == 0.5, result
    elif function_name == "_build_ai_statistics":
        result = h._build_ai_statistics(cases)
        assert result["recovery_rate_after_ai_review"] == 0.5, result
        assert result["resolved_sample_size_after_ai_review"] == 2, result
    else:
        result = getattr(h, function_name)(cases)
        rates = rate_dicts(result)
        assert rates, result
        assert any(item.get("recovery_rate") == 0.5 for item in rates), result


def test_recency_overall_rate_excludes_unresolved():
    cases = [
        make_case("r1", "recovered", created_at="2026-10-04T12:00:00+00:00"),
        make_case("r2", "executed_no_recovery", created_at="2026-10-03T12:00:00+00:00"),
        make_case("r3", "in_progress", created_at="2026-10-02T12:00:00+00:00"),
        make_case("r4", "in_progress", created_at="2026-10-01T12:00:00+00:00"),
    ]
    result = h._build_recency_learning(cases)
    assert result.get("overall_recovery_rate") == 0.5, result


def test_recency_rates_are_none_when_every_case_is_unresolved():
    cases = [
        make_case("u1", "in_progress", created_at="2026-10-02T12:00:00+00:00"),
        make_case("u2", "in_progress", created_at="2026-10-01T12:00:00+00:00"),
    ]
    result = h._build_recency_learning(cases)
    assert result.get("overall_recovery_rate") is None, result
    assert result.get("recent_recovery_rate") is None, result


def test_customer_behavior_uses_revenue_events_and_tracks_attempts():
    source = Path(h.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_build_customer_behavior"
    )
    body = ast.get_source_segment(source, function)
    assert body is not None
    assert "get_revenue_events" in body
    assert "get_payment_attempts" in body
    assert "outcome_count = recovered_count + failed_count" in body


def test_all_unresolved_action_cases_have_none_recovery_rate():
    cases = [
        make_case("pending1", "in_progress"),
        make_case("pending2", "in_progress"),
    ]
    result = h._build_action_statistics(cases)
    rates = rate_dicts(result)
    assert rates, result
    assert any(item.get("recovery_rate") is None for item in rates), result
