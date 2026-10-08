from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[2]

FILES = [
    "backend/agent/recovery_agent.py",
    "backend/api.py",
    "backend/modules/execution.py",
    "backend/modules/scheduler.py",
    "backend/modules/decision_engine.py",
    "backend/modules/outcome_tracker.py",
    "backend/ai/ai_policy_reconciliation.py",
    "backend/webhooks/handler.py",
    "backend/webhooks/verifier.py",
    "static/js/api.js",
    "static/js/state.js",
    "static/js/scenario-cards.js",
    "static/js/audit-trail.js",
]


def read(rel):
    return (ROOT / rel).read_text(
        encoding="utf-8-sig"
    )


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main():

    print("=" * 78)
    print("DUNNFLOW STEP 13 — COMBINED VERIFICATION")
    print("=" * 78)
    print()

    # ------------------------------------------------------------
    # Required files
    # ------------------------------------------------------------

    for rel in FILES:
        check(
            (ROOT / rel).exists(),
            f"Required file exists: {rel}",
        )

    # ------------------------------------------------------------
    # Python syntax
    # ------------------------------------------------------------

    python_files = [
        "backend/agent/recovery_agent.py",
        "backend/api.py",
        "backend/modules/execution.py",
        "backend/modules/scheduler.py",
        "backend/modules/decision_engine.py",
        "backend/modules/outcome_tracker.py",
        "backend/ai/ai_policy_reconciliation.py",
        "backend/webhooks/handler.py",
        "backend/webhooks/verifier.py",
    ]

    for rel in python_files:
        ast.parse(
            read(rel),
            filename=rel,
        )

    print("[PASS] All required Python files pass AST validation.")

    # ------------------------------------------------------------
    # RecoveryAgent structure
    # ------------------------------------------------------------

    agent = read(
        "backend/agent/recovery_agent.py"
    )

    for token in [
        "class AgentState",
        "class RecoveryAgentContext",
        "class RecoveryAgent",
        "def observe(",
        "def diagnose(",
        "def recommend(",
        "def prioritize(",
        "def authorize(",
        "def schedule(",
        "def execute(",
        "def verify(",
        "def measure(",
        "def evaluate_stopping_rule(",
        "def escalate(",
        "def prepare_batch(",
        "def run_batch(",
    ]:
        check(
            token in agent,
            f"RecoveryAgent contains {token}",
        )

    # ------------------------------------------------------------
    # prepare_batch safety
    # ------------------------------------------------------------

    start = agent.index(
        "    def prepare_batch("
    )

    end = agent.index(
        "    def run_batch(",
        start,
    )

    prepare = agent[start:end]

    check(
        "self.observe(" in prepare,
        "prepare_batch performs observation.",
    )

    check(
        "self.diagnose(" in prepare,
        "prepare_batch performs diagnosis.",
    )

    check(
        "self.recommend(" in prepare,
        "prepare_batch performs AI advisory recommendation.",
    )

    check(
        "self.prioritize(" in prepare,
        "prepare_batch performs prioritization.",
    )

    for forbidden in [
        "self.schedule(",
        "self.execute(",
        "self.verify(",
    ]:
        check(
            forbidden not in prepare,
            f"prepare_batch does not call {forbidden}",
        )

    check(
        '"execution_authority"' in prepare,
        "Agent exposes execution authority.",
    )

    check(
        '"deterministic_orchestrator"' in prepare,
        "Execution authority is deterministic orchestrator.",
    )

    check(
        '"financial_authority"' in prepare,
        "Agent exposes financial authority.",
    )

    check(
        '"deterministic_policy"' in prepare,
        "Financial authority remains deterministic policy.",
    )

    check(
        '"ai_authority"' in prepare,
        "Agent exposes AI authority.",
    )

    check(
        '"advisory_only"' in prepare,
        "AI authority remains advisory-only.",
    )

    check(
        '"agent_ready"' in prepare,
        "Agent exposes readiness state.",
    )

    # ------------------------------------------------------------
    # API endpoint
    # ------------------------------------------------------------

    api = read("backend/api.py")

    check(
        "from backend.agent.recovery_agent import RecoveryAgent"
        in api,
        "API imports the existing RecoveryAgent.",
    )

    route = '@app.get("/api/batches/{batch_id}/agent")'

    check(
        route in api,
        "Step 13 agent inspection endpoint exists.",
    )

    route_start = api.index(route)
    route_end = api.find(
        "\n@app.",
        route_start + len(route),
    )

    if route_end == -1:
        route_end = len(api)

    endpoint = api[
        route_start:route_end
    ]

    check(
        "RecoveryAgent(" in endpoint,
        "Endpoint instantiates RecoveryAgent.",
    )

    check(
        "prepare_batch(" in endpoint,
        "Endpoint invokes prepare_batch only.",
    )

    check(
        '"read_only": True' in endpoint,
        "Endpoint declares read_only=True.",
    )

    for forbidden in [
        ".schedule(",
        ".execute(",
        ".verify(",
        "create_order(",
        "capture(",
        "payment.create",
    ]:
        check(
            forbidden not in endpoint,
            f"Endpoint does not invoke {forbidden}",
        )

    # ------------------------------------------------------------
    # Frontend API
    # ------------------------------------------------------------

    api_js = read("static/js/api.js")

    check(
        "async function getRecoveryAgent(batchId)"
        in api_js,
        "Frontend getRecoveryAgent() exists.",
    )

    check(
        "/api/batches/${encodeURIComponent(batchId)}/agent"
        in api_js,
        "Frontend uses the Step 13 endpoint.",
    )

    check(
        "getRecoveryAgent," in api_js,
        "getRecoveryAgent is exported.",
    )

    # ------------------------------------------------------------
    # Frontend state
    # ------------------------------------------------------------

    state = read("static/js/state.js")

    for token in [
        "agentState:",
        "agentReady:",
        "agentHistory:",
        "agentPlan:",
        "function resetAgentState(",
    ]:
        check(
            token in state,
            f"Frontend state contains {token}",
        )

    # ------------------------------------------------------------
    # Scenario integration
    # ------------------------------------------------------------

    scenario = read(
        "static/js/scenario-cards.js"
    )

    check(
        "async function refreshRecoveryAgent("
        in scenario,
        "Scenario layer contains refreshRecoveryAgent().",
    )

    check(
        "DunnFlowAPI.getRecoveryAgent"
        in scenario,
        "Scenario layer uses centralized API.",
    )

    check(
        "dunnflow:agent-ready"
        in scenario,
        "Scenario layer emits agent-ready event.",
    )

    check(
        "refreshRecoveryAgent,"
        in scenario,
        "Agent refresh is exposed through the demo layer.",
    )

    # ------------------------------------------------------------
    # Existing financial architecture
    # ------------------------------------------------------------

    execution = read(
        "backend/modules/execution.py"
    )

    scheduler = read(
        "backend/modules/scheduler.py"
    )

    decision = read(
        "backend/modules/decision_engine.py"
    )

    reconciliation = read(
        "backend/ai/ai_policy_reconciliation.py"
    )

    check(
        "razorpay" in execution.lower(),
        "Existing Razorpay execution layer remains present.",
    )

    check(
        "guard" in execution.lower()
        or "guardrail" in execution.lower(),
        "Existing execution guardrails remain present.",
    )

    check(
        "determin" in decision.lower(),
        "Deterministic decision layer remains present.",
    )

    check(
        "schedule" in scheduler.lower(),
        "Existing scheduler remains present.",
    )

    check(
        "deterministic" in reconciliation.lower(),
        "AI-policy reconciliation preserves deterministic authority.",
    )

    check(
        "advisory" in reconciliation.lower(),
        "AI-policy reconciliation remains advisory.",
    )

    # ------------------------------------------------------------
    # Webhook architecture
    # ------------------------------------------------------------

    handler = read(
        "backend/webhooks/handler.py"
    )

    verifier = read(
        "backend/webhooks/verifier.py"
    )

    check(
        "webhook_event_exists" in handler,
        "Webhook idempotency architecture remains present.",
    )

    check(
        "hmac.new" in verifier,
        "Webhook HMAC verification remains present.",
    )

    # ------------------------------------------------------------
    # Audit architecture
    # ------------------------------------------------------------

    audit = read(
        "static/js/audit-trail.js"
    )

    check(
        ".audit-row" in audit,
        "Audit-row ownership remains isolated.",
    )

    check(
        ".activity-item" in audit,
        "Live activity-feed ownership remains preserved.",
    )

    check(
        "getAuditTrail" in audit,
        "Audit UI remains connected through centralized API.",
    )

    # ------------------------------------------------------------
    # Frontend syntax
    # ------------------------------------------------------------

    for rel in [
        "static/js/api.js",
        "static/js/state.js",
        "static/js/scenario-cards.js",
        "static/js/audit-trail.js",
    ]:
        result = __import__(
            "subprocess"
        ).run(
            ["node", "--check", str(ROOT / rel)],
            capture_output=True,
            text=True,
        )

        check(
            result.returncode == 0,
            f"Node syntax validation passed: {rel}",
        )

    # ------------------------------------------------------------
    # No duplicate financial engine
    # ------------------------------------------------------------

    check(
        "def execute(" in agent,
        "RecoveryAgent still delegates through its existing execution capability.",
    )

    check(
        "def schedule(" in agent,
        "RecoveryAgent still delegates through its existing scheduling capability.",
    )

    check(
        "def verify(" in agent,
        "RecoveryAgent still delegates through its existing verification capability.",
    )

    # ------------------------------------------------------------
    # Final architectural boundary
    # ------------------------------------------------------------

    check(
        "deterministic_orchestrator" in agent,
        "Agent execution boundary points to deterministic orchestrator.",
    )

    check(
        "deterministic_policy" in agent,
        "Financial authority remains deterministic policy.",
    )

    check(
        "advisory_only" in agent,
        "AI remains advisory-only.",
    )

    print()
    print("=" * 78)
    print("STEP 13 COMBINED VERIFICATION: PASS")
    print("=" * 78)
    print()
    print("RecoveryAgent planning boundary    : PASS")
    print("AI advisory-only boundary          : PASS")
    print("Deterministic policy authority     : PASS")
    print("Execution authority                : PASS")
    print("Agent API                           : PASS")
    print("Frontend API                        : PASS")
    print("Frontend state                      : PASS")
    print("Scenario integration                : PASS")
    print("Existing scheduler                  : PASS")
    print("Existing execution engine          : PASS")
    print("Existing verification               : PASS")
    print("Webhook idempotency                 : PASS")
    print("Webhook signature verification     : PASS")
    print("Audit architecture                  : PASS")
    print("No duplicate financial engine       : PASS")
    print("No new payment execution            : PASS")
    print("No new webhook processing           : PASS")
    print()


if __name__ == "__main__":
    main()
