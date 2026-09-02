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
)
from backend.modules.detection import detect_revenue_at_risk
from backend.modules.decision_engine import decide_for_invoice
from backend.modules.execution import execute_due_actions


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

    invoice = next((invoice for invoice in invoices if invoice.get("razorpay_order_id") and invoice.get("status") != "paid"), None)

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


