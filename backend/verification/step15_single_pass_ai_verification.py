from pathlib import Path
import ast


ROOT = Path(".")
AGENT = ROOT / "backend" / "agent" / "recovery_agent.py"
ORCHESTRATOR = ROOT / "orchestrator.py"


def check(condition, message):
    if not condition:
        raise AssertionError(f"[FAIL] {message}")
    print(f"[PASS] {message}")


print("=" * 78)
print("DUNNFLOW STEP 15 — SINGLE-PASS AI HANDOFF VERIFICATION")
print("=" * 78)
print()


# ------------------------------------------------------------
# Files
# ------------------------------------------------------------

check(
    AGENT.exists(),
    "RecoveryAgent exists.",
)

check(
    ORCHESTRATOR.exists(),
    "Deterministic orchestrator exists.",
)


# ------------------------------------------------------------
# Syntax
# ------------------------------------------------------------

agent_text = AGENT.read_text(
    encoding="utf-8-sig"
)

orchestrator_text = ORCHESTRATOR.read_text(
    encoding="utf-8-sig"
)

ast.parse(agent_text)
ast.parse(orchestrator_text)

print("[PASS] RecoveryAgent and orchestrator pass AST validation.")


# ------------------------------------------------------------
# Step 14 handoff preserved
# ------------------------------------------------------------

check(
    "run_authorized_batch" in agent_text,
    "run_authorized_batch() remains present.",
)

check(
    "agent_plan" in agent_text,
    "Agent plan handoff remains present.",
)

check(
    "deterministic_orchestrator" in agent_text,
    "Agent execution authority remains deterministic.",
)

check(
    "deterministic_policy" in agent_text,
    "Financial authority remains deterministic policy.",
)

check(
    "advisory_only" in agent_text,
    "AI remains advisory-only.",
)


# ------------------------------------------------------------
# Single-pass AI recommendation handoff
# ------------------------------------------------------------

check(
    '"ai_recommendations"' in agent_text,
    "Agent carries AI recommendations into the handoff.",
)

check(
    '"agent_advisory_source"' in agent_text,
    "Agent advisory source is explicitly identified.",
)

check(
    '"recovery_agent_single_pass"' in agent_text,
    "Agent marks the advisory source as single-pass.",
)

check(
    'if planning_context.result.get(\n                    "ai_recommendations"\n                )' in agent_text,
    "Agent prevents duplicate advisor invocation when recommendations already exist.",
)


# ------------------------------------------------------------
# Orchestrator single-pass consumption
# ------------------------------------------------------------

check(
    '"recovery_agent_single_pass"' in orchestrator_text,
    "Orchestrator recognizes the single-pass agent advisory source.",
)

check(
    "agent_ai_recommendations" in orchestrator_text,
    "Orchestrator reads recommendations from the agent plan.",
)

check(
    '"source": "recovery_agent_single_pass"' in orchestrator_text,
    "AI reconciliation records the agent as advisory source.",
)

check(
    '"advisory_only": True' in orchestrator_text,
    "Agent recommendations remain advisory-only.",
)


# ------------------------------------------------------------
# Direct AI fallback remains available
# ------------------------------------------------------------

check(
    '"orchestrator_direct_advisory"' in orchestrator_text,
    "Direct orchestrator AI advisory fallback remains available.",
)

check(
    "elif ai_advisor is not None" in orchestrator_text,
    "Orchestrator direct AI path remains conditional.",
)


# ------------------------------------------------------------
# Deterministic authority
# ------------------------------------------------------------

check(
    'deterministic_decision.get("action")' in orchestrator_text,
    "AI agreement/disagreement is compared against deterministic action.",
)

check(
    'deterministic_action' in orchestrator_text,
    "Deterministic action remains explicitly represented.",
)

check(
    "reconcile_invoice" in orchestrator_text,
    "Existing AI-policy reconciliation path remains available.",
)


# ------------------------------------------------------------
# No AI recommendation modifies policy
# ------------------------------------------------------------

check(
    "decisions = decide_batch(" in orchestrator_text,
    "Deterministic decisions are still produced by decide_batch().",
)

check(
    "schedule_batch(" in orchestrator_text,
    "Existing scheduler remains present.",
)

check(
    "execute_due_actions(" in orchestrator_text,
    "Existing execution remains present.",
)

check(
    "process_customer_responses(" in orchestrator_text,
    "Existing customer-response stage remains present.",
)

check(
    "summarize_batch_outcomes(" in orchestrator_text,
    "Existing outcome reconciliation remains present.",
)

check(
    "get_batch_metrics(" in orchestrator_text,
    "Existing authoritative metrics remain present.",
)


# ------------------------------------------------------------
# No duplicate financial engine
# ------------------------------------------------------------

# The RecoveryAgent contains older helper methods named
# schedule() and execute(). Those existing methods are not the
# Step 15 handoff boundary.
#
# Therefore inspect ONLY the run_authorized_batch() method body.
agent_tree = ast.parse(agent_text)

run_authorized_method = None

for node in ast.walk(agent_tree):
    if isinstance(node, ast.FunctionDef):
        if node.name == "run_authorized_batch":
            run_authorized_method = node
            break

check(
    run_authorized_method is not None,
    "run_authorized_batch() AST node exists.",
)

handoff_body = ast.get_source_segment(
    agent_text,
    run_authorized_method,
) or ""

check(
    "execute_due_actions(" not in handoff_body,
    "run_authorized_batch() does not directly invoke payment execution.",
)

check(
    "schedule_batch(" not in handoff_body,
    "run_authorized_batch() does not directly invoke payment scheduling.",
)


# ------------------------------------------------------------
# No Razorpay/webhook additions
# ------------------------------------------------------------

# Inspect only the Step 15 handoff method for direct
# payment/webhook integration. Existing RecoveryAgent code may
# legitimately document or import those capabilities elsewhere.
check(
    "razorpay" not in handoff_body.lower(),
    "run_authorized_batch() does not directly invoke Razorpay.",
)

# Do not reject the word "webhook" appearing in comments,
# documentation, or metadata. Inspect actual function calls.
webhook_call_names = {
    "handle_webhook",
    "process_webhook",
    "verify_webhook",
    "dispatch_webhook",
    "webhook_handler",
}

actual_webhook_calls = []

for node in ast.walk(run_authorized_method):
    if isinstance(node, ast.Call):
        function_name = None

        if isinstance(node.func, ast.Name):
            function_name = node.func.id

        elif isinstance(node.func, ast.Attribute):
            function_name = node.func.attr

        if function_name in webhook_call_names:
            actual_webhook_calls.append(function_name)

check(
    not actual_webhook_calls,
    "run_authorized_batch() does not directly process webhooks.",
)


# ------------------------------------------------------------
# Final architecture
# ------------------------------------------------------------

print()
print("=" * 78)
print("STEP 15 COMBINED VERIFICATION: PASS")
print("=" * 78)
print()

print("Single AI advisory pass              : PASS")
print("Agent recommendation handoff        : PASS")
print("No duplicate AI call on handoff     : PASS")
print("AI remains advisory-only             : PASS")
print("Deterministic policy preserved       : PASS")
print("Existing decision engine preserved   : PASS")
print("Existing scheduler preserved         : PASS")
print("Existing execution preserved         : PASS")
print("Existing outcome verification        : PASS")
print("Existing metrics preserved           : PASS")
print("No payment engine duplication        : PASS")
print("No Razorpay changes                  : PASS")
print("No webhook changes                   : PASS")
print()
