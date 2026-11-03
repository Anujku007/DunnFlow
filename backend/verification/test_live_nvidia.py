from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai.recovery_advisor import (
    AIConfig,
    AIUnavailableResult,
    AIRecoveryRecommendation,
    RecoveryAdvisor,
)
from backend.ai.recovery_context import RecoveryContext


EXPECTED_PROVIDER = "nvidia"
EXPECTED_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"

print("=" * 72)
print("DUNNFLOW — LIVE NVIDIA ADVISORY TEST")
print("=" * 72)

# --------------------------------------------------
# 1. Verify configuration without revealing API key
# --------------------------------------------------

config = AIConfig.from_environment()

print("\n[1] Configuration")
print("Provider:", config.provider)
print("Model:", config.model)
print("Enabled:", config.enabled)
print("API key configured:", bool(config.api_key))
print("Timeout:", config.timeout_seconds)

if config.provider != EXPECTED_PROVIDER:
    raise SystemExit("STOP: Configured provider is not NVIDIA.")

if config.model != EXPECTED_MODEL:
    raise SystemExit("STOP: Configured model does not match expected model.")

if not config.enabled or not config.api_key:
    raise SystemExit("STOP: NVIDIA is not enabled or API key is missing.")

# --------------------------------------------------
# 2. Build entirely synthetic in-memory context
# IMPORTANT: invoice has NO invoice_id
# --------------------------------------------------

context = RecoveryContext(
    invoice={
        "batch_id": "nvidia_offline_synthetic_batch",
        "status": "issued",
        "amount": 29900,
        "currency": "INR",
    },
    subscription={
        "subscription_id": "synthetic_subscription_001",
        "status": "pending",
        "retry_count": 0,
    },
    customer={
        "customer_id": "synthetic_customer_001",
    },
    failure_category="insufficient_funds",
    raw_gateway_error="insufficient_fund",
    failure_reason="Synthetic insufficient funds scenario",
    invoice_amount=29900,
    payment_attempts=[
        {
            "attempt_type": "initial_charge",
            "result": "failed",
            "error_code": "insufficient_fund",
        }
    ],
    recovery_actions=[],
    retry_count=0,
    time_since_previous_retry_seconds=None,
    previous_recovery_actions=[],
    invoice_status="issued",
    customer_action_history=[],
    revenue_events=[],
    audit_history=[],
)

assert "invoice_id" not in context.invoice

print("\n[2] Synthetic context")
print("Failure category:", context.failure_category)
print("Raw gateway error:", context.raw_gateway_error)
print("Invoice amount: INR 299.00")
print("Invoice ID present:", "invoice_id" in context.invoice)
print("Database historical lookup: skipped")

# --------------------------------------------------
# 3. Initialize real NVIDIA provider
# --------------------------------------------------

print("\n[3] Initializing NVIDIA advisor")

advisor = RecoveryAdvisor(config=config)

if not advisor.available:
    raise SystemExit("STOP: NVIDIA advisor is not available.")

print("Advisor available:", advisor.available)

# --------------------------------------------------
# 4. Make one live recommendation request
# --------------------------------------------------

print("\n[4] Sending one live request to NVIDIA...")
print("No payment execution or scheduling will occur.")

result = advisor.recommend(context)

# --------------------------------------------------
# 5. Inspect response
# --------------------------------------------------

print("\n[5] NVIDIA response")

if isinstance(result, AIUnavailableResult):
    print("RESULT: AI UNAVAILABLE")
    print("Reason:", result.reason)
    raise SystemExit(2)

if not isinstance(result, AIRecoveryRecommendation):
    raise SystemExit(
        "FAIL: Unexpected response type: " + type(result).__name__
    )

allowed_actions = {
    "retry_payment",
    "auto_retry_same_card",
    "customer_action",
    "payment_method_update",
    "manual_review",
    "no_action",
}

print("Priority score:", result.priority_score)
print("Urgency:", result.urgency)
print("Recommended action:", result.recommended_action)
print("Confidence:", result.confidence)
print("Reason:", result.reason)
print("Customer strategy:", result.customer_strategy)

print(
    "Learning influence:",
    json.dumps(result.learning_influence, indent=2, default=str),
)

if result.recommended_action not in allowed_actions:
    raise SystemExit("FAIL: Unsupported action returned.")

if not 0 <= result.priority_score <= 100:
    raise SystemExit("FAIL: Invalid priority score.")

if result.urgency not in {"low", "normal", "high"}:
    raise SystemExit("FAIL: Invalid urgency.")

if not 0 <= result.confidence <= 1:
    raise SystemExit("FAIL: Invalid confidence.")

print("\n" + "=" * 72)
print("PASS: LIVE NVIDIA RECOMMENDATION VALIDATED")
print("=" * 72)
print("Provider:", config.provider)
print("Model:", config.model)
print("Recommendation:", result.recommended_action)
print("Financial authority: deterministic DunnFlow policy")
print("Payment execution: NOT PERFORMED")
print("Database writes: NOT PERFORMED")
