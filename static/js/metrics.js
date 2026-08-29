const runButton = document.getElementById("runBatchBtn");
const pipelineStatus = document.getElementById("pipelineStatus");
const batchSelect = document.getElementById("batchSelect");

function getSelectedBatchId() {
    return batchSelect.value;
}

function setStep(id, state) {
    const step = document.getElementById(id);

    if (!step) return;

    step.dataset.state = state;

    if (state === "active") {
        step.style.borderColor = "#7c5cff";
    }

    if (state === "done") {
        step.style.borderColor = "#39d98a";
    }

    if (state === "error") {
        step.style.borderColor = "#ff647c";
    }
}

function formatINR(amount) {
    return "INR " + (Number(amount || 0) / 100).toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

function updateMetrics(metrics, riskAmount = null) {
    document.getElementById("riskAmount").textContent =
        formatINR(
            riskAmount !== null
                ? riskAmount
                : metrics.historical_amount_at_risk
        );

    document.getElementById("recoveredAmount").textContent =
        formatINR(metrics.amount_recovered);

    document.getElementById("recoveryRate").textContent =
        `${metrics.recovery_rate_pct || 0}%`;

    document.getElementById("inProgress").textContent =
        metrics.in_progress_count || 0;
}

function clearActivityFeed() {
    const feed = document.getElementById("activityFeed");

    if (feed) {
        feed.innerHTML = "";
    }
}

function addActivity(message) {
    const feed = document.getElementById("activityFeed");

    const item = document.createElement("div");
    item.className = "activity-item";

    item.innerHTML = `
        <span class="activity-dot"></span>
        <span>${message}</span>
    `;

    feed.prepend(item);
}

function renderCases(decisions) {
    const table = document.getElementById("casesTable");

    table.innerHTML = "";

    if (!decisions || decisions.length === 0) {
        table.innerHTML = `
            <tr>
                <td colspan="4" class="empty">
                    No recovery cases found.
                </td>
            </tr>
        `;
        return;
    }

    for (const decision of decisions) {
        const row = document.createElement("tr");

        row.innerHTML = `
            <td>${decision.action_type || "unknown"}</td>
            <td>${decision.rationale || "-"}</td>
            <td>${decision.priority || "-"}</td>
            <td>${decision.decision || "-"}</td>
        `;

        table.appendChild(row);
    }
}

function downloadReport() {
    const batchId = getSelectedBatchId();

    if (!batchId) {
        addActivity("Please select a demo batch first.");
        return;
    }

    addActivity(`Generating report for ${batchId}...`);

    window.location.href =
        `/api/batches/${encodeURIComponent(batchId)}/report`;
}

async function runRecovery() {
    const batchId = getSelectedBatchId();

    clearActivityFeed();

    runButton.disabled = true;
    runButton.textContent = "RUNNING...";

    pipelineStatus.textContent = "DETECTING";

    try {
        // -----------------------------------------
        // 1. DETECT
        // -----------------------------------------

        setStep("detectStep", "active");

        addActivity("Detecting revenue at risk...");

        const detection = await detectBatch(batchId);

        setStep("detectStep", "done");

        addActivity(
            `Detection complete: ${detection.detected_count} recoverable case(s).`
        );

        // -----------------------------------------
        // 2. DECIDE
        // -----------------------------------------

        pipelineStatus.textContent = "DECIDING";

        setStep("decideStep", "active");

        addActivity("Running recovery decision engine...");

        const decisionResult = await decideBatch(batchId);

        setStep("decideStep", "done");

        renderCases(decisionResult.decisions);

        addActivity(
            `Decision engine evaluated ${decisionResult.decisions.length} case(s).`
        );

        // -----------------------------------------
        // 3. EXECUTE
        // -----------------------------------------

        pipelineStatus.textContent = "EXECUTING";

        setStep("executeStep", "active");

        addActivity("Executing approved recovery actions...");

        const execution = await executeBatch(batchId);

        setStep("executeStep", "done");

        addActivity(
            `Execution complete: ${execution.actions_executed} action(s) executed.`
        );

        // -----------------------------------------
        // 4. OUTCOME / METRICS
        // -----------------------------------------

        pipelineStatus.textContent = "TRACKING OUTCOME";

        setStep("outcomeStep", "active");

        const metrics = await getMetrics(batchId);

updateMetrics(metrics, detection.amount_at_risk);

        setStep("outcomeStep", "done");

        pipelineStatus.textContent = "COMPLETE";

        addActivity(
            `Recovery metrics updated. Recovery rate: ${metrics.recovery_rate_pct}%.`
        );

    } catch (error) {
        console.error(error);

        pipelineStatus.textContent = "ERROR";

        addActivity(`Pipeline error: ${error.message}`);

        [
            "detectStep",
            "decideStep",
            "executeStep",
            "outcomeStep"
        ].forEach(id => {
            const step = document.getElementById(id);

            if (step && step.dataset.state === "active") {
                setStep(id, "error");
            }
        });

    } finally {
        runButton.disabled = false;
        runButton.textContent = "RUN RECOVERY";
    }
}

runButton.addEventListener("click", runRecovery);

const downloadReportButton =
      document.getElementById("downloadReportBtn");

downloadReportButton.addEventListener("click", downloadReport);

batchSelect.addEventListener("change", async () => {
    const batchId = getSelectedBatchId();

    // Clear previous batch activity
    clearActivityFeed();

    try {
        const detection = await detectBatch(batchId);
        const metrics = await getMetrics(batchId);

        updateMetrics(metrics, detection.amount_at_risk);

        renderCases([]);

        pipelineStatus.textContent = "READY";

        [
            "detectStep",
            "decideStep",
            "executeStep",
            "outcomeStep"
        ].forEach(id => {
            const step = document.getElementById(id);

            if (step) {
                step.dataset.state = "";
                step.style.borderColor = "";
            }
        });

        addActivity(
            `Switched to batch ${batchId}.`
        );

    } catch (error) {
        console.error(error);
        addActivity(
            `Unable to load batch ${batchId}.`
        );
    }
});


// Load initial metrics
(async function initializeDashboard() {
    try {
        const health = await getHealth();

        if (health.status === "ok") {
            addActivity("DunnFlow API connected.");
        }

        const batchId = getSelectedBatchId();

        const detection = await detectBatch(batchId);
        const metrics = await getMetrics(batchId);

        updateMetrics(metrics, detection.amount_at_risk);

    } catch (error) {
        console.error("Dashboard initialization failed:", error);
        addActivity("Unable to connect to DunnFlow API.");
    }
})();