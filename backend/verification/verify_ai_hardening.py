from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai.recovery_advisor import (
    AIProviderError,
    AIRecoveryRecommendation,
    AIUnavailableResult,
    RecoveryAdvisor,
)
from backend.ai.recovery_context import RecoveryContext
from backend.ai.ai_policy_reconciliation import reconcile_ai_with_policy
from backend.modules.diagnosis import classify


passed = 0
failed = 0


def check(name, test):
    global passed, failed
    try:
        test()
        passed += 1
        print(f"PASS: {name}")
    except Exception as exc:
        failed += 1
        print(f"FAIL: {name}")
        print(f"      {type(exc).__name__}: {exc}")


def expect_ai_error(payload, expected_text=None):
    try:
        RecoveryAdvisor._validate_recommendation(payload)
    except AIProviderError as exc:
        if expected_text and expected_text not in str(exc):
            raise AssertionError(
                f"Expected error containing {expected_text!r}, got {str(exc)!r}"
            )
        return
    raise AssertionError("Expected AIProviderError, but validation succeeded")


VALID = {
    "priority_score": 70,
    "urgency": "normal",
    "recommended_action": "retry_payment",
    "confidence": 0.85,
    "reason": "A retry may be appropriate after the failure.",
    "customer_strategy": "Retry according to deterministic policy.",
}


def test_prompt_contract():
    prompt_file = ROOT / "backend" / "ai" / "prompts.py"
    source = prompt_file.read_text(encoding="utf-8")

    required = [
        "Action selection contract",
        "retry_payment",
        "auto_retry_same_card",
        "customer_action",
        "payment_method_update",
        "manual_review",
        "no_action",
        "Deterministic",
    ]

    missing = [item for item in required if item not in source]
    if missing:
        raise AssertionError(f"Prompt is missing: {missing}")


def test_valid_recommendation():
    RecoveryAdvisor._validate_recommendation(dict(VALID))


def test_missing_reason():
    payload = dict(VALID)
    payload.pop("reason")
    expect_ai_error(payload, "reason")


def test_missing_urgency():
    payload = dict(VALID)
    payload.pop("urgency")
    expect_ai_error(payload, "urgency")


def test_unsupported_action():
    payload = dict(VALID)
    payload["recommended_action"] = "refund_everything"
    expect_ai_error(payload, "not a valid DunnFlow action")


def test_boolean_priority_rejected():
    payload = dict(VALID)
    payload["priority_score"] = True
    expect_ai_error(payload, "priority_score must be an integer")


def test_priority_range_rejected():
    payload = dict(VALID)
    payload["priority_score"] = 101
    expect_ai_error(payload, "between 0 and 100")


def test_confidence_range_rejected():
    payload = dict(VALID)
    payload["confidence"] = 1.5
    expect_ai_error(payload, "between 0.0 and 1.0")


def test_invalid_urgency_rejected():
    payload = dict(VALID)
    payload["urgency"] = "critical"
    expect_ai_error(payload, "urgency must be one of")


def test_non_dict_rejected():
    expect_ai_error(["not", "a", "dictionary"], "JSON object")


def test_diagnosis_mapping():
    expected = {
        "insufficient_fund": "insufficient_funds",
        "insufficient_funds": "insufficient_funds",
        "payment_timed_out": "bank_timeout",
        "authentication_failed": "auth_failed",
        "card_expired": "card_expired",
        "unknown_gateway_code": "unclassified",
        None: "unclassified",
    }

    for raw_code, expected_category in expected.items():
        actual = classify(raw_code)
        if actual != expected_category:
            raise AssertionError(
                f"{raw_code!r}: expected {expected_category!r}, got {actual!r}"
            )


def make_context():
    return RecoveryContext(
        invoice={"invoice_id": "offline_test_invoice", "batch_id": "offline_test"},
        subscription={"subscription_id": "offline_test_subscription"},
        customer={},
        failure_category="insufficient_funds",
        raw_gateway_error="insufficient_fund",
        failure_reason="Synthetic offline test",
        invoice_amount=29900,
        payment_attempts=[],
        recovery_actions=[],
        retry_count=0,
        time_since_previous_retry_seconds=None,
        previous_recovery_actions=[],
        invoice_status="issued",
        customer_action_history=[],
        revenue_events=[],
        audit_history=[],
    )


class StubAdvisor:
    def __init__(self, result):
        self.result = result

    def recommend(self, context):
        return self.result


def make_recommendation(action):
    return AIRecoveryRecommendation(
        priority_score=70,
        urgency="normal",
        recommended_action=action,
        confidence=0.85,
        reason="Synthetic offline test recommendation",
        customer_strategy="Advisory only",
        learning_influence={},
    )


def test_reconciliation_agreement():
    context = make_context()
    logs = []

    result = reconcile_ai_with_policy(
        context=context,
        deterministic_decision={"action_type": "retry_payment"},
        advisor=StubAdvisor(make_recommendation("retry_payment")),
        audit_logger=logs.append,
    )

    assert result.result == "agreement"
    assert result.deterministic_action == "retry_payment"
    assert len(logs) == 1
    assert logs[0]["action_taken"] == "retry_payment"


def test_reconciliation_disagreement():
    context = make_context()
    logs = []

    result = reconcile_ai_with_policy(
        context=context,
        deterministic_decision={"action_type": "retry_payment"},
        advisor=StubAdvisor(make_recommendation("manual_review")),
        audit_logger=logs.append,
    )

    assert result.result == "disagreement"
    assert result.ai_action == "manual_review"
    assert result.deterministic_action == "retry_payment"
    assert logs[0]["action_taken"] == "retry_payment"


def test_ai_unavailable_preserves_deterministic_action():
    context = make_context()
    logs = []

    result = reconcile_ai_with_policy(
        context=context,
        deterministic_decision={"action_type": "retry_payment"},
        advisor=StubAdvisor(
            AIUnavailableResult(reason="Synthetic provider unavailable")
        ),
        audit_logger=logs.append,
    )

    assert result.result == "ai_unavailable"
    assert result.ai_available is False
    assert result.deterministic_action == "retry_payment"
    assert logs[0]["action_taken"] == "retry_payment"


print("=" * 68)
print("DUNNFLOW — OFFLINE AI HARDENING VERIFICATION")
print("=" * 68)
print("No live AI calls. No payment execution. No database writes.")
print("-" * 68)

tests = [
    ("Prompt contains all six allowed actions", test_prompt_contract),
    ("Validator accepts a valid recommendation", test_valid_recommendation),
    ("Validator safely rejects missing reason", test_missing_reason),
    ("Validator safely rejects missing urgency", test_missing_urgency),
    ("Validator rejects unsupported actions", test_unsupported_action),
    ("Validator rejects boolean priority", test_boolean_priority_rejected),
    ("Validator rejects priority above 100", test_priority_range_rejected),
    ("Validator rejects confidence above 1.0", test_confidence_range_rejected),
    ("Validator rejects invalid urgency", test_invalid_urgency_rejected),
    ("Validator rejects non-dictionary input", test_non_dict_rejected),
    ("Diagnosis maps gateway errors correctly", test_diagnosis_mapping),
    ("Reconciliation identifies agreement", test_reconciliation_agreement),
    ("Reconciliation preserves policy on disagreement", test_reconciliation_disagreement),
    ("AI unavailable preserves deterministic action", test_ai_unavailable_preserves_deterministic_action),
]

for name, test in tests:
    check(name, test)

print("-" * 68)
print(f"TOTAL:  {passed + failed}")
print(f"PASSED: {passed}")
print(f"FAILED: {failed}")
print("=" * 68)

sys.exit(0 if failed == 0 else 1)
