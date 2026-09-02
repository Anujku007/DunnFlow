from backend.ai.recovery_advisor import (
    AIConfig,
    AIProvider,
    AIProviderError,
    AIRecoveryRecommendation,
    AIUnavailableResult,
    RecoveryAdvisor,
)
from backend.ai.recovery_context import RecoveryContext


class MockProvider(AIProvider):
    def __init__(
        self,
        response: str | None = None,
        error: Exception | None = None,
    ):
        self.response = response
        self.error = error

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        if self.error is not None:
            raise self.error

        return self.response or ""


def make_context() -> RecoveryContext:
    return RecoveryContext(
        invoice={
            "invoice_id": "test_invoice",
            "status": "issued",
            "amount": 99900,
        },
        subscription={
            "subscription_id": "test_subscription",
            "status": "pending",
        },
        customer={
            "customer_id": "test_customer",
            "customer_name": "Test Customer",
            "customer_email": "test@example.com",
        },
        failure_category="insufficient_funds",
        raw_gateway_error="insufficient_fund",
        failure_reason="Insufficient funds",
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



VALID_RESPONSE = """
{
    "priority_score": 80,
    "urgency": "high",
    "recommended_action": "retry_payment",
    "confidence": 0.9,
    "reason": "A delayed retry is appropriate for insufficient funds.",
    "customer_strategy": "Ask the customer to ensure sufficient balance."
}
""".strip()


def make_advisor(response: str | None = None, error=None) -> RecoveryAdvisor:
    config = AIConfig(
        provider="test",
        api_key="test",
        model="test-model",
        enabled=True,
        timeout_seconds=5,
    )

    provider = MockProvider(
        response=response,
        error=error,
    )

    return RecoveryAdvisor(
        config=config,
        provider=provider,
    )


def assert_rejected(response: str, expected_message: str) -> None:
    result = make_advisor(
        response=response
    ).recommend(make_context())

    assert isinstance(
        result,
        AIUnavailableResult,
    ), (
        "Expected unsafe AI output to return "
        "AIUnavailableResult."
    )

    assert expected_message in result.reason, (
        f"Expected '{expected_message}' in fallback reason, "
        f"got '{result.reason}'"
    )



def test_valid_recommendation():
    result = make_advisor(
        response=VALID_RESPONSE
    ).recommend(make_context())

    assert isinstance(
        result,
        AIRecoveryRecommendation,
    )

    assert result.priority_score == 80
    assert result.urgency == "high"
    assert result.recommended_action == "retry_payment"
    assert result.confidence == 0.9


def test_invalid_json():
    assert_rejected(
        "not json",
        "AI response was not valid JSON.",
    )


def test_missing_required_field():
    response = """
    {
        "priority_score": 80,
        "urgency": "high",
        "recommended_action": "retry_payment",
        "confidence": 0.9,
        "reason": "Test"
    }
    """

    assert_rejected(
        response,
        "missing required fields",
    )


def test_invalid_action():
    response = VALID_RESPONSE.replace(
        '"retry_payment"',
        '"delete_customer"',
    )

    assert_rejected(
        response,
        "not a valid DunnFlow action",
    )


def test_priority_below_zero():
    response = VALID_RESPONSE.replace(
        '"priority_score": 80',
        '"priority_score": -1',
    )

    assert_rejected(
        response,
        "between 0 and 100",
    )


def test_priority_above_100():
    response = VALID_RESPONSE.replace(
        '"priority_score": 80',
        '"priority_score": 101',
    )

    assert_rejected(
        response,
        "between 0 and 100",
    )


def test_priority_wrong_type():
    response = VALID_RESPONSE.replace(
        '"priority_score": 80',
        '"priority_score": "80"',
    )

    assert_rejected(
        response,
        "priority_score must be an integer",
    )


def test_confidence_below_zero():
    response = VALID_RESPONSE.replace(
        '"confidence": 0.9',
        '"confidence": -0.1',
    )

    assert_rejected(
        response,
        "between 0.0 and 1.0",
    )


def test_confidence_above_one():
    response = VALID_RESPONSE.replace(
        '"confidence": 0.9',
        '"confidence": 1.1',
    )

    assert_rejected(
        response,
        "between 0.0 and 1.0",
    )


def test_invalid_urgency():
    response = VALID_RESPONSE.replace(
        '"high"',
        '"critical"',
    )

    assert_rejected(
        response,
        "urgency must be one of",
    )


def test_empty_reason():
    response = VALID_RESPONSE.replace(
        '"reason": "A delayed retry is appropriate for insufficient funds."',
        '"reason": ""',
    )

    assert_rejected(
        response,
        "reason must be a non-empty string",
    )


def test_empty_customer_strategy():
    response = VALID_RESPONSE.replace(
        '"customer_strategy": "Ask the customer to ensure sufficient balance."',
        '"customer_strategy": ""',
    )

    assert_rejected(
        response,
        "customer_strategy must be a non-empty string",
    )


def test_empty_response_safe_fallback():
    result = make_advisor(
        response=""
    ).safe_generate(
        system_prompt="test",
        user_prompt="test",
    )

    assert isinstance(
        result,
        AIUnavailableResult,
    )

    assert result.available is False
    assert result.fallback_required is True


def test_timeout_safe_fallback():
    """Provider timeout must fail closed into AIUnavailableResult."""

    class TimeoutProvider(AIProvider):
        def generate(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
        ) -> str:
            raise AIProviderError(
                "OpenRouter request failed: request timed out."
            )

    advisor = RecoveryAdvisor(
        config=AIConfig(
            provider="test",
            api_key="test",
            model="test-model",
            enabled=True,
            timeout_seconds=5,
        ),
        provider=TimeoutProvider(),
    )

    result = advisor.recommend(make_context())

    assert isinstance(result, AIUnavailableResult)
    assert result.available is False
    assert result.fallback_required is True
    assert "timed out" in result.reason.lower()


def test_rate_limit_safe_fallback():
    """Provider rate-limit failure must fail closed into AIUnavailableResult."""

    class RateLimitProvider(AIProvider):
        def generate(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
        ) -> str:
            raise AIProviderError(
                "OpenRouter request failed: rate limit exceeded."
            )

    advisor = RecoveryAdvisor(
        config=AIConfig(
            provider="test",
            api_key="test",
            model="test-model",
            enabled=True,
            timeout_seconds=5,
        ),
        provider=RateLimitProvider(),
    )

    result = advisor.recommend(make_context())

    assert isinstance(result, AIUnavailableResult)
    assert result.available is False
    assert result.fallback_required is True
    assert "rate limit" in result.reason.lower()


def test_provider_failure_safe_fallback():
    result = make_advisor(
        error=AIProviderError("simulated provider failure")
    ).safe_generate(
        system_prompt="test",
        user_prompt="test",
    )

    assert isinstance(
        result,
        AIUnavailableResult,
    )

    assert result.available is False
    assert result.fallback_required is True


if __name__ == "__main__":
    tests = [
        test_valid_recommendation,
        test_invalid_json,
        test_missing_required_field,
        test_invalid_action,
        test_priority_below_zero,
        test_priority_above_100,
        test_priority_wrong_type,
        test_confidence_below_zero,
        test_confidence_above_one,
        test_invalid_urgency,
        test_empty_reason,
        test_empty_customer_strategy,
        test_empty_response_safe_fallback,
        test_provider_failure_safe_fallback,
        test_timeout_safe_fallback,
        test_rate_limit_safe_fallback,
    ]

    for test in tests:
        test()
        print(f"PASS: {test.__name__}")

    print(f"\nALL {len(tests)} AI SAFETY TESTS PASSED")
