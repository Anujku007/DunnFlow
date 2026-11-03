from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai.recovery_advisor import (
    AIConfig,
    AIUnavailableResult,
    RecoveryAdvisor,
)
from backend.ai.recovery_context import RecoveryContext
from backend.modules.diagnosis import classify


SCENARIOS = [
    {
        "name": "Bank timeout",
        "raw_code": "payment_timed_out",
        "expected_category": "bank_timeout",
        "expected_actions": {"auto_retry_same_card"},
    },
    {
        "name": "Authentication failure",
        "raw_code": "authentication_failed",
        "expected_category": "auth_failed",
        "expected_actions": {"customer_action"},
    },
    {
        "name": "Expired card",
        "raw_code": "card_expired",
        "expected_category": "card_expired",
        "expected_actions": {"payment_method_update"},
    },
    {
        "name": "Unknown gateway error",
        "raw_code": "unknown_gateway_code",
        "expected_category": "unclassified",
        "expected_actions": {"manual_review", "no_action"},
    },
]

EXPECTED_PROVIDER = "nvidia"
EXPECTED_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"

print("=" * 76)
print("DUNNFLOW — NVIDIA MULTI-SCENARIO EVALUATION")
print("=" * 76)

# --------------------------------------------------
# 1. Verify provider configuration
# --------------------------------------------------

config = AIConfig.from_environment()

print("\nPROVIDER CONFIGURATION")
print("Provider:", config.provider)
print("Model:", config.model)
print("Enabled:", config.enabled)
print("API key configured:", bool(config.api_key))

if config.provider != EXPECTED_PROVIDER:
    raise SystemExit("STOP: NVIDIA is not the configured provider.")

if config.model != EXPECTED_MODEL:
    raise SystemExit("STOP: Unexpected NVIDIA model.")

if not config.enabled or not config.api_key:
    raise SystemExit("STOP: NVIDIA configuration is incomplete.")

advisor = RecoveryAdvisor(config=config)

if not advisor.available:
    raise SystemExit("STOP: NVIDIA advisor is unavailable.")

# --------------------------------------------------
# 2. Build synthetic context for each scenario
# --------------------------------------------------

def make_context(raw_code, category):
    return RecoveryContext(
        invoice={
            "batch_id": "nvidia_synthetic_evaluation",
            "status": "issued",
            "amount": 29900,
            "currency": "INR",
        },
        subscription={
            "subscription_id": "synthetic_subscription",
            "status": "pending",
            "retry_count": 0,
        },
        customer={
            "customer_id": "synthetic_customer",
        },
        failure_category=category,
        raw_gateway_error=raw_code,
        failure_reason=f"Synthetic test: {category}",
        invoice_amount=29900,
        payment_attempts=[
            {
                "attempt_type": "initial_charge",
                "result": "failed",
                "error_code": raw_code,
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


# --------------------------------------------------
# 3. Execute live requests sequentially
# --------------------------------------------------

results = []

print("\n" + "=" * 76)
print("LIVE SCENARIO RESULTS")
print("=" * 76)

for index, scenario in enumerate(SCENARIOS, start=1):

    name = scenario["name"]
    raw_code = scenario["raw_code"]
    expected_category = scenario["expected_category"]
    expected_actions = scenario["expected_actions"]

    print(f"\n[{index}/4] {name}")
    print("-" * 60)

    actual_category = classify(raw_code)

    if actual_category != expected_category:
        print("FAIL: DunnFlow diagnosis mapping mismatch.")
        print("Expected:", expected_category)
        print("Actual:", actual_category)

        results.append({
            "name": name,
            "status": "DIAGNOSIS_MISMATCH",
            "action": None,
        })
        continue

    context = make_context(raw_code, actual_category)

    # Intentionally no invoice_id: no historical DB lookup.
    assert "invoice_id" not in context.invoice

    print("Gateway code:", raw_code)
    print("Diagnosis category:", actual_category)
    print("Expected action:", " OR ".join(sorted(expected_actions)))
    print("Sending live NVIDIA request...")

    try:
        result = advisor.recommend(context)

    except Exception as exc:
        print("REQUEST ERROR:", type(exc).__name__, str(exc))

        results.append({
            "name": name,
            "status": "REQUEST_ERROR",
            "action": None,
        })
        continue

    if isinstance(result, AIUnavailableResult):
        print("AI UNAVAILABLE:", result.reason)

        results.append({
            "name": name,
            "status": "AI_UNAVAILABLE",
            "action": None,
        })
        continue

    action = result.recommended_action

    print("Actual action:", action)
    print("Priority:", result.priority_score)
    print("Urgency:", result.urgency)
    print("Confidence:", result.confidence)
    print("Reason:", result.reason)
    print("Customer strategy:", result.customer_strategy)

    if action in expected_actions:
        status = "MATCH"
        print("RESULT: MATCH")
    else:
        status = "MISMATCH"
        print("RESULT: MISMATCH")

    results.append({
        "name": name,
        "status": status,
        "action": action,
    })


# --------------------------------------------------
# 4. Evaluation summary
# --------------------------------------------------

print("\n" + "=" * 76)
print("FINAL NVIDIA EVALUATION SUMMARY")
print("=" * 76)

matches = sum(r["status"] == "MATCH" for r in results)
mismatches = sum(r["status"] == "MISMATCH" for r in results)
unavailable = sum(
    r["status"] in {"AI_UNAVAILABLE", "REQUEST_ERROR"}
    for r in results
)

for result in results:
    print(
        f'{result["name"]:<28} '
        f'{result["action"] or "N/A":<28} '
        f'{result["status"]}'
    )

print("-" * 76)
print("Total scenarios:", len(SCENARIOS))
print("Matches:", matches)
print("Mismatches:", mismatches)
print("Unavailable/errors:", unavailable)

if matches + mismatches:
    evaluated = matches + mismatches
    print(f"Action agreement: {matches}/{evaluated} ({matches / evaluated * 100:.1f}%)")

print("=" * 76)
print("Payment execution: NOT PERFORMED")
print("Database writes: NOT PERFORMED")
print("Scheduler invocation: NOT PERFORMED")
print("Razorpay calls: NOT PERFORMED")
print("=" * 76)
