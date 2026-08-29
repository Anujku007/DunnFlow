/* =========================================================
   DUNNFLOW — DASHBOARD CONTROLLER
   Recovery pipeline + dashboard rendering

   IMPORTANT:
   - Backend behavior is unchanged.
   - Delays below are UI pacing only.
   - All actual results still come from the DunnFlow API.
   ========================================================= */


/* =========================================================
   DOM REFERENCES
   ========================================================= */

const runButton = document.getElementById("runBatchBtn");
const downloadReportButton = document.getElementById("downloadReportBtn");
const pipelineStatus = document.getElementById("pipelineStatus");
const batchSelect = document.getElementById("batchSelect");


/* =========================================================
   UI PACING
   ========================================================= */

/*
 * The backend responds very quickly.
 *
 * Without a small visual pause, the four pipeline stages
 * appear to complete almost instantly.
 *
 * 900ms per stage gives the demo enough pacing to be
 * understandable while keeping the entire recovery run
 * comfortably below the 5–6 second demo-video limit.
 */

const STAGE_DELAY_MS = 900;


function wait(ms) {
    return new Promise(resolve => {
        setTimeout(resolve, ms);
    });
}


/* =========================================================
   BATCH HELPERS
   ========================================================= */

function getSelectedBatchId() {
    return batchSelect ? batchSelect.value : "";
}


/* =========================================================
   PIPELINE UI
   ========================================================= */

function resetPipeline() {

    [
        "detectStep",
        "decideStep",
        "executeStep",
        "outcomeStep"
    ].forEach(id => {

        const step = document.getElementById(id);

        if (!step) return;

        step.dataset.state = "";
        step.style.borderColor = "";
    });

    if (pipelineStatus) {
        pipelineStatus.textContent = "READY";
    }
}


function setStep(id, state) {

    const step = document.getElementById(id);

    if (!step) return;

    step.dataset.state = state;

    /*
     * Keep the current inline styling because it works with
     * the existing DunnFlow pipeline design.
     */

    if (state === "active") {

        step.style.borderColor = "#7c5cff";

    } else if (state === "done") {

        step.style.borderColor = "#39d98a";

    } else if (state === "error") {

        step.style.borderColor = "#ff647c";

    } else {

        step.style.borderColor = "";
    }
}


/* =========================================================
   FORMATTING
   ========================================================= */

function formatINR(amount) {

    const value = Number(amount || 0) / 100;

    return "₹" + value.toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}


function formatPercent(value) {

    const number = Number(value || 0);

    return `${number}%`;
}


/* =========================================================
   METRICS
   ========================================================= */

function updateMetrics(metrics, riskAmount = null) {

    if (!metrics) return;

    const riskElement =
        document.getElementById("riskAmount");

    const recoveredElement =
        document.getElementById("recoveredAmount");

    const rateElement =
        document.getElementById("recoveryRate");

    const progressElement =
        document.getElementById("inProgress");


    const amountAtRisk =
        riskAmount !== null
            ? riskAmount
            : metrics.historical_amount_at_risk;


    if (riskElement) {

        riskElement.textContent =
            formatINR(amountAtRisk);
    }


    if (recoveredElement) {

        recoveredElement.textContent =
            formatINR(metrics.amount_recovered);
    }


    if (rateElement) {

        rateElement.textContent =
            formatPercent(metrics.recovery_rate_pct);
    }


    if (progressElement) {

        progressElement.textContent =
            Number(metrics.in_progress_count || 0);
    }
}


/* =========================================================
   ACTIVITY FEED
   ========================================================= */

function clearActivityFeed() {

    const feed =
        document.getElementById("activityFeed");

    if (feed) {
        feed.innerHTML = "";
    }
}


function addActivity(message, type = "normal") {

    const feed =
        document.getElementById("activityFeed");

    if (!feed) return;


    const item =
        document.createElement("div");

    item.className = "activity-item";


    if (type === "error") {
        item.classList.add("activity-error");
    }


    if (type === "success") {
        item.classList.add("activity-success");
    }


    if (type === "warning") {
        item.classList.add("activity-warning");
    }


    const dot =
        document.createElement("span");

    dot.className = "activity-dot";


    const text =
        document.createElement("span");

    text.textContent = message;


    item.appendChild(dot);
    item.appendChild(text);


    /*
     * Newest activity stays at the top of the feed,
     * matching the current dashboard design.
     */

    feed.prepend(item);
}


/* =========================================================
   RECOVERY CASES
   ========================================================= */

function renderCases(decisions) {

    const table =
        document.getElementById("casesTable");

    if (!table) return;


    table.innerHTML = "";


    if (
        !Array.isArray(decisions) ||
        decisions.length === 0
    ) {

        const row =
            document.createElement("tr");

        const cell =
            document.createElement("td");

        cell.colSpan = 4;
        cell.className = "empty";
        cell.textContent =
            "No recovery cases found.";

        row.appendChild(cell);
        table.appendChild(row);

        return;
    }


    decisions.forEach(decision => {

        const row =
            document.createElement("tr");


        const failureCell =
            document.createElement("td");

        failureCell.textContent =
            decision.action_type || "unknown";


        const actionCell =
            document.createElement("td");

        actionCell.textContent =
            decision.rationale || "-";


        const priorityCell =
            document.createElement("td");

        priorityCell.textContent =
            decision.priority || "-";


        const statusCell =
            document.createElement("td");

        statusCell.textContent =
            decision.decision || "-";


        row.appendChild(failureCell);
        row.appendChild(actionCell);
        row.appendChild(priorityCell);
        row.appendChild(statusCell);


        table.appendChild(row);
    });
}


/* =========================================================
   REPORT DOWNLOAD
   ========================================================= */

function downloadReport() {

    const batchId =
        getSelectedBatchId();


    if (!batchId) {

        addActivity(
            "Please select a demo batch first.",
            "warning"
        );

        return;
    }


    addActivity(
        `Preparing recovery report for ${batchId}...`
    );


    /*
     * getReportUrl() is provided by api.js.
     */

    window.location.href =
        getReportUrl(batchId);
}


/* =========================================================
   RECOVERY PIPELINE
   ========================================================= */

async function runRecovery() {

    const batchId =
        getSelectedBatchId();


    if (!batchId) {

        addActivity(
            "Please select a demo batch first.",
            "warning"
        );

        return;
    }


    clearActivityFeed();
    resetPipeline();


    if (runButton) {

        runButton.disabled = true;

        runButton.innerHTML =
            '<span class="button-icon">▶</span> RUNNING...';
    }


    try {

        /* =====================================================
           1. DETECT
           ===================================================== */

        pipelineStatus.textContent =
            "DETECTING";


        setStep(
            "detectStep",
            "active"
        );


        addActivity(
            "Detecting revenue at risk..."
        );


        /*
         * Give the judge enough time to see
         * DETECT before the API result appears.
         */

        await wait(STAGE_DELAY_MS);


        /*
         * REAL BACKEND CALL
         */

        const detection =
            await detectBatch(batchId);


        setStep(
            "detectStep",
            "done"
        );


        addActivity(
            `Detection complete: ${Number(
                detection.detected_count || 0
            )} recoverable case(s).`,
            "success"
        );


        /* =====================================================
           2. DECIDE
           ===================================================== */

        pipelineStatus.textContent =
            "DECIDING";


        setStep(
            "decideStep",
            "active"
        );


        addActivity(
            "Running recovery decision engine..."
        );


        /*
         * Visual pacing before the decision result.
         */

        await wait(STAGE_DELAY_MS);


        /*
         * REAL BACKEND CALL
         */

        const decisionResult =
            await decideBatch(batchId);


        const decisions =
            Array.isArray(
                decisionResult.decisions
            )
                ? decisionResult.decisions
                : [];


        setStep(
            "decideStep",
            "done"
        );


        /*
         * Render the actual backend decision
         * into the Recovery Cases table.
         */

        renderCases(decisions);


        addActivity(
            `Decision engine evaluated ${decisions.length} case(s).`
        );


        /* =====================================================
           3. EXECUTE
           ===================================================== */

        pipelineStatus.textContent =
            "EXECUTING";


        setStep(
            "executeStep",
            "active"
        );


        addActivity(
            "Executing approved recovery actions..."
        );


        /*
         * Visual pacing before execution result.
         */

        await wait(STAGE_DELAY_MS);


        /*
         * REAL BACKEND CALL
         */

        const execution =
            await executeBatch(batchId);


        const actionsExecuted =
            Number(
                execution.actions_executed || 0
            );


        setStep(
            "executeStep",
            "done"
        );


        addActivity(
            `Execution complete: ${actionsExecuted} action(s) executed.`,
            actionsExecuted > 0
                ? "success"
                : "warning"
        );


        /* =====================================================
           4. OUTCOME
           ===================================================== */

        pipelineStatus.textContent =
            "TRACKING OUTCOME";


        setStep(
            "outcomeStep",
            "active"
        );


        addActivity(
            "Updating recovery metrics..."
        );


        /*
         * Visual pacing before the final metrics result.
         */

        await wait(STAGE_DELAY_MS);


        /*
         * REAL BACKEND CALL
         */

        const metrics =
            await getMetrics(batchId);


        updateMetrics(
            metrics,
            detection.amount_at_risk
        );


        setStep(
            "outcomeStep",
            "done"
        );


        pipelineStatus.textContent =
            "COMPLETE";


        addActivity(
            `Recovery metrics updated. Recovery rate: ${
                metrics.recovery_rate_pct || 0
            }%.`,
            "success"
        );


    } catch (error) {

        console.error(
            "DunnFlow recovery pipeline error:",
            error
        );


        pipelineStatus.textContent =
            "ERROR";


        addActivity(
            `Pipeline error: ${error.message}`,
            "error"
        );


        [
            "detectStep",
            "decideStep",
            "executeStep",
            "outcomeStep"
        ].forEach(id => {

            const step =
                document.getElementById(id);


            if (
                step &&
                step.dataset.state === "active"
            ) {

                setStep(
                    id,
                    "error"
                );
            }
        });


    } finally {

        if (runButton) {

            runButton.disabled = false;

            runButton.innerHTML =
                '<span class="button-icon">▶</span> RUN RECOVERY';
        }
    }
}


/* =========================================================
   BATCH SWITCHING
   ========================================================= */

async function handleBatchChange() {

    const batchId =
        getSelectedBatchId();


    if (!batchId) return;


    clearActivityFeed();
    resetPipeline();


    renderCases([]);


    try {

        addActivity(
            `Loading batch ${batchId}...`
        );


        /*
         * Batch switching is intentionally NOT delayed.
         *
         * The pacing is needed for RUN RECOVERY,
         * not for simply changing the selected batch.
         */

        const detection =
            await detectBatch(batchId);


        const metrics =
            await getMetrics(batchId);


        updateMetrics(
            metrics,
            detection.amount_at_risk
        );


        addActivity(
            `Switched to batch ${batchId}.`
        );


    } catch (error) {

        console.error(
            "Batch loading failed:",
            error
        );


        addActivity(
            `Unable to load batch ${batchId}: ${error.message}`,
            "error"
        );
    }
}


/* =========================================================
   EVENT LISTENERS
   ========================================================= */

if (runButton) {

    runButton.addEventListener(
        "click",
        runRecovery
    );
}


if (downloadReportButton) {

    downloadReportButton.addEventListener(
        "click",
        downloadReport
    );
}


if (batchSelect) {

    batchSelect.addEventListener(
        "change",
        handleBatchChange
    );
}


/* =========================================================
   INITIAL DASHBOARD LOAD
   ========================================================= */

async function initializeDashboard() {

    try {

        const health =
            await getHealth();


        if (
            health &&
            health.status === "ok"
        ) {

            addActivity(
                "DunnFlow API connected.",
                "success"
            );
        }


        const batchId =
            getSelectedBatchId();


        if (!batchId) {
            return;
        }


        const detection =
            await detectBatch(batchId);


        const metrics =
            await getMetrics(batchId);


        updateMetrics(
            metrics,
            detection.amount_at_risk
        );


    } catch (error) {

        console.error(
            "Dashboard initialization failed:",
            error
        );


        addActivity(
            "Unable to connect to DunnFlow API.",
            "error"
        );
    }
}


/* =========================================================
   START DASHBOARD
   ========================================================= */

initializeDashboard();