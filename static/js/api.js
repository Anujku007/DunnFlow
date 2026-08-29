/* =========================================================
   DUNNFLOW — API CLIENT
   Centralized FastAPI communication layer
   ========================================================= */

const API_BASE = "";


/* =========================================================
   CORE REQUEST HANDLER
   ========================================================= */

async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
        ...options,

        headers: {
            Accept: "application/json",
            ...(options.body ? { "Content-Type": "application/json" } : {}),
            ...(options.headers || {})
        }
    });

    if (!response.ok) {
        let message = `Request failed with status ${response.status}`;

        try {
            const data = await response.json();

            if (typeof data.detail === "string") {
                message = data.detail;
            } else if (data.detail) {
                message = JSON.stringify(data.detail);
            }
        } catch {
            try {
                const text = await response.text();

                if (text) {
                    message = text;
                }
            } catch {
                // Keep the default error message.
            }
        }

        throw new Error(message);
    }

    return response.json();
}


/* =========================================================
   BATCH ID SAFETY
   ========================================================= */

function batchUrl(batchId, endpoint = "") {
    if (!batchId) {
        throw new Error("Batch ID is required.");
    }

    const encodedBatchId = encodeURIComponent(batchId);

    return `${API_BASE}/api/batches/${encodedBatchId}${endpoint}`;
}


/* =========================================================
   HEALTH
   ========================================================= */

async function getHealth() {
    return apiRequest(
        `${API_BASE}/api/health`
    );
}


/* =========================================================
   BATCH
   ========================================================= */

async function getBatch(batchId) {
    return apiRequest(
        batchUrl(batchId)
    );
}


/* =========================================================
   DETECTION
   ========================================================= */

async function detectBatch(batchId) {
    return apiRequest(
        batchUrl(batchId, "/detect"),
        {
            method: "POST"
        }
    );
}


/* =========================================================
   DECISION
   ========================================================= */

async function decideBatch(batchId) {
    return apiRequest(
        batchUrl(batchId, "/decide"),
        {
            method: "POST"
        }
    );
}


/* =========================================================
   EXECUTION
   ========================================================= */

async function executeBatch(batchId) {
    return apiRequest(
        batchUrl(batchId, "/execute"),
        {
            method: "POST"
        }
    );
}


/* =========================================================
   METRICS
   ========================================================= */

async function getMetrics(batchId) {
    return apiRequest(
        batchUrl(batchId, "/metrics")
    );
}


/* =========================================================
   REPORT
   ========================================================= */

function getReportUrl(batchId) {
    return batchUrl(batchId, "/report");
}