from __future__ import annotations

import json

from backend.ai.ai_policy_reconciliation import (
    reconcile_ai_with_policy,
)
from backend.ai.recovery_advisor import (
    AIConfig,
    AIProvider,
    RecoveryAdvisor,
)
from backend.ai.recovery_context import (
    RecoveryContext,
    build_recovery_context,
)


AUDIT_ENTRIES = []


def test_audit_logger(entry: dict) -> int:
    AUDIT_ENTRIES.append(entry)
    return len(AUDIT_ENTRIES)


class MockProvider(AIProvider):
    def __init__(self, response: str):
        self.response = response

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        return self.response


def make_context() -> RecoveryContext:
    return RecoveryContext(
        invoice={
            "invoice_id": "test_invoice",
            "batch_id": "test_batch",
            "status": "issued",
            "amount": 99900,
        },
        subscription={
            "subscription_id": "test_subscription",
            "batch_id": "test_batch",
            "status": "pending",
            "customer_id": "test_customer",
            "customer_name": "Test Customer",
            "customer_email": "test@example.com",
        },
        customer={
            "customer_id": "test_customer",
            "customer_name": "Test Customer",
            "customer_email": "test@example.com",
        },
        failure_category="card_expired",
        raw_gateway_error="card_expired",
        failure_reason="Card expired",
        invoice_amount=99900,
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


def make_advisor(ai_action: str) -> RecoveryAdvisor:
    response = json.dumps(
        {
            "priority_score": 90,
            "urgency": "high",
            "recommended_action": ai_action,
            "confidence": 0.95,
            "reason": "Test AI recommendation.",
            "customer_strategy": "Test customer strategy.",
        }
    )

    config = AIConfig(
        provider="test",
        api_key="test",
        model="test-model",
        enabled=True,
        timeout_seconds=5,
    )

    return RecoveryAdvisor(
        config=config,
        provider=MockProvider(response),
    )


def test_ai_agrees_with_policy() -> None:
    context = make_context()

    deterministic_decision = {
        "invoice_id": "test_invoice",
        "action_type": "payment_method_update",
        "decision": "scheduled",
    }

    AUDIT_ENTRIES.clear()

    result = reconcile_ai_with_policy(
        context=context,
        deterministic_decision=deterministic_decision,
        advisor=make_advisor("payment_method_update"),
        audit_logger=test_audit_logger,
    )

    assert result.result == "agreement"
    assert result.ai_action == "payment_method_update"
    assert result.deterministic_action == "payment_method_update"

    # The deterministic decision must remain untouched.
    assert deterministic_decision["action_type"] == "payment_method_update"
    assert len(AUDIT_ENTRIES) == 1
    assert AUDIT_ENTRIES[0]["stage"] == "ai_policy_check"
    assert AUDIT_ENTRIES[0]["result"] == "agreement"


def test_ai_disagreement_cannot_override_policy() -> None:
    context = make_context()

    deterministic_decision = {
        "invoice_id": "test_invoice",
        "action_type": "payment_method_update",
        "decision": "scheduled",
    }

    AUDIT_ENTRIES.clear()

    result = reconcile_ai_with_policy(
        context=context,
        deterministic_decision=deterministic_decision,
        advisor=make_advisor("retry_payment"),
        audit_logger=test_audit_logger,
    )

    assert result.result == "disagreement"
    assert result.ai_action == "retry_payment"
    assert result.deterministic_action == "payment_method_update"

    # Critical safety invariant:
    # AI disagreement must never mutate the final deterministic action.
    assert deterministic_decision["action_type"] == "payment_method_update"
    assert len(AUDIT_ENTRIES) == 1
    assert AUDIT_ENTRIES[0]["stage"] == "ai_policy_check"
    assert AUDIT_ENTRIES[0]["result"] == "disagreement"
    assert AUDIT_ENTRIES[0]["action_taken"] == "payment_method_update"


def test_ai_agreement_does_not_authorize_execution() -> None:
    context = make_context()

    deterministic_decision = {
        "invoice_id": "test_invoice",
        "action_type": "retry_payment",
        "decision": "scheduled",
    }

    AUDIT_ENTRIES.clear()

    result = reconcile_ai_with_policy(
        context=context,
        deterministic_decision=deterministic_decision,
        advisor=make_advisor("retry_payment"),
        audit_logger=test_audit_logger,
    )

    assert result.result == "agreement"

    # Reconciliation only observes the decision. It does not execute it.
    assert "executed_at" not in deterministic_decision
    assert deterministic_decision["action_type"] == "retry_payment"



def test_ai_learning_influence_is_observable() -> None:
    """Trusted historical learning influence must survive reconciliation."""

    # Use a real benchmark-backed invoice so RecoveryAdvisor can obtain
    # trusted historical context. The AI must not be allowed to invent
    # or override these historical values.
    context = build_recovery_context("inv_dunnflow_060")

    deterministic_decision = {
        "invoice_id": "inv_dunnflow_060",
        "action_type": "payment_method_update",
        "decision": "scheduled",
    }

    # Deliberately provide fabricated historical values from the AI.
    # RecoveryAdvisor must reject these as authoritative and use the
    # trusted DunnFlow historical context instead.
    response = json.dumps(
        {
            "priority_score": 90,
            "urgency": "high",
            "recommended_action": "retry_payment",
            "confidence": 0.95,
            "reason": "Historical evidence was considered.",
            "customer_strategy": "Test historical strategy.",
            "learning_influence": {
                "used": True,
                "signal": "historically_favorable",
                "sample_size": 999,
                "confidence": 0.99,
                "historical_recovery_rate": 0.99,
            },
        }
    )

    config = AIConfig(
        provider="test",
        api_key="test",
        model="test-model",
        enabled=True,
        timeout_seconds=5,
    )

    advisor = RecoveryAdvisor(
        config=config,
        provider=MockProvider(response),
    )

    AUDIT_ENTRIES.clear()

    result = reconcile_ai_with_policy(
        context=context,
        deterministic_decision=deterministic_decision,
        advisor=advisor,
        audit_logger=test_audit_logger,
    )

    assert result.result == "disagreement"

    # AI may indicate that historical evidence influenced its
    # recommendation, but historical values must come from
    # trusted DunnFlow context.
    assert result.learning_influence["used"] is True
    assert (
        result.learning_influence["signal"]
        == "historically_unfavorable"
    )
    assert result.learning_influence["sample_size"] == 5
    assert result.learning_influence["confidence"] == 0.5
    assert (
        result.learning_influence["historical_recovery_rate"]
        == 0.0
    )

    result_dict = result.to_dict()

    assert "learning_influence" in result_dict
    assert (
        result_dict["learning_influence"]
        == result.learning_influence
    )

    # AI disagreement must never change deterministic authority.
    assert (
        deterministic_decision["action_type"]
        == "payment_method_update"
    )

    # Audit still records the deterministic action.
    assert len(AUDIT_ENTRIES) == 1
    assert AUDIT_ENTRIES[0]["stage"] == "ai_policy_check"
    assert AUDIT_ENTRIES[0]["result"] == "disagreement"
    assert (
        AUDIT_ENTRIES[0]["action_taken"]
        == "payment_method_update"
    )


def test_ai_learning_influence_backward_compatible() -> None:
    """Older AI responses without learning metadata remain valid."""

    context = make_context()

    deterministic_decision = {
        "invoice_id": "test_invoice",
        "action_type": "payment_method_update",
        "decision": "scheduled",
    }

    # Existing make_advisor() intentionally returns the old
    # six-field AI response without learning_influence.
    result = reconcile_ai_with_policy(
        context=context,
        deterministic_decision=deterministic_decision,
        advisor=make_advisor("payment_method_update"),
        audit_logger=test_audit_logger,
    )

    assert result.result == "agreement"
    assert isinstance(result.learning_influence, dict)

    assert "used" in result.learning_influence
    assert "signal" in result.learning_influence
    assert "sample_size" in result.learning_influence
    assert "confidence" in result.learning_influence
    assert "historical_recovery_rate" in result.learning_influence


def test_ai_unavailable_learning_influence_is_safe() -> None:
    """AI unavailable must expose the bounded safe learning state."""

    context = make_context()

    deterministic_decision = {
        "invoice_id": "test_invoice",
        "action_type": "payment_method_update",
        "decision": "scheduled",
    }

    class UnavailableAdvisor(RecoveryAdvisor):

        def __init__(self):
            pass

        def safe_generate(
            self,
            system_prompt: str,
            user_prompt: str,
        ):
            from backend.ai.recovery_advisor import AIUnavailableResult

            return AIUnavailableResult(
                reason="controlled test"
            )

    result = reconcile_ai_with_policy(
        context=context,
        deterministic_decision=deterministic_decision,
        advisor=UnavailableAdvisor(),
        audit_logger=test_audit_logger,
    )

    assert result.result == "ai_unavailable"

    assert result.learning_influence == {
        "used": False,
        "signal": "historical_context_unavailable",
        "sample_size": 0,
        "confidence": 0.0,
        "historical_recovery_rate": None,
    }

    assert (
        deterministic_decision["action_type"]
        == "payment_method_update"
    )

if __name__ == "__main__":
    tests = [
        test_ai_agrees_with_policy,
        test_ai_disagreement_cannot_override_policy,
        test_ai_agreement_does_not_authorize_execution,
        test_ai_learning_influence_is_observable,
        test_ai_learning_influence_backward_compatible,
        test_ai_unavailable_learning_influence_is_safe,
    ]

    for test in tests:
        test()
        print(f"PASS: {test.__name__}")

    print()
    print("ALL AI-POLICY RECONCILIATION TESTS PASSED")
