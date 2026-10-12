(function () {
    "use strict";

    function init() {
        const trigger = document.getElementById("inspectDecisionBtn");

        if (!trigger || trigger.dataset.standaloneInspectionBound === "true") {
            return;
        }

        trigger.dataset.standaloneInspectionBound = "true";

        trigger.addEventListener("click", function () {
            const state = window.DunnFlowState;
            const invoiceId = state && state.invoiceId;

            if (!invoiceId) {
                console.warn("Select a demo invoice before opening AI inspection.");
                alert("Please select a demo case before inspecting its AI decision.");
                return;
            }

            window.location.href =
                "/ai-inspection?invoice_id=" + encodeURIComponent(invoiceId);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
