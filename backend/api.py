from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.modules.report import generate_batch_report

from backend.data.db import (
    init_db,
    get_batch_run,
    get_invoices,
    get_invoice,
    get_batch_metrics,
    get_audit_log,
    get_recovery_timeline,
    attach_razorpay_order_to_invoice,
)
from backend.modules.detection import detect_revenue_at_risk
from backend.modules.diagnosis import diagnose_invoice
from backend.modules.decision_engine import decide_for_invoice
from backend.modules.execution import execute_due_actions, execute_recovery_action
from backend.ai.ai_policy_reconciliation import reconcile_invoice
from backend.ai.recovery_advisor import RecoveryAdvisor
from backend.ai.historical_decision_context import get_historical_decision_context_dict
from backend.agent.recovery_agent import RecoveryAgent
from backend.data.demo_runs import create_isolated_demo_run, get_demo_run
from backend.data.db import create_batch_run, upsert_subscription, upsert_invoice


BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(
    title="DunnFlow API",
    version="1.0.0",
)

# Serve frontend assets
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "templates" / "index.html")



@app.get("/ai-inspection")
def ai_inspection_page():
    """Serve the standalone AI inspection report."""
    return FileResponse(BASE_DIR / "templates" / "ai_inspection.html")


@app.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    """Receive and authenticate Razorpay webhooks."""
    from fastapi import Header
    from backend.webhooks.verifier import (
        WebhookVerificationError,
        verify_razorpay_signature,
    )

    body = await request.body()
    signature = request.headers.get("x-razorpay-signature")

    try:
        valid = verify_razorpay_signature(body, signature or "")
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    if not valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature.",
        )

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON webhook payload.",
        )

    from backend.webhooks.handler import (
        WebhookHandlerError,
        handle_razorpay_webhook,
    )

    try:
        result = handle_razorpay_webhook(
            payload,
            event_id=request.headers.get("x-razorpay-event-id"),
        )
    except WebhookHandlerError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return result


# ============================================================================
@app.post("/api/demo/runs")
def create_demo_run():
    """Create a fresh visitor-isolated 60-case synthetic benchmark."""
    try:
        return create_isolated_demo_run()
    except Exception as exc:
        # Avoid returning internal exception details to public visitors.
        raise HTTPException(
            status_code=500,
            detail="Unable to create an isolated demo run.",
        ) from exc


@app.get("/api/demo/runs/{run_id}")
def inspect_demo_run(run_id: str):
    """Return run metadata only; this endpoint never executes recovery."""
    run = get_demo_run(run_id)
    if not run or run["status"] != "ready":
        raise HTTPException(status_code=404, detail="Demo run not found.")
    from backend.data.db import get_invoices
    invoices = get_invoices(batch_id=run["batch_id"])
    return {
        **run,
        "case_count": len(invoices),
        "invoice_ids": [item["invoice_id"] for item in invoices],
    }

# AUDIT TRAIL API
# ============================================================================
# Read-only judge-facing audit/timeline surface.
#
# IMPORTANT:
# - No database mutation.
# - No decision creation.
# - No execution.
# - No payment.
# - No webhook processing.
# - Existing audit records remain the source of truth.
# ============================================================================

@app.get("/api/audit")
def get_audit(
    batch_id: str | None = None,
    subscription_id: str | None = None,
    invoice_id: str | None = None,
):
    """
    Return immutable audit history or a unified recovery timeline.

    At least one scope identifier is required so the endpoint can never
    accidentally expose the entire audit database to the dashboard.

    This endpoint is strictly read-only.
    """

    if not any(
        (
            batch_id,
            subscription_id,
            invoice_id,
        )
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "One audit scope is required: "
                "batch_id, subscription_id, or invoice_id."
            ),
        )

    if invoice_id:
        events = get_recovery_timeline(
            invoice_id=invoice_id,
        )
    elif subscription_id:
        events = get_recovery_timeline(
            subscription_id=subscription_id,
        )
    else:
        events = get_audit_log(
            batch_id=batch_id,
        )

    return {
        "read_only": True,
        "deterministic_authority": True,
        "ai_advisory_only": True,
        "scope": {
            "batch_id": batch_id,
            "subscription_id": subscription_id,
            "invoice_id": invoice_id,
        },
        "events": events,
        "count": len(events),
    }



@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "dunnflow",
    }


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str):
    batch = get_batch_run(batch_id)

    if not batch:
        raise HTTPException(
            status_code=404,
            detail="Batch not found",
        )

    return batch


@app.post("/api/batches/{batch_id}/detect")
def detect_batch(batch_id: str):
    if not get_batch_run(batch_id):
        raise HTTPException(
            status_code=404,
            detail="Batch not found",
        )

    return detect_revenue_at_risk(batch_id)


@app.post("/api/batches/{batch_id}/decide")
def decide_batch(batch_id: str):
    if not get_batch_run(batch_id):
        raise HTTPException(
            status_code=404,
            detail="Batch not found",
        )

    invoices = get_invoices(batch_id=batch_id)

    decisions = []

    for invoice in invoices:
        decisions.append(
            decide_for_invoice(invoice["invoice_id"])
        )

    return {
        "batch_id": batch_id,
        "decisions": decisions,
    }




# ============================================================================
# DEMO CASE API
# ============================================================================
# Thin judge-facing single-invoice demo layer.
#
# IMPORTANT:
# - Existing recovery engine remains authoritative.
# - AI is advisory only.
# - Deterministic decision is the only executable decision.
# - Execution delegates to the existing guarded execution engine.
# ============================================================================



def _require_demo_run_invoice(run_id: str, invoice_id: str, *, for_execution: bool = False) -> dict:
    """Require a ready isolated run that owns the requested invoice."""
    run = get_demo_run(run_id)
    if not run or run.get("status") != "ready":
        raise HTTPException(status_code=404, detail="Demo run not found.")

    invoice = get_invoice(invoice_id)
    if not invoice or invoice.get("batch_id") != run.get("batch_id"):
        raise HTTPException(status_code=404, detail="Invoice not found in this demo run.")

    if for_execution:
        from backend.modules.execution import EXECUTION_MODE
        if EXECUTION_MODE != "synthetic_test_mode":
            raise HTTPException(
                status_code=409,
                detail="Isolated synthetic runs can execute only in synthetic_test_mode.",
            )
    return invoice

DEMO_CASES = {
    "fresh": "inv_dunnflow_006",
    "guardrail": "inv_dunnflow_012",
    "manual_review": "inv_dunnflow_060",
}


@app.get("/api/demo/cases/{invoice_id}")
def get_demo_case(invoice_id: str, run_id: str):
    """Return the current single-invoice demo state without mutation."""

    _require_demo_run_invoice(run_id, invoice_id)

    invoice = get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=404,
            detail="Invoice not found",
        )

    diagnosis = diagnose_invoice(invoice_id)

    decision = decide_for_invoice(
        invoice_id,
        persist=False,
    )

    return {
        "invoice": invoice,
        "diagnosis": diagnosis,
        "decision": decision,
        "deterministic_authority": True,
        "ai_advisory_only": True,
        "demo_case": next(
            (
                name
                for name, configured_invoice_id
                in DEMO_CASES.items()
                if configured_invoice_id == invoice_id
            ),
            None,
        ),
    }


@app.get("/api/demo/cases/{invoice_id}/inspect")
def inspect_demo_case(invoice_id: str, run_id: str):
    """
    Read-only Decision Intelligence preview for one demo invoice.

    This endpoint never creates or modifies a recovery action.
    Deterministic policy is evaluated with persist=False.
    AI remains advisory and cannot authorize execution.
    """

    _require_demo_run_invoice(run_id, invoice_id)

    invoice = get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=404,
            detail="Invoice not found",
        )

    diagnosis = diagnose_invoice(invoice_id)

    decision = decide_for_invoice(
        invoice_id,
        persist=False,
    )

    advisor = RecoveryAdvisor()

    reconciliation = reconcile_invoice(
        invoice_id=invoice_id,
        deterministic_decision=decision,
        advisor=advisor,
    )

    historical_context = get_historical_decision_context_dict(
        invoice_id,
        limit=20,
    )

    return {
        "invoice": get_invoice(invoice_id),
        "diagnosis": diagnosis,
        "decision": decision,
        "ai_reconciliation": reconciliation.to_dict(),
        "historical_context": historical_context,
        "deterministic_authority": True,
        "ai_advisory_only": True,
        "read_only": True,
    }


@app.post("/api/demo/cases/{invoice_id}/decide")
def decide_demo_case(invoice_id: str, run_id: str):
    """
    Create the deterministic recovery action for one demo invoice and
    reconcile AI advice against it.

    AI never changes or authorizes the deterministic decision.
    """

    _require_demo_run_invoice(run_id, invoice_id)

    invoice = get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=404,
            detail="Invoice not found",
        )

    diagnosis = diagnose_invoice(invoice_id)

    decision = decide_for_invoice(
        invoice_id,
        persist=True,
    )

    advisor = RecoveryAdvisor()

    reconciliation = reconcile_invoice(
        invoice_id=invoice_id,
        deterministic_decision=decision,
        advisor=advisor,
    )

    return {
        "invoice": get_invoice(invoice_id),
        "diagnosis": diagnosis,
        "decision": decision,
        "ai_reconciliation": reconciliation.to_dict(),
        "deterministic_authority": True,
        "ai_advisory_only": True,
    }


@app.post("/api/demo/cases/{invoice_id}/execute")
def execute_demo_case(invoice_id: str, run_id: str):
    """
    Execute the already-created deterministic recovery action for one
    demo invoice through the scheduler's virtual demo clock.

    Demo execution preserves the real scheduling semantics:

        planned action
            ?
        demo clock = action.scheduled_for
            ?
        scheduler due check
            ?
        guarded execution

    The stored scheduled_for timestamp is NOT modified.
    """

    from backend.data.db import (
        get_recovery_actions,
        get_recovery_action,
    )
    from backend.modules.scheduler import (
        get_demo_time_for_action,
        is_action_due,
    )

    _require_demo_run_invoice(run_id, invoice_id, for_execution=True)

    invoice = get_invoice(invoice_id)

    if not invoice:
        raise HTTPException(
            status_code=404,
            detail="Invoice not found",
        )

    # ---------------------------------------------------------------
    # Select the latest executable action only.
    #
    # Do not blindly use actions[-1], because the latest historical
    # action may already be blocked/executed/cancelled.
    # ---------------------------------------------------------------

    actions = get_recovery_actions(
        invoice_id=invoice_id,
    )

    planned_actions = [
        action
        for action in actions
        if action.get("status") == "planned"
    ]

    if not planned_actions:
        raise HTTPException(
            status_code=409,
            detail=(
                "No planned recovery action exists. "
                "Decide the demo case first."
            ),
        )

    action = planned_actions[-1]

    # ---------------------------------------------------------------
    # Use the action's own scheduled_for as the virtual demo clock.
    #
    # This makes a T+24h/T+1h action immediately due WITHOUT changing
    # the persisted schedule.
    # ---------------------------------------------------------------

    demo_time = get_demo_time_for_action(
        action
    )

    if not is_action_due(
        action,
        as_of=demo_time,
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Recovery action is not due under the scheduler."
            ),
        )

    # ---------------------------------------------------------------
    # Execute through the existing guarded execution engine.
    # ---------------------------------------------------------------

    result = execute_recovery_action(
        action["action_id"],
        as_of=demo_time,
    )

    return {
        "invoice": get_invoice(invoice_id),
        "action": get_recovery_action(
            action["action_id"]
        ),
        "execution": result,
        "scheduler": {
            "demo_time": demo_time.isoformat(
                timespec="seconds"
            ),
            "scheduled_for": action.get(
                "scheduled_for"
            ),
            "due": True,
        },
        "deterministic_authority": True,
        "ai_advisory_only": True,
    }


@app.post("/api/batches/{batch_id}/execute")
def execute_batch(batch_id: str, run_id: str | None = None):
    demo_run = get_demo_run(run_id) if run_id else None
    if demo_run and demo_run.get("batch_id") != batch_id:
        raise HTTPException(status_code=404, detail="Demo run not found.")
    if batch_id.startswith("demo_"):
        if not demo_run or demo_run.get("status") != "ready":
            raise HTTPException(status_code=404, detail="Demo run not found.")
        from backend.modules.execution import EXECUTION_MODE
        if EXECUTION_MODE != "synthetic_test_mode":
            raise HTTPException(
                status_code=409,
                detail="Isolated synthetic runs can execute only in synthetic_test_mode.",
            )

    if not get_batch_run(batch_id):
        raise HTTPException(
            status_code=404,
            detail="Batch not found",
        )

    return execute_due_actions(batch_id)



@app.post("/api/demo/razorpay/session")
def create_razorpay_demo_session(request: Request):
    """Create an isolated Ã¢â€šÂ¹299 Razorpay Test Mode demo session."""
    from datetime import datetime, timezone

    from backend.data.razorpay_demo import (
        DEMO_AMOUNT_PAISE,
        DEMO_CURRENCY,
        attach_order_to_razorpay_demo_session,
        claim_razorpay_demo_order_creation,
        get_razorpay_demo_session,
        register_razorpay_demo_session,
        update_razorpay_demo_session_status,
    )
    from backend.integrations.razorpay_client import (
        RazorpayClient,
        RazorpayClientError,
    )
    from backend.data.seed_data import (
        build_subscription,
        build_invoice,
        build_initial_failed_attempt,
        record_initial_revenue_events,
    )
    from backend.data.db import create_payment_attempt

    idempotency_key = request.headers.get("idempotency-key", "").strip()
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="The Idempotency-Key header is required.",
        )

    try:
        session = register_razorpay_demo_session(idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # A retry after a successful request returns the same order.
    if session["status"] == "order_created" and session.get("razorpay_order_id"):
        client = RazorpayClient()
        if (
            client.get_mode() != "test"
            or not client.configured
            or not client.key_id.startswith("rzp_test_")
        ):
            raise HTTPException(
                status_code=503,
                detail="Razorpay Test Mode configuration is unavailable.",
            )
        return {
            "session_id": session["session_id"],
            "batch_id": session["batch_id"],
            "invoice_id": session["invoice_id"],
            "razorpay_order_id": session["razorpay_order_id"],
            "key_id": client.key_id,
            "amount": session["amount_paise"],
            "currency": session["currency"],
            "status": session["status"],
            "mode": "razorpay_test_mode",
        }

    if session["status"] != "creating":
        raise HTTPException(
            status_code=409,
            detail=(
                "This demo session cannot start another order request. "
                "Its current status requires inspection or manual review."
            ),
        )

    try:
        client = RazorpayClient()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Razorpay configuration is unavailable.",
        ) from exc

    # Never make an external request unless all three checks pass.
    if (
        client.get_mode() != "test"
        or not client.configured
        or not client.key_id.startswith("rzp_test_")
    ):
        raise HTTPException(
            status_code=503,
            detail="Razorpay Test Mode configuration is required.",
        )

    if not claim_razorpay_demo_order_creation(session["session_id"]):
        latest = get_razorpay_demo_session(session["session_id"])
        if latest and latest["status"] == "order_created" and latest.get("razorpay_order_id"):
            raise HTTPException(
                status_code=409,
                detail="The session already has an order; retrieve the session status.",
            )
        raise HTTPException(
            status_code=409,
            detail="Order creation is already claimed or requires manual review.",
        )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        create_batch_run(session["batch_id"], started_at=now, status="running")

        subscription = build_subscription(
            index=0,
            batch_id=session["batch_id"],
            created_at=now,
            scenario="card_expired",
            initial_retry_count=0,
        )
        subscription.update({
            "subscription_id": session["subscription_id"],
            "razorpay_subscription_id": (
                "sub_test_rpdemo_"
                + session["session_id"].replace("-", "")[:24]
            ),
            "batch_id": session["batch_id"],
            "amount": DEMO_AMOUNT_PAISE,
            "currency": DEMO_CURRENCY,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        })
        upsert_subscription(subscription)

        invoice = build_invoice(
            index=0,
            batch_id=session["batch_id"],
            subscription=subscription,
            created_at=now,
            scenario="card_expired",
        )
        invoice.update({
            "invoice_id": session["invoice_id"],
            "batch_id": session["batch_id"],
            "subscription_id": session["subscription_id"],
            "razorpay_invoice_id": None,
            "razorpay_order_id": None,
            "amount": DEMO_AMOUNT_PAISE,
            "currency": DEMO_CURRENCY,
            "status": "issued",
            "issued_at": now,
            "paid_at": None,
            "created_at": now,
            "updated_at": now,
        })
        upsert_invoice(invoice)

        # This is a synthetic pre-existing failure signal for the demo.
        # It is not a Razorpay payment or a gateway webhook.
        initial_attempt = build_initial_failed_attempt(
            index=0,
            batch_id=session["batch_id"],
            subscription=subscription,
            invoice=invoice,
            created_at=now,
            scenario="card_expired",
        )
        initial_attempt["razorpay_payment_id"] = None
        initial_attempt["result_detail"] = (
            "Synthetic pre-existing failed charge for the isolated "
            "Razorpay Test Mode recovery demo; not a gateway transaction."
        )
        attempt_id = create_payment_attempt(initial_attempt)
        record_initial_revenue_events(
            batch_id=session["batch_id"],
            subscription=subscription,
            invoice=invoice,
            payment_attempt_id=attempt_id,
            created_at=now,
            scenario="card_expired",
        )
    except Exception as exc:
        update_razorpay_demo_session_status(
            session["session_id"], "manual_review"
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to prepare the isolated demo invoice; manual review required.",
        ) from exc

    # Once this call begins, a network error may be ambiguous. Never retry it
    # automatically under the same session.
    try:
        order = client.create_order(
            amount=DEMO_AMOUNT_PAISE,
            currency=DEMO_CURRENCY,
            receipt=session["invoice_id"],
            notes={
                "dunnflow_invoice_id": session["invoice_id"],
                "dunnflow_demo_session_id": session["session_id"],
                "dunnflow_mode": "razorpay_test_mode",
            },
        )
    except RazorpayClientError as exc:
        update_razorpay_demo_session_status(
            session["session_id"], "manual_review"
        )
        raise HTTPException(
            status_code=502,
            detail="Razorpay order result is uncertain; manual review required.",
        ) from exc
    except Exception as exc:
        update_razorpay_demo_session_status(
            session["session_id"], "manual_review"
        )
        raise HTTPException(
            status_code=502,
            detail="Order request failed or returned an uncertain result; manual review required.",
        ) from exc

    order_id = order.get("id") if isinstance(order, dict) else None
    if (
        not isinstance(order_id, str)
        or not order_id
        or order.get("amount") != DEMO_AMOUNT_PAISE
        or str(order.get("currency", "")).upper() != DEMO_CURRENCY
    ):
        update_razorpay_demo_session_status(
            session["session_id"], "manual_review"
        )
        raise HTTPException(
            status_code=502,
            detail="Razorpay order response failed validation; manual review required.",
        )

    try:
        attach_razorpay_order_to_invoice(session["invoice_id"], order_id)
        attached = attach_order_to_razorpay_demo_session(
            session["session_id"], order_id
        )
    except Exception as exc:
        update_razorpay_demo_session_status(
            session["session_id"], "manual_review"
        )
        raise HTTPException(
            status_code=500,
            detail="Order was returned but could not be safely linked; manual review required.",
        ) from exc

    return {
        "session_id": attached["session_id"],
        "batch_id": attached["batch_id"],
        "invoice_id": attached["invoice_id"],
        "razorpay_order_id": attached["razorpay_order_id"],
        "key_id": client.key_id,
        "amount": DEMO_AMOUNT_PAISE,
        "currency": DEMO_CURRENCY,
        "status": attached["status"],
        "mode": "razorpay_test_mode",
    }





@app.post("/api/demo/razorpay/session/{session_id}/recover")
def recover_isolated_razorpay_demo_session(session_id: str):
    """
    Run detection, diagnosis and deterministic decision for one isolated
    Razorpay session. This endpoint never executes a payment or creates
    an order. Decision persistence is deliberately disabled so a scheduler
    cannot later execute a customer-checkout decision unexpectedly.
    """
    from backend.data.razorpay_demo import get_razorpay_demo_session

    session = get_razorpay_demo_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Razorpay demo session not found.")

    if session.get("status") != "order_created" or not session.get("razorpay_order_id"):
        raise HTTPException(
            status_code=409,
            detail="An existing Razorpay Test Mode order is required before recovery preparation.",
        )

    invoice = get_invoice(session["invoice_id"])
    if not invoice or invoice.get("batch_id") != session.get("batch_id"):
        raise HTTPException(
            status_code=409,
            detail="The isolated session invoice is missing or mismatched.",
        )

    if invoice.get("status") == "paid" or session.get("status") == "paid":
        raise HTTPException(
            status_code=409,
            detail="This isolated session is already paid; use authoritative status verification.",
        )

    if invoice.get("razorpay_order_id") != session.get("razorpay_order_id"):
        raise HTTPException(
            status_code=409,
            detail="Session and invoice order IDs do not match.",
        )

    try:
        amount_matches = (
            int(invoice.get("amount")) == int(session.get("amount_paise"))
        )
    except (TypeError, ValueError):
        amount_matches = False

    if (
        not amount_matches
        or str(invoice.get("currency") or "").upper()
        != str(session.get("currency") or "").upper()
    ):
        raise HTTPException(
            status_code=409,
            detail="Session and invoice amount/currency do not match.",
        )

    detection = detect_revenue_at_risk(session["batch_id"])
    diagnosis = diagnose_invoice(session["invoice_id"])
    decision = decide_for_invoice(session["invoice_id"], persist=False)

    return {
        "session_id": session["session_id"],
        "batch_id": session["batch_id"],
        "invoice_id": session["invoice_id"],
        "razorpay_order_id": session["razorpay_order_id"],
        "detection": detection,
        "diagnosis": diagnosis,
        "decision": decision,
        "pipeline": {
            "detection": "complete",
            "diagnosis": "complete",
            "decision": "complete",
            "execution": "prepared_existing_order",
            "payment": "awaiting_customer",
        },
        "awaiting_payment": True,
        "financial_execution_performed": False,
        "decision_persisted": False,
        "deterministic_authority": True,
        "ai_advisory_only": True,
    }


@app.get("/api/demo/razorpay/session/{session_id}")
def get_razorpay_demo_session_status(session_id: str):
    """Read session and invoice state without changing financial state."""
    from backend.data.razorpay_demo import get_razorpay_demo_session

    session = get_razorpay_demo_session(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail="Razorpay demo session not found.",
        )

    invoice = get_invoice(session["invoice_id"])
    if not invoice:
        raise HTTPException(
            status_code=409,
            detail="Session invoice is missing; manual review is required.",
        )

    session_order_id = session.get("razorpay_order_id")
    invoice_order_id = invoice.get("razorpay_order_id")
    order_matches = bool(
        session_order_id
        and invoice_order_id
        and session_order_id == invoice_order_id
    )
    try:
        invoice_amount_matches = (
            int(invoice.get("amount")) == int(session.get("amount_paise"))
        )
    except (TypeError, ValueError):
        invoice_amount_matches = False

    invoice_currency = str(invoice.get("currency") or "").upper()
    session_currency = str(session.get("currency") or "").upper()
    invoice_currency_matches = bool(
        invoice_currency
        and invoice_currency == session_currency
    )

    verified_paid = bool(
        session.get("status") == "paid"
        and invoice.get("status") == "paid"
        and order_matches
        and invoice_amount_matches
        and invoice_currency_matches
    )

    return {
        "session_id": session["session_id"],
        "batch_id": session["batch_id"],
        "invoice_id": session["invoice_id"],
        "razorpay_order_id": session_order_id,
        "session_status": session["status"],
        "invoice_status": invoice.get("status"),
        "order_matches": order_matches,
        "verified_paid": verified_paid,
        "amount": session["amount_paise"],
        "currency": session["currency"],
        "mode": "razorpay_test_mode",
    }


@app.get("/api/demo/razorpay/inspect/{invoice_id}")
def inspect_razorpay_demo_invoice(invoice_id: str):
    """Read an existing Razorpay demo invoice and session without mutations."""
    from backend.data.razorpay_demo import (
        get_razorpay_demo_session_by_invoice_id,
    )

    session = get_razorpay_demo_session_by_invoice_id(invoice_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail="No existing Razorpay demo session was found for this invoice.",
        )

    invoice = get_invoice(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=409,
            detail="The Razorpay demo session exists, but its invoice is missing.",
        )

    session_order_id = session.get("razorpay_order_id")
    invoice_order_id = invoice.get("razorpay_order_id")
    order_matches = bool(
        session_order_id
        and invoice_order_id
        and session_order_id == invoice_order_id
    )

    try:
        amount_matches = (
            int(invoice.get("amount")) == int(session.get("amount_paise"))
        )
    except (TypeError, ValueError):
        amount_matches = False

    currency_matches = (
        str(invoice.get("currency") or "").upper()
        == str(session.get("currency") or "").upper()
    )

    verified_paid = bool(
        session.get("status") == "paid"
        and invoice.get("status") == "paid"
        and order_matches
        and amount_matches
        and currency_matches
    )

    # Read-only: retrieve existing records for this invoice.
    from backend.data.db import (
        get_payment_attempts,
        get_recovery_timeline,
        get_revenue_events,
    )

    payment_attempts = get_payment_attempts(invoice_id=invoice_id)
    timeline = get_recovery_timeline(invoice_id=invoice_id)
    revenue_events = get_revenue_events(invoice_id=invoice_id)

    diagnosis_event = next(
        (
            event for event in timeline
            if event.get("type") == "audit"
            and event.get("stage") == "diagnose"
        ),
        None,
    )
    diagnosis = {}
    if diagnosis_event:
        diagnosis = {
            "category": invoice.get("failure_category"),
            "reason": diagnosis_event.get("detail"),
            "source": "persisted_audit_event",
            "created_at": diagnosis_event.get("timestamp"),
        }

    historical_context = get_historical_decision_context_dict(
        invoice_id,
        limit=20,
    )

    # Do not recommend recovery for an invoice/session already marked paid.
    # This is a read-only status summary, not a persisted decision.
    if invoice.get("status") == "paid" or session.get("status") == "paid":
        decision = {
            "action": "no_action",
            "reason": "The invoice or session is already marked paid; no further recovery action is appropriate.",
            "source": "read_only_paid_state",
            "persisted": False,
        }
    else:
        decision = decide_for_invoice(invoice_id, persist=False)

    return {
        "invoice_id": invoice_id,
        "invoice": invoice,
        "session": {
            "session_id": session["session_id"],
            "batch_id": session["batch_id"],
            "session_status": session["status"],
            "razorpay_order_id": session_order_id,
            "order_matches": order_matches,
            "amount_matches": amount_matches,
            "currency_matches": currency_matches,
            "verified_paid": verified_paid,
            "mode": "razorpay_test_mode",
        },
        "diagnosis": diagnosis,
        "decision": decision,
        "ai_reconciliation": {
            "result": "not_evaluated",
            "detail": "Read-only inspection; no AI request or decision was executed.",
        },
        "historical_context": historical_context,
        "payment_attempts": payment_attempts,
        "audit": {
            "read_only": True,
            "events": timeline,
            "count": len(timeline),
        },
        "revenue_events": revenue_events,
    }



@app.get("/api/demo/razorpay/metrics")
def get_isolated_razorpay_metrics():
    """Return aggregate metrics for registered isolated Razorpay demo sessions."""
    from backend.data.razorpay_demo import get_isolated_razorpay_demo_metrics

    return get_isolated_razorpay_demo_metrics()

@app.get("/api/batches/{batch_id}/razorpay-checkout")
def razorpay_checkout(batch_id: str):
    if not get_batch_run(batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")

    invoices = get_invoices(batch_id=batch_id)

    # ---------------------------------------------------------------
    # Razorpay Test Mode checkout
    #
    # DunnFlow only exposes an invoice that:
    #   1. belongs to this batch,
    #   2. already has a Razorpay order mapped to it,
    #   3. is not already paid.
    #
    # Order creation and invoice -> Razorpay order mapping are handled
    # explicitly before this route is called.
    # ---------------------------------------------------------------
    invoice = next(
        (
            invoice
            for invoice in invoices
            if invoice.get("razorpay_order_id")
            and invoice.get("status") != "paid"
        ),
        None,
    )

    if not invoice:
        raise HTTPException(
            status_code=404,
            detail="No Razorpay Checkout order found for this batch",
        )

    from backend.integrations.razorpay_client import RazorpayClient

    client = RazorpayClient()

    return {
        "batch_id": batch_id,
        "invoice_id": invoice["invoice_id"],
        "razorpay_order_id": invoice["razorpay_order_id"],
        "razorpay_key_id": client.key_id,
        "amount": invoice["amount"],
        "currency": invoice["currency"],
        "status": invoice["status"],
    }


@app.get("/api/batches/{batch_id}/metrics")
def batch_metrics(batch_id: str):
    metrics = get_batch_metrics(batch_id)

    if not metrics.get("exists"):
        raise HTTPException(
            status_code=404,
            detail="Batch not found",
        )

    return metrics


@app.get("/reports/{batch_id}")
def report_page(batch_id: str):
    if not get_batch_run(batch_id):
        raise HTTPException(
            status_code=404,
            detail="Batch not found",
        )

    report_template = (
        Path(__file__).resolve().parent.parent
        / "templates"
        / "report.html"
    )

    if not report_template.exists():
        raise HTTPException(
            status_code=500,
            detail="Report page template not found.",
        )

    return FileResponse(
        path=report_template,
        media_type="text/html",
    )


@app.get("/api/batches/{batch_id}/report")
def download_batch_report(batch_id: str):
    if not get_batch_run(batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")

    report_path = generate_batch_report(batch_id)

    return FileResponse(
        path=report_path,
        media_type="application/pdf",
        filename=f"dunnflow_report_{batch_id}.pdf",
    )




# ============================================================================
# STEP 13 ? RECOVERY AGENT PLANNING / INSPECTION
# ============================================================================

@app.get("/api/batches/{batch_id}/agent")
def inspect_recovery_agent(batch_id: str):
    """
    Inspect the existing RecoveryAgent planning state.

    This endpoint is read/planning only.

    It does not:
      - schedule recovery actions
      - execute payments
      - create Razorpay payments
      - mutate financial recovery state

    AI remains advisory and deterministic policy remains authoritative.
    """

    if not get_batch_run(batch_id):
        raise HTTPException(
            status_code=404,
            detail="Batch not found",
        )

    agent = RecoveryAgent(
        batch_id=batch_id,
    )

    context = agent.prepare_batch()

    return {
        "batch_id": batch_id,
        "agent": {
            "state": context.state.value,
            "history": context.history,
            "agent_ready": context.result.get(
                "agent_ready",
                False,
            ),
        },
        "execution_authority": context.result.get(
            "execution_authority",
        ),
        "financial_authority": context.result.get(
            "financial_authority",
        ),
        "ai_authority": context.result.get(
            "ai_authority",
        ),
        "detection": context.result.get(
            "detection",
            {},
        ),
        "diagnoses": context.result.get(
            "diagnoses",
            [],
        ),
        "ai_recommendations": context.result.get(
            "ai_recommendations",
            [],
        ),
        "ranked_opportunities": context.result.get(
            "ranked_opportunities",
            [],
        ),
        "read_only": True,
    }

