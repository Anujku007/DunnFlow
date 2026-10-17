/*
 * DunnFlow — API Layer
 *
 * Responsibilities:
 * - HTTP communication with the FastAPI backend.
 * - Centralized error handling.
 * - No UI state decisions.
 * - No navigation logic.
 * - No recovery orchestration.
 *
 * Execution mode belongs to state.js / metrics.js.
 */

const API_BASE = "";


/**
 * Generic API request helper.
 */
async function apiRequest(
    path,
    options = {}
) {
    const {
        method = "GET",
        headers = {},
        body = null
    } = options;

    const requestHeaders = {
        Accept: "application/json",
        ...headers
    };

    const requestOptions = {
        method,
        headers: requestHeaders
    };

    if (body !== null) {
        requestOptions.headers["Content-Type"] =
            "application/json";

        requestOptions.body =
            typeof body === "string"
                ? body
                : JSON.stringify(body);
    }

    let response;

    try {
        response = await fetch(
            `${API_BASE}${path}`,
            requestOptions
        );
    } catch (error) {
        throw new Error(
            `Network error while requesting ${path}: ${
                error.message || error
            }`
        );
    }

    let payload = null;

    const contentType =
        response.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
        try {
            payload = await response.json();
        } catch (error) {
            payload = null;
        }
    } else {
        try {
            payload = await response.text();
        } catch (error) {
            payload = null;
        }
    }

    if (!response.ok) {
        const detail =
            payload &&
            typeof payload === "object" &&
            payload.detail
                ? payload.detail
                : `HTTP ${response.status}`;

        throw new Error(
            `${detail}`
        );
    }

    return payload;
}


/**
 * Health
 */
async function getHealth() {
    return apiRequest(
        "/api/health"
    );
}


/**
 * Batch
 */
async function getBatch(batchId) {
    if (!batchId) {
        throw new Error(
            "Batch ID is required."
        );
    }

    return apiRequest(
        `/api/batches/${encodeURIComponent(batchId)}`
    );
}


/**
 * Batch detection
 */
async function detectBatch(batchId) {
    if (!batchId) {
        throw new Error(
            "Batch ID is required for detection."
        );
    }

    return apiRequest(
        `/api/batches/${encodeURIComponent(batchId)}/detect`,
        {
            method: "POST"
        }
    );
}


/**
 * Batch decision
 */
async function decideBatch(batchId) {
    if (!batchId) {
        throw new Error(
            "Batch ID is required for decision."
        );
    }

    return apiRequest(
        `/api/batches/${encodeURIComponent(batchId)}/decide`,
        {
            method: "POST"
        }
    );
}


/**
 * Batch execution
 */
async function executeBatch(batchId) {
    if (!batchId) {
        throw new Error(
            "Batch ID is required for execution."
        );
    }

    return apiRequest(
        `/api/batches/${encodeURIComponent(batchId)}/execute`,
        {
            method: "POST"
        }
    );
}


/**
 * Batch metrics
 */
async function getMetrics(batchId) {
    if (!batchId) {
        throw new Error(
            "Batch ID is required for metrics."
        );
    }

    return apiRequest(
        `/api/batches/${encodeURIComponent(batchId)}/metrics`
    );
}


/**
 * Batch report URL.
 *
 * This function does not perform a request.
 * It only returns the backend report path.
 */
function getReportUrl(batchId) {
    if (!batchId) {
        throw new Error(
            "Batch ID is required for the report."
        );
    }

    return (
        `/api/batches/${encodeURIComponent(batchId)}/report`
    );
}


/**
 * Visitor-isolated synthetic demo run.
 */
async function createDemoRun() {
    return apiRequest("/api/demo/runs", {
        method: "POST"
    });
}

async function getDemoRun(runId) {
    if (!runId) {
        throw new Error("Demo run ID is required.");
    }

    return apiRequest(
        `/api/demo/runs/${encodeURIComponent(runId)}`
    );
}

function requireDemoRunId(runId) {
    const resolved =
        runId ||
        (window.DunnFlowState && window.DunnFlowState.runId);

    if (!resolved) {
        throw new Error(
            "No isolated demo run is active. Create a demo run first."
        );
    }

    return resolved;
}


/**
 * Demo case
 */
async function getDemoCase(invoiceId, runId = null) {
    const activeRunId = requireDemoRunId(runId);

    if (!invoiceId) {
        throw new Error(
            "Demo invoice ID is required."
        );
    }

    return apiRequest(
        `/api/demo/cases/${encodeURIComponent(invoiceId)}?run_id=${encodeURIComponent(activeRunId)}`
    );
}


async function inspectDemoCase(invoiceId, runId = null) {
    const activeRunId = requireDemoRunId(runId);

    if (!invoiceId) {
        throw new Error(
            "Demo invoice ID is required."
        );
    }

    return apiRequest(
        `/api/demo/cases/${encodeURIComponent(invoiceId)}/inspect?run_id=${encodeURIComponent(activeRunId)}`
    );
}


/**
 * Demo decision
 */
async function decideDemoCase(invoiceId, runId = null) {
    const activeRunId = requireDemoRunId(runId);

    if (!invoiceId) {
        throw new Error(
            "Demo invoice ID is required for decision."
        );
    }

    return apiRequest(
        `/api/demo/cases/${encodeURIComponent(invoiceId)}/decide?run_id=${encodeURIComponent(activeRunId)}`,
        {
            method: "POST"
        }
    );
}


/**
 * Demo execution
 */
async function executeDemoCase(invoiceId, runId = null) {
    const activeRunId = requireDemoRunId(runId);

    if (!invoiceId) {
        throw new Error(
            "Demo invoice ID is required for execution."
        );
    }

    return apiRequest(
        `/api/demo/cases/${encodeURIComponent(invoiceId)}/execute?run_id=${encodeURIComponent(activeRunId)}`,
        {
            method: "POST"
        }
    );
}


/**
 * Read-only audit timeline.
 *
 * No mutation, decision, execution, or payment occurs here.
 */
async function getAuditTrail({
    batchId = null,
    subscriptionId = null,
    invoiceId = null
} = {}) {

    const params = new URLSearchParams();

    if (batchId) {
        params.set("batch_id", batchId);
    }

    if (subscriptionId) {
        params.set("subscription_id", subscriptionId);
    }

    if (invoiceId) {
        params.set("invoice_id", invoiceId);
    }

    if (!params.toString()) {
        throw new Error(
            "An audit scope is required."
        );
    }

    return apiRequest(
        `/api/audit?${params.toString()}`
    );
}



/**
 * Existing Razorpay checkout information.
 */


/**
 * Create or retrieve an isolated Razorpay Test Mode demo session.
 * The caller must retain the same idempotency key after an ambiguous
 * network failure. This helper does not run automatically.
 */
async function createRazorpayDemoSession(idempotencyKey) {
    if (
        typeof idempotencyKey !== "string" ||
        !idempotencyKey.trim()
    ) {
        throw new Error(
            "An idempotency key is required for the Razorpay demo session."
        );
    }

    return apiRequest(
        "/api/demo/razorpay/session",
        {
            method: "POST",
            headers: {
                "Idempotency-Key": idempotencyKey
            }
        }
    );
}


/**
 * Read authoritative status for one Razorpay demo session.
 */
async function getRazorpayDemoSessionStatus(sessionId) {
    if (!sessionId) {
        throw new Error(
            "Session ID is required to inspect Razorpay demo status."
        );
    }

    return apiRequest(
        `/api/demo/razorpay/session/${encodeURIComponent(sessionId)}`
    );
}

async function runIsolatedRazorpayRecovery(sessionId) {
    if (!sessionId) {
        throw new Error("An isolated Razorpay session ID is required for recovery.");
    }

    return apiRequest(
        `/api/demo/razorpay/session/${encodeURIComponent(sessionId)}/recover`,
        { method: "POST" }
    );
}


async function getRazorpayCheckout(batchId) {
    if (!batchId) {
        throw new Error(
            "Batch ID is required for Razorpay checkout."
        );
    }

    return apiRequest(
        `/api/batches/${encodeURIComponent(batchId)}/razorpay-checkout`
    );
}


/**
 * Expose the API contract explicitly.
 *
 * These references make the browser-side API surface
 * easy to inspect without introducing another global
 * state object.
 */

async function getRecoveryAgent(batchId) {
    if (!batchId) {
        throw new Error(
            "Batch ID is required for recovery-agent inspection."
        );
    }

    return apiRequest(
        `/api/batches/${encodeURIComponent(batchId)}/agent`
    );
}

window.DunnFlowAPI = {
    createDemoRun,
    getDemoRun,
    getRecoveryAgent,
    apiRequest,

    getHealth,
    getBatch,

    detectBatch,
    decideBatch,
    executeBatch,

    getMetrics,
    getReportUrl,

    getDemoCase,
    inspectDemoCase,
    decideDemoCase,
    executeDemoCase,

    getAuditTrail,

    getRazorpayCheckout,
    createRazorpayDemoSession,
    getRazorpayDemoSessionStatus,
    runIsolatedRazorpayRecovery
};