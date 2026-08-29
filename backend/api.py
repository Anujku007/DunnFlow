from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.data.db import (
    init_db,
    get_batch_run,
    get_invoices,
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


@app.get("/api/batches/{batch_id}/metrics")
def batch_metrics(batch_id: str):
    metrics = get_batch_metrics(batch_id)

    if not metrics.get("exists"):
        raise HTTPException(
            status_code=404,
            detail="Batch not found",
        )

    return metrics