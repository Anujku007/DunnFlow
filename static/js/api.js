const API_BASE = "";

const DEMO_BATCH_ID = "e2e_api_card_expired_001";

async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        }
    });

    if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status}: ${text}`);
    }

    return response.json();
}

async function getHealth() {
    return apiRequest(`${API_BASE}/api/health`);
}

async function getBatch(batchId) {
    return apiRequest(`${API_BASE}/api/batches/${batchId}`);
}

async function detectBatch(batchId) {
    return apiRequest(
        `${API_BASE}/api/batches/${batchId}/detect`,
        { method: "POST" }
    );
}

async function decideBatch(batchId) {
    return apiRequest(
        `${API_BASE}/api/batches/${batchId}/decide`,
        { method: "POST" }
    );
}

async function executeBatch(batchId) {
    return apiRequest(
        `${API_BASE}/api/batches/${batchId}/execute`,
        { method: "POST" }
    );
}

async function getMetrics(batchId) {
    return apiRequest(
        `${API_BASE}/api/batches/${batchId}/metrics`
    );
}