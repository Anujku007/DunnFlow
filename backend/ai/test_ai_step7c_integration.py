import json

from backend.ai.historical_decision_context import (
    get_historical_decision_context_dict,
)
from backend.ai.recovery_context import build_recovery_context
from backend.ai.recovery_advisor import RecoveryAdvisor


INVOICE_ID = "inv_dunnflow_051"


class FakeAIProvider:
    def generate(self, system_prompt, user_prompt):
        # Deliberately attempt to inject fake historical statistics.
        return json.dumps({
            "priority_score": 75,
            "urgency": "high",
            "recommended_action": "retry_payment",
            "confidence": 0.85,
            "reason": "Test recommendation using historical evidence.",
            "customer_strategy": "Retry payment using a controlled path.",
            "learning_influence": {
                "used": True,
                "signal": "historically_favorable",
                "sample_size": 999,
                "confidence": 0.99,
                "historical_recovery_rate": 0.99,
                "ai_action_feedback": {
                    "available": True,
                    "actions": {
                        "retry_payment": {
                            "total_cases": 999,
                            "recovered_cases": 999,
                            "recovery_rate": 1.0,
                            "agreement_cases": 999,
                            "disagreement_cases": 0,
                            "attribution": "ai_caused_recovery",
                            "episode_granularity": "audit_row",
                            "financial_authority": "ai",
                        }
                    },
                    "advisory_only": False,
                },
            },
        })


print("=" * 80)
print("STEP 7C — REAL CONTEXT INTEGRATION GATE")
print("=" * 80)

# -------------------------------------------------------------------------
# 1. Build real historical context
# -------------------------------------------------------------------------

historical = get_historical_decision_context_dict(
    INVOICE_ID,
    limit=20,
)

print(f"Invoice: {INVOICE_ID}")
print(
    "Historical cases:",
    historical.get("similar_case_count"),
)

raw_ai_stats = historical.get(
    "ai_action_statistics",
    {},
)

print(
    "Historical AI-action statistics:",
    json.dumps(raw_ai_stats, indent=2),
)

assert isinstance(raw_ai_stats, dict)

# inv_dunnflow_051 is a real card_expired cohort member.
# Its historical feedback should contain the retry_payment episode.
assert "retry_payment" in raw_ai_stats, (
    "Expected retry_payment historical feedback "
    "for inv_dunnflow_051"
)

retry_stats = raw_ai_stats["retry_payment"]

assert retry_stats["total_cases"] == 1
assert retry_stats["recovered_cases"] == 0
assert retry_stats["recovery_rate"] == 0.0
assert retry_stats["agreement_cases"] == 0
assert retry_stats["disagreement_cases"] == 1
assert retry_stats["attribution"] == "advisory_correlation"
assert retry_stats["episode_granularity"] == "invoice"
assert retry_stats["financial_authority"] == "deterministic_policy"

print("1. REAL HISTORICAL FEEDBACK: PASS")


# -------------------------------------------------------------------------
# 2. Build real RecoveryContext
# -------------------------------------------------------------------------

context = build_recovery_context(INVOICE_ID)

assert context.invoice["invoice_id"] == INVOICE_ID

print("2. REAL RECOVERY CONTEXT: PASS")


# -------------------------------------------------------------------------
# 3. Run RecoveryAdvisor with controlled AI provider
# -------------------------------------------------------------------------

advisor = RecoveryAdvisor(
    provider=FakeAIProvider()
)

result = advisor.recommend(context)

assert result is not None

print(
    "AI recommended action:",
    result.recommended_action,
)

print(
    "Learning influence:",
    json.dumps(
        result.learning_influence,
        indent=2,
    ),
)


# -------------------------------------------------------------------------
# 4. Verify trusted historical learning signal
# -------------------------------------------------------------------------

learning = result.learning_influence

assert learning["signal"] == historical["learning_signal"]["signal"]
assert learning["sample_size"] == historical["learning_signal"]["sample_size"]
assert learning["confidence"] == historical["learning_signal"]["confidence"]
assert (
    learning["historical_recovery_rate"]
    == historical["learning_signal"]["historical_recovery_rate"]
)

print("3. TRUSTED LEARNING SIGNAL: PASS")


# -------------------------------------------------------------------------
# 5. Verify AI-action feedback was actually exposed
# -------------------------------------------------------------------------

feedback = learning.get(
    "ai_action_feedback"
)

assert isinstance(feedback, dict)

assert feedback["available"] is True
assert feedback["advisory_only"] is True

actions = feedback["actions"]

assert "retry_payment" in actions

trusted_retry = actions["retry_payment"]

assert trusted_retry["total_cases"] == 1
assert trusted_retry["recovered_cases"] == 0
assert trusted_retry["recovery_rate"] == 0.0
assert trusted_retry["agreement_cases"] == 0
assert trusted_retry["disagreement_cases"] == 1

assert (
    trusted_retry["attribution"]
    == "advisory_correlation"
)

assert (
    trusted_retry["episode_granularity"]
    == "invoice"
)

assert (
    trusted_retry["financial_authority"]
    == "deterministic_policy"
)

print("4. AI-ACTION HISTORICAL FEEDBACK EXPOSED: PASS")


# -------------------------------------------------------------------------
# 6. Verify AI cannot fabricate historical statistics
# -------------------------------------------------------------------------

assert trusted_retry["total_cases"] != 999
assert trusted_retry["recovered_cases"] != 999
assert trusted_retry["recovery_rate"] != 1.0
assert trusted_retry["attribution"] != "ai_caused_recovery"
assert trusted_retry["episode_granularity"] != "audit_row"
assert trusted_retry["financial_authority"] != "ai"

print("5. AI FABRICATION RESISTANCE: PASS")


# -------------------------------------------------------------------------
# 7. Verify serialization
# -------------------------------------------------------------------------

serialized = result.to_dict()

json.dumps(serialized)

assert "learning_influence" in serialized
assert "ai_action_feedback" in serialized["learning_influence"]

print("6. RECOMMENDATION SERIALIZATION: PASS")


# -------------------------------------------------------------------------
# FINAL SAFETY GATE
# -------------------------------------------------------------------------

print()
print("=" * 80)
print("STEP 7C RESULTS")
print("=" * 80)

print("REAL HISTORICAL CONTEXT: VERIFIED")
print("AI-ACTION FEEDBACK: VERIFIED")
print("BOUNDED FEEDBACK: VERIFIED")
print("TRUSTED DUNNFLOW VALUES: VERIFIED")
print("AI FABRICATION BLOCKED: VERIFIED")
print("ADVISORY-ONLY ATTRIBUTION: VERIFIED")
print("DETERMINISTIC AUTHORITY: VERIFIED")
print("SERIALIZATION: VERIFIED")

print()
print("NO PAYMENT.")
print("NO RAZORPAY API CALL.")
print("NO RECOVERY ACTION.")
print("NO WEBHOOK.")
print("NO DETERMINISTIC DECISION CHANGE.")
print("NO DATABASE WRITE.")
print("NO DATABASE SCHEMA CHANGE.")
print()
print("STEP 7C CLOSED/PASS")
print("=" * 80)
