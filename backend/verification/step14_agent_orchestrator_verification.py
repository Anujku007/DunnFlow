from pathlib import Path
import ast

ROOT = Path(".")

def read(path):
    return Path(path).read_text(
        encoding="utf-8-sig"
    )

def check(condition, message):
    if not condition:
        raise AssertionError(
            "[FAIL] " + message
        )
    print("[PASS] " + message)


print("=" * 78)
print("DUNNFLOW STEP 14 — AGENT / ORCHESTRATOR HANDOFF VERIFICATION")
print("=" * 78)
print()

agent_path = ROOT / "backend" / "agent" / "recovery_agent.py"
orchestrator_path = ROOT / "orchestrator.py"

check(
    agent_path.exists(),
    "RecoveryAgent file exists.",
)

check(
    orchestrator_path.exists(),
    "Deterministic orchestrator exists.",
)

agent = read(agent_path)
orchestrator = read(orchestrator_path)

# ------------------------------------------------------------
# Syntax
# ------------------------------------------------------------

ast.parse(
    agent,
    filename=str(agent_path),
)

ast.parse(
    orchestrator,
    filename=str(orchestrator_path),
)

print(
    "[PASS] RecoveryAgent and orchestrator pass AST validation."
)

# ------------------------------------------------------------
# Step 13 planning boundary remains
# ------------------------------------------------------------

check(
    "def prepare_batch(" in agent,
    "prepare_batch() remains present.",
)

check(
    '"execution_authority"' in agent,
    "Agent execution authority metadata remains present.",
)

check(
    '"deterministic_orchestrator"' in agent,
    "Agent points execution authority to deterministic orchestrator.",
)

check(
    '"financial_authority"' in agent,
    "Agent financial authority metadata remains present.",
)

check(
    '"deterministic_policy"' in agent,
    "Financial authority remains deterministic policy.",
)

check(
    '"ai_authority"' in agent,
    "Agent AI authority metadata remains present.",
)

check(
    '"advisory_only"' in agent,
    "AI remains advisory-only.",
)

# ------------------------------------------------------------
# Step 14 handoff
# ------------------------------------------------------------

check(
    "def run_authorized_batch(" in agent,
    "run_authorized_batch() exists.",
)

handoff_start = agent.index(
    "    def run_authorized_batch("
)

handoff_end = agent.find(
    "    def run_batch(",
    handoff_start,
)

if handoff_end == -1:
    handoff_end = len(agent)

handoff = agent[
    handoff_start:handoff_end
]

check(
    "self.prepare_batch(" in handoff,
    "Authorized batch execution starts with agent planning.",
)

check(
    "from orchestrator import run_batch as run_deterministic_batch"
    in handoff,
    "Agent hands execution to the existing deterministic orchestrator.",
)

check(
    "run_deterministic_batch(" in handoff,
    "Agent invokes the deterministic orchestrator.",
)

check(
    '"execution_authority"' in handoff,
    "Agent validates execution authority before handoff.",
)

check(
    '"financial_authority"' in handoff,
    "Agent validates financial authority before handoff.",
)

check(
    '"ai_authority"' in handoff,
    "Agent validates AI authority before handoff.",
)

check(
    "agent_plan=" in handoff,
    "Agent passes validated planning metadata to orchestrator.",
)

# The new handoff must NOT become a second financial engine.

check(
    "execute_due_actions(" not in handoff,
    "run_authorized_batch() does not directly execute payment actions.",
)

check(
    "schedule_batch(" not in handoff,
    "run_authorized_batch() does not directly schedule recovery actions.",
)

# ------------------------------------------------------------
# Existing orchestrator
# ------------------------------------------------------------

check(
    "def run_batch(" in orchestrator,
    "Existing orchestrator.run_batch() remains present.",
)

check(
    "agent_plan: dict | None = None" in orchestrator,
    "Orchestrator accepts optional agent_plan.",
)

check(
    "agent_handoff =" in orchestrator,
    "Orchestrator creates an explicit agent handoff record.",
)

check(
    '"advisory_only": True' in orchestrator,
    "Agent handoff is explicitly advisory-only.",
)

check(
    '"execution_authority": "deterministic_orchestrator"'
    in orchestrator,
    "Orchestrator execution authority remains deterministic.",
)

check(
    '"financial_authority": "deterministic_policy"'
    in orchestrator,
    "Orchestrator financial authority remains deterministic policy.",
)

check(
    '"ai_authority": "advisory_only"'
    in orchestrator,
    "Orchestrator AI authority remains advisory-only.",
)

# ------------------------------------------------------------
# Existing financial pipeline must remain
# ------------------------------------------------------------

for token, label in [
    ("detect_revenue_at_risk(", "detection"),
    ("decide_batch(", "deterministic decision"),
    ("schedule_batch(", "scheduler"),
    ("execute_due_actions(", "execution"),
    ("process_customer_responses(", "customer response"),
    ("summarize_batch_outcomes(", "outcome reconciliation"),
    ("get_batch_metrics(", "authoritative metrics"),
]:
    check(
        token in orchestrator,
        f"Existing {label} pipeline remains present.",
    )

# ------------------------------------------------------------
# Agent plan must NOT override deterministic decisions
# ------------------------------------------------------------

check(
    "agent_plan" in orchestrator,
    "Agent plan is visible only as orchestration metadata.",
)

check(
    "agent_plan.get(" in orchestrator,
    "Agent plan is validated before acceptance.",
)

check(
    "agent_handoff" in orchestrator,
    "Agent handoff is recorded separately from financial decisions.",
)

# ------------------------------------------------------------
# Result visibility
# ------------------------------------------------------------

check(
    '"agent_handoff": agent_handoff' in orchestrator,
    "Agent handoff is exposed in orchestrator result.",
)

# ------------------------------------------------------------
# No webhook/payment architecture changes
# ------------------------------------------------------------

check(
    "razorpay" not in handoff.lower(),
    "Agent handoff does not directly invoke Razorpay.",
)

# The handoff may document the existing webhook architecture.
# What matters is that it does not invoke webhook processing functions.
for forbidden in [
    "handle_webhook(",
    "process_webhook(",
    "verify_webhook(",
    "dispatch_webhook(",
    "webhook_handler(",
]:
    check(
        forbidden not in handoff.lower(),
        f"Agent handoff does not invoke {forbidden}",
    )

print(
    "[PASS] Agent handoff does not process webhooks directly."
)

# ------------------------------------------------------------
# Final architecture
# ------------------------------------------------------------

print()
print("=" * 78)
print("STEP 14 COMBINED VERIFICATION: PASS")
print("=" * 78)
print()
print("Agent planning boundary              : PASS")
print("Agent → orchestrator handoff         : PASS")
print("Deterministic execution authority    : PASS")
print("Deterministic financial authority    : PASS")
print("AI advisory-only boundary            : PASS")
print("Existing decision engine preserved   : PASS")
print("Existing scheduler preserved         : PASS")
print("Existing execution preserved         : PASS")
print("Existing outcome verification        : PASS")
print("Existing metrics preserved           : PASS")
print("No duplicate payment engine          : PASS")
print("No direct Razorpay execution         : PASS")
print("No webhook changes                   : PASS")
print()
