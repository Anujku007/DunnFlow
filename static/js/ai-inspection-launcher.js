(function () {
    "use strict";

    function getInvoiceId() {
        const state = window.DunnFlowState;

        // Prefer an explicitly selected demo invoice.
        if (state) {
            if (typeof state.getSelectedDemoInvoiceId === "function") {
                const selected = state.getSelectedDemoInvoiceId();
                if (selected) return String(selected);
            }

            if (state.invoiceId) return String(state.invoiceId);
        }

        // If no demo invoice is selected, resolve the active batch.
        const batchSelect = document.getElementById("batchSelect");
        const batchId = String(batchSelect?.value || state?.batchId || "");

        const batchInspectionInvoices = {
            "razorpay_isolated_test_001": "inv_razorpay_isolated_001"
        };

        return batchInspectionInvoices[batchId] || "";
    }

    function init() {
        const button = document.getElementById("inspectDecisionBtn");
        if (!button || button.dataset.standaloneLauncherBound === "true") return;

        button.addEventListener("click", function (event) {
            event.preventDefault();

            const invoiceId = getInvoiceId();
            if (!invoiceId) {
                console.warn("DunnFlow inspection: no invoice is selected.");
                window.alert(
                    "Select a demo scenario or the Razorpay Test Mode batch before opening its inspection report."
                );
                return;
            }

            const isRazorpayInvoice = invoiceId.startsWith("inv_rp_demo_");
            const runId = window.DunnFlowState?.runId;

            if (!isRazorpayInvoice && !runId) {
                window.alert("No active synthetic demo run was found. Select a demo scenario and try again.");
                return;
            }

            let url = "/ai-inspection?invoice_id=" + encodeURIComponent(invoiceId);
            if (!isRazorpayInvoice && runId) {
                url += "&run_id=" + encodeURIComponent(runId);
            }
            window.location.assign(url);
        });

        button.dataset.standaloneLauncherBound = "true";
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();

