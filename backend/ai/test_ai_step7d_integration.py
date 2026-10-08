import json

from backend.ai.recovery_advisor import (
    RecoveryAdvisor,
    AIRecoveryRecommendation,
)
from backend.ai.recovery_context import build_recovery_context


INVOICE_ID = "inv_dunnflow_051"


class CaptureAIProvider:
    def __init__(self):
        self.system_prompt = None
        self.user_prompt = None

    def generate(self, system_prompt, user_prompt):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt

        # Deliberately attempt to fabricate historical learning metadata.
        return json.dumps({
            "priority_score": 70,
            "urgency": "high",
            "recommended_action": "retry_payment",
            "confidence": 0.80,
            "reason": (
                "Historical evidence was considered, "
                "but deterministic policy remains authoritative."
            ),
            "customer_strategy": "Use a controlled recovery path.",
            "learning_influence": {
                "used": True,
                "signal": "historically_favorable",
                "sample_size": 9999,
                "confidence": 1.0,
                "historical_recovery_rate": 1.0,
                "ai_action_feedback": {
                    "available": True,
                    "actions": {
                        "retry_payment": {
                            "total_cases": 9999,
                            "recovered_cases": 9999,
                            "recovery_rate": 1.0,
                            "agreement_cases": 9999,
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
print("STEP 7D.6 — REAL PROMPT INTEGRATION GATE")
print("=" * 80)

provider = CaptureAIProvider()
advisor = RecoveryAdvisor(provider=provider)

context = build_recovery_context(INVOICE_ID)

result = advisor.recommend(context)

assert isinstance(result, AIRecoveryRecommendation)

print("1. REAL ADVISOR EXECUTION: PASS")


# -------------------------------------------------------------------------
# 2. Historical decision context must reach the actual model prompt.
# -------------------------------------------------------------------------

assert provider.user_prompt is not None

assert "historical_decision_context" in provider.user_prompt
assert "historically_unfavorable" in provider.user_prompt
assert "sample_size" in provider.user_prompt
assert "confidence" in provider.user_prompt
assert "historical_recovery_rate" in provider.user_prompt

print("2. HISTORICAL DECISION CONTEXT REACHED PROMPT: PASS")


# -------------------------------------------------------------------------
# 3. New 7D reasoning instructions must reach the model.
# -------------------------------------------------------------------------

assert provider.system_prompt is not None

assert "Historical AI-action feedback" in provider.system_prompt
assert "causal proof" in provider.system_prompt
assert "blindly copy" in provider.system_prompt
assert "execution instruction" in provider.system_prompt
assert "override deterministic policy" in provider.system_prompt
assert 'financial_authority = "deterministic_policy"' in provider.system_prompt

print("3. AI REASONING GUARDRAILS REACHED MODEL: PASS")


# -------------------------------------------------------------------------
# 4. Trusted DunnFlow historical values must win over fake AI values.
# -------------------------------------------------------------------------

learning = result.learning_influence

print(
    "Learning influence:",
    json.dumps(learning, indent=2),
)

assert learning["signal"] == "historically_unfavorable"
assert learning["sample_size"] == 11
assert learning["confidence"] == 0.61
assert learning["historical_recovery_rate"] == 0.0

print("4. TRUSTED HISTORICAL VALUES: PASS")


# -------------------------------------------------------------------------
# 5. Trusted AI-action feedback must win over fake AI values.
# -------------------------------------------------------------------------

feedback = learning["ai_action_feedback"]

assert feedback["available"] is True
assert feedback["advisory_only"] is True

retry = feedback["actions"]["retry_payment"]

assert retry["total_cases"] == 1
assert retry["recovered_cases"] == 0
assert retry["recovery_rate"] == 0.0
assert retry["agreement_cases"] == 0
assert retry["disagreement_cases"] == 1

assert retry["attribution"] == "advisory_correlation"
assert retry["episode_granularity"] == "invoice"
assert retry["financial_authority"] == "deterministic_policy"

# Explicitly prove the AI's fake values were not trusted.
assert retry["total_cases"] != 9999
assert retry["recovered_cases"] != 9999
assert retry["recovery_rate"] != 1.0
assert retry["attribution"] != "ai_caused_recovery"
assert retry["episode_granularity"] != "audit_row"
assert retry["financial_authority"] != "ai"

print("5. AI HISTORICAL FABRICATION BLOCKED: PASS")


# -------------------------------------------------------------------------
# 6. Advisory-only authority must remain explicit.
# -------------------------------------------------------------------------

assert feedback["advisory_only"] is True
assert retry["financial_authority"] == "deterministic_policy"

print("6. ADVISORY-ONLY AUTHORITY: PASS")


# -------------------------------------------------------------------------
# 7. Recommendation remains serializable.
# -------------------------------------------------------------------------

serialized = result.to_dict()

json.dumps(serialized)

assert "learning_influence" in serialized
assert "ai_action_feedback" in serialized["learning_influence"]

print("7. SERIALIZATION: PASS")


print()
print("=" * 80)
print("STEP 7D.6 RESULTS")
print("=" * 80)

print("REAL ADVISOR EXECUTION: VERIFIED")
print("HISTORICAL DECISION CONTEXT REACHED PROMPT: VERIFIED")
print("AI REASONING GUARDRAILS: VERIFIED")
print("TRUSTED HISTORICAL VALUES: VERIFIED")
print("AI FABRICATION BLOCKED: VERIFIED")
print("ADVISORY-ONLY AUTHORITY: VERIFIED")
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
print("STEP 7D CLOSED/PASS")
print("=" * 80)
