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
 * Demo case
 */
async function getDemoCase(invoiceId) {
    if (!invoiceId) {
        throw new Error(
            "Demo invoice ID is required."
        );
    }

    return apiRequest(
        `/api/demo/cases/${encodeURIComponent(invoiceId)}`
    );
}


async function inspectDemoCase(invoiceId) {
    if (!invoiceId) {
        throw new Error(
            "Demo invoice ID is required."
        );
    }

    return apiRequest(
        `/api/demo/cases/${encodeURIComponent(invoiceId)}/inspect`
    );
}


/**
 * Demo decision
 */
async function decideDemoCase(invoiceId) {
    if (!invoiceId) {
        throw new Error(
            "Demo invoice ID is required for decision."
        );
    }

    return apiRequest(
        `/api/demo/cases/${encodeURIComponent(invoiceId)}/decide`,
        {
            method: "POST"
        }
    );
}


/**
 * Demo execution
 */
async function executeDemoCase(invoiceId) {
    if (!invoiceId) {
        throw new Error(
            "Demo invoice ID is required for execution."
        );
    }

    return apiRequest(
        `/api/demo/cases/${encodeURIComponent(invoiceId)}/execute`,
        {
            method: "POST"
        }
    );
}


/**
 * Existing Razorpay checkout information.
 */
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
window.DunnFlowAPI = {
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

    getRazorpayCheckout
};