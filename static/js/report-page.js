(function () {
    "use strict";

    const BATCH_ID =
        "benchmark_60_subscription_failures";


    function openReportPage() {
        const url =
            "/reports/" +
            encodeURIComponent(BATCH_ID);

        window.location.href = url;
    }

    function byId(id) {
        return document.getElementById(id);
    }

    function formatINR(paise) {
        const value = Number(paise || 0) / 100;

        return "\u20B9" + value.toLocaleString("en-IN", {
            maximumFractionDigits: 0
        });
    }

    function formatPercent(value) {
        return Number(value || 0).toFixed(1) + "%";
    }

    function setText(id, value) {
        const element = byId(id);

        if (element) {
            element.textContent = value;
        }
    }

    function renderCategoryBreakdown(categories) {
        const container = byId(
            "reportCategoryBreakdown"
        );

        if (!container) return;

        if (!Array.isArray(categories) || !categories.length) {
            container.innerHTML =
                '<div class="report-empty-state">' +
                'No category metrics available.' +
                '</div>';

            return;
        }

        container.innerHTML = categories.map(function (item) {
            const total = Number(item.total || 0);
            const recovered = Number(item.recovered || 0);

            const rate =
                total > 0
                    ? ((recovered / total) * 100).toFixed(1)
                    : "0.0";

            return `
                <div class="report-breakdown-row">
                    <div class="report-breakdown-main">
                        <strong>
                            ${item.failure_category || "unclassified"}
                        </strong>

                        <span>
                            ${recovered} recovered
                            of ${total} cases
                        </span>
                    </div>

                    <div class="report-breakdown-value">
                        ${rate}%
                    </div>
                </div>
            `;
        }).join("");
    }

    function renderActionBreakdown(actions) {
        const container = byId(
            "reportActionBreakdown"
        );

        if (!container) return;

        if (!Array.isArray(actions) || !actions.length) {
            container.innerHTML =
                '<div class="report-empty-state">' +
                'No recovery strategy metrics available.' +
                '</div>';

            return;
        }

        container.innerHTML = actions.map(function (item) {
            const action =
                item.action_type || "unknown";

            const total =
                Number(item.actions || 0);

            const executed =
                Number(item.executed || 0);

            const blocked =
                Number(item.blocked || 0);

            return `
                <div class="report-breakdown-row">
                    <div class="report-breakdown-main">
                        <strong>
                            ${action}
                        </strong>

                        <span>
                            ${total} planned
                            · ${executed} executed
                            · ${blocked} blocked
                        </span>
                    </div>

                    <div class="report-breakdown-value">
                        ${total}
                    </div>
                </div>
            `;
        }).join("");
    }

    function renderMetrics(metrics) {
        if (!metrics) {
            throw new Error(
                "Benchmark metrics response was empty."
            );
        }

        setText(
            "reportRevenueAtRisk",
            formatINR(metrics.historical_amount_at_risk)
        );

        setText(
            "reportRecoveredAmount",
            formatINR(metrics.amount_recovered)
        );

        setText(
            "reportRecoveryRate",
            formatPercent(metrics.recovery_rate_pct)
        );

        setText(
            "reportRecoveredCases",
            String(metrics.recovered_count || 0)
        );

        setText(
            "reportBlockedCases",
            String(metrics.blocked_count || 0)
        );

        setText(
            "reportGuardrailBlocks",
            String(metrics.guardrail_blocks || 0)
        );

        setText(
            "reportManualReviews",
            String(metrics.manual_review_count || 0)
        );

        renderCategoryBreakdown(
            metrics.failure_categories
        );

        renderActionBreakdown(
            metrics.action_metrics
        );
    }

    async function loadMetrics() {
        if (typeof getMetrics !== "function") {
            throw new Error(
                "DunnFlow metrics API is unavailable."
            );
        }

        const metrics = await getMetrics(BATCH_ID);

        renderMetrics(metrics);

        return metrics;
    }

    function downloadReport() {
        const url =
            "/api/batches/" +
            encodeURIComponent(BATCH_ID) +
            "/report";

        window.location.href = url;
    }

    function init() {
        const reportButton =
            byId("openReportInspectorBtn");

        if (reportButton) {
            reportButton.addEventListener(
                "click",
                openReportPage
            );
        }

        const downloadButton =
            byId("downloadReportBtn");

        if (downloadButton) {
            downloadButton.addEventListener(
                "click",
                downloadReport
            );
        }

        loadMetrics().catch(function (error) {
            console.error(
                "DunnFlow report loading failed:",
                error
            );

            const category =
                byId("reportCategoryBreakdown");

            const actions =
                byId("reportActionBreakdown");

            if (category) {
                category.innerHTML =
                    '<div class="report-empty-state">' +
                    'Unable to load benchmark metrics.' +
                    '</div>';
            }

            if (actions) {
                actions.innerHTML =
                    '<div class="report-empty-state">' +
                    'Unable to load recovery strategy metrics.' +
                    '</div>';
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            init
        );
    } else {
        init();
    }

    window.DunnFlowReportPage = {
        loadMetrics,
        downloadReport
    };
})();
