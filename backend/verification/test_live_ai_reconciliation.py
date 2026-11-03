from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.ai.recovery_advisor as advisor_module

from backend.ai.recovery_advisor import (
    AIConfig,
    AIRecoveryRecommendation,
    AIUnavailableResult,
    RecoveryAdvisor,
)
from backend.ai.recovery_context import RecoveryContext
from backend.ai.ai_policy_reconciliation import reconcile_ai_with_policy


# --------------------------------------------------
# TEST CONFIGURATION
# --------------------------------------------------

SCENARIOS = [
    {
        "name": "Insufficient funds",
        "category": "insufficient_funds",
        "raw_code": "insufficient_fund",
        "expected": "retry_payment",
    },
    {
        "name": "Bank timeout",
        "category": "bank_timeout",
        "raw_code": "payment_timed_out",
        "expected": "auto_retry_same_card",
    },
    {
        "name": "Authentication failure",
        "category": "auth_failed",
        "raw_code": "authentication_failed",
        "expected": "customer_action",
    },
    {
        "name": "Expired card",
        "category": "card_expired",
        "raw_code": "card_expired",
        "expected": "payment_method_update",
    },
]

print("=" * 76)
print("DUNNFLOW — LIVE NVIDIA AI-POLICY RECONCILIATION")
print("=" * 76)

config = AIConfig.from_environment()

if config.provider != "nvidia":
    raise SystemExit("STOP: NVIDIA is not configured.")

if config.model != "nvidia/nemotron-3.5-super-vl-120b-a12b":
    raise SystemExit("STOP: Unexpected NVIDIA model.")

if not config.enabled or not config.api_key:
    raise SystemExit("STOP: NVIDIA configuration incomplete.")

advisor = RecoveryAdvisor(config=config)

if not advisor.available:
    raise SystemExit("STOP: NVIDIA advisor unavailable.")

print("Provider:", config.provider)
print("Model:", config.model)
print("Advisor available:", advisor.available)


# --------------------------------------------------
# PREVENT DATABASE HISTORICAL LOOKUPS
# --------------------------------------------------

original_history_builder = (
    advisor_module.get_historical_decision_context_dict
)

advisor_module.get_historical_decision_context_dict = (
    lambda invoice_id, limit=20: {
        "learning_signal": "synthetic_no_history",
        "available": False,
    }
)


def make_context(scenario, index):
    return RecoveryContext(
        invoice={
            "invoice_id": f"synthetic_reconciliation_{index}",
            "batch_id": "synthetic_reconciliation_batch",
            "status": "issued",
            "amount": 29900,
            "currency": "INR",
        },
        subscription={
            "subscription_id": f"synthetic_subscription_{index}",
            "status": "pending",
            "retry_count": 0,
        },
        customer={
            "customer_id": "synthetic_customer",
        },
        failure_category=scenario["category"],
        raw_gateway_error=scenario["raw_code"],
        failure_reason="Synthetic reconciliation test",
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


results = []
cached_recommendation = None

try:

    # --------------------------------------------------
    # FOUR LIVE RECONCILIATION TESTS
    # --------------------------------------------------

    for index, scenario in enumerate(SCENARIOS, start=1):

        print("\n" + "-" * 76)
        print(f"SCENARIO {index}: {scenario['name']}")
        print("-" * 76)

        context = make_context(scenario, index)

        deterministic_decision = {
            "action_type": scenario["expected"],
            "reason": "Synthetic deterministic policy decision",
        }

        original_decision = dict(deterministic_decision)
        audit_events = []

        result = reconcile_ai_with_policy(
            context=context,
            deterministic_decision=deterministic_decision,
            advisor=advisor,
            audit_logger=audit_events.append,
        )

        print("AI action:", result.ai_action)
        print("Deterministic action:", result.deterministic_action)
        print("Reconciliation:", result.result)

        if result.ai_available and result.ai_action == scenario["expected"]:
            print("AI ACTION AGREEMENT: PASS")
            action_match = True
        else:
            print("AI ACTION AGREEMENT: MISMATCH")
            action_match = False

        decision_unchanged = (
            deterministic_decision == original_decision
            and result.deterministic_action == original_decision["action_type"]
        )

        print(
            "Deterministic decision preserved:",
            "PASS" if decision_unchanged else "FAIL",
        )

        audit_valid = (
            len(audit_events) == 1
            and audit_events[0]["action_taken"] == scenario["expected"]
            and audit_events[0]["stage"] == "ai_policy_check"
        )

        print(
            "In-memory audit event:",
            "PASS" if audit_valid else "FAIL",
        )

        if index == 1 and result.ai_available:
            cached_recommendation = AIRecoveryRecommendation(
                priority_score=65,
                urgency="normal",
                recommended_action=result.ai_action,
                confidence=0.8,
                reason="Cached live NVIDIA recommendation",
                customer_strategy="Advisory only",
                learning_influence={},
            )

        results.append({
            "name": scenario["name"],
            "agreement": action_match,
            "preserved": decision_unchanged,
            "audit": audit_valid,
            "available": result.ai_available,
        })


    # --------------------------------------------------
    # INTENTIONAL DISAGREEMENT TEST
    # No additional NVIDIA request needed.
    # --------------------------------------------------

    print("\n" + "=" * 76)
    print("INTENTIONAL AI-POLICY DISAGREEMENT TEST")
    print("=" * 76)

    if cached_recommendation is None:
        print("SKIPPED: No valid live recommendation available to reuse.")
        disagreement_pass = False

    else:

        class CachedAdvisor:
            def recommend(self, context):
                return cached_recommendation

        context = make_context(SCENARIOS[0], 99)

        # Deliberately different from the cached AI action.
        deterministic_decision = {
            "action_type": "manual_review",
            "reason": "Synthetic disagreement test",
        }

        original_decision = dict(deterministic_decision)
        audit_events = []

        disagreement = reconcile_ai_with_policy(
            context=context,
            deterministic_decision=deterministic_decision,
            advisor=CachedAdvisor(),
            audit_logger=audit_events.append,
        )

        disagreement_pass = (
            disagreement.result == "disagreement"
            and deterministic_decision == original_decision
            and disagreement.deterministic_action == "manual_review"
            and len(audit_events) == 1
            and audit_events[0]["action_taken"] == "manual_review"
        )

        print("AI recommendation:", disagreement.ai_action)
        print("Deterministic decision:", disagreement.deterministic_action)
        print("Reconciliation result:", disagreement.result)
        print(
            "Deterministic authority preserved:",
            "PASS" if disagreement_pass else "FAIL",
        )


finally:
    # Restore original function even if a test fails.
    advisor_module.get_historical_decision_context_dict = (
        original_history_builder
    )


# --------------------------------------------------
# FINAL REPORT
# --------------------------------------------------

print("\n" + "=" * 76)
print("FINAL RECONCILIATION REPORT")
print("=" * 76)

for item in results:
    print(
        f"{item['name']:<27} "
        f"Agreement={'PASS' if item['agreement'] else 'FAIL':<5} "
        f"Policy={'PASS' if item['preserved'] else 'FAIL':<5} "
        f"Audit={'PASS' if item['audit'] else 'FAIL':<5} "
        f"Available={item['available']}"
    )

agreement_count = sum(r["agreement"] for r in results)
preserved_count = sum(r["preserved"] for r in results)
audit_count = sum(r["audit"] for r in results)

total_checks = (
    len(SCENARIOS) * 3
    + 1
)

passed_checks = (
    agreement_count
    + preserved_count
    + audit_count
    + int(disagreement_pass)
)

print("-" * 76)
print("Live scenario agreement:", agreement_count, "/", len(SCENARIOS))
print("Deterministic preservation:", preserved_count, "/", len(SCENARIOS))
print("Audit validation:", audit_count, "/", len(SCENARIOS))
print("Forced disagreement:", "PASS" if disagreement_pass else "FAIL")
print("TOTAL CHECKS:", total_checks)
print("PASSED:", passed_checks)
print("FAILED:", total_checks - passed_checks)

print("=" * 76)
print("Database writes: NONE")
print("Payment execution: NONE")
print("Scheduler calls: NONE")
print("Razorpay calls: NONE")
print("=" * 76)

sys.exit(0 if passed_checks == total_checks else 1)
