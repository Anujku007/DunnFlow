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
    attach_razorpay_order_to_invoice,
)
from backend.modules.detection import detect_revenue_at_risk
from backend.modules.diagnosis import diagnose_invoice
from backend.modules.decision_engine import decide_for_invoice
from backend.modules.execution import execute_due_actions, execute_recovery_action
from backend.ai.ai_policy_reconciliation import reconcile_invoice
from backend.ai.recovery_advisor import RecoveryAdvisor


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

DEMO_CASES = {
    "fresh": "inv_dunnflow_006",
    "guardrail": "inv_dunnflow_012",
    "manual_review": "inv_dunnflow_060",
}


@app.get("/api/demo/cases/{invoice_id}")
def get_demo_case(invoice_id: str):
    """Return the current single-invoice demo state without mutation."""

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
def inspect_demo_case(invoice_id: str):
    """
    Read-only Decision Intelligence preview for one demo invoice.

    This endpoint never creates or modifies a recovery action.
    Deterministic policy is evaluated with persist=False.
    AI remains advisory and cannot authorize execution.
    """

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

    return {
        "invoice": get_invoice(invoice_id),
        "diagnosis": diagnosis,
        "decision": decision,
        "ai_reconciliation": reconciliation.to_dict(),
        "deterministic_authority": True,
        "ai_advisory_only": True,
        "read_only": True,
    }


@app.post("/api/demo/cases/{invoice_id}/decide")
def decide_demo_case(invoice_id: str):
    """
    Create the deterministic recovery action for one demo invoice and
    reconcile AI advice against it.

    AI never changes or authorizes the deterministic decision.
    """

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
def execute_demo_case(invoice_id: str):
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
def execute_batch(batch_id: str):
    if not get_batch_run(batch_id):
        raise HTTPException(
            status_code=404,
            detail="Batch not found",
        )

    return execute_due_actions(batch_id)


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


