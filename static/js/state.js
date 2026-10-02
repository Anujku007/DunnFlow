/*
 * DunnFlow — Frontend State
 *
 * Single source of truth for UI execution mode.
 *
 * CONTROL:
 *   batch-level recovery pipeline
 *
 * DEMO:
 *   invoice-level recovery demonstration
 */

const DUNNFLOW_DEFAULT_BATCH =
    "benchmark_60_subscription_failures";

const DunnFlowState = {
    mode: "control",

    batchId: DUNNFLOW_DEFAULT_BATCH,

    invoiceId: null,

    scenario: null,

    demoStage: "idle",

    running: false,

    lastDiagnosis: null,

    lastDecision: null,

    lastExecution: null,

    lastMetrics: null
};


function enterControlMode(batchId) {
    DunnFlowState.mode = "control";

    DunnFlowState.batchId =
        batchId ||
        DUNNFLOW_DEFAULT_BATCH;

    DunnFlowState.invoiceId = null;
    DunnFlowState.scenario = null;

    DunnFlowState.lastDiagnosis = null;
    DunnFlowState.lastDecision = null;
    DunnFlowState.lastExecution = null;
    DunnFlowState.demoStage = "idle";
}


function enterDemoMode(invoiceId, scenario = null) {
    if (!invoiceId) {
        throw new Error(
            "A demo invoice ID is required."
        );
    }

    DunnFlowState.mode = "demo";

    /*
     * Demo scenario selection changes only the recovery target.
     * Preserve the currently selected Demo Batch.
     */
    DunnFlowState.invoiceId = invoiceId;

    DunnFlowState.scenario = scenario;
    DunnFlowState.demoStage = "idle";

    DunnFlowState.lastDiagnosis = null;
    DunnFlowState.lastDecision = null;
    DunnFlowState.lastExecution = null;
    DunnFlowState.demoStage = "idle";
}


function setRecoveryRunning(value) {
    DunnFlowState.running =
        Boolean(value);
}


function resetRecoveryResult() {
    DunnFlowState.lastDiagnosis = null;
    DunnFlowState.lastDecision = null;
    DunnFlowState.lastExecution = null;

    if (
        !(
            DunnFlowState.mode === "demo" &&
            (
                DunnFlowState.demoStage === "scheduled" ||
                DunnFlowState.demoStage === "completed"
            )
        )
    ) {
        DunnFlowState.demoStage = "idle";
    }
}


function isDemoMode() {
    return DunnFlowState.mode === "demo";
}


function isControlMode() {
    return DunnFlowState.mode === "control";
}


function getSelectedBatchId() {
    return (
        DunnFlowState.batchId ||
        DUNNFLOW_DEFAULT_BATCH
    );
}


function getSelectedDemoInvoiceId() {
    return DunnFlowState.invoiceId || null;
}


window.DunnFlowState = DunnFlowState;

window.DUNNFLOW_DEFAULT_BATCH =
    DUNNFLOW_DEFAULT_BATCH;
