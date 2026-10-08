/*
 * DunnFlow — Audit Trail UI
 *
 * Responsibilities:
 * - Render audit events.
 * - Format audit information for judges/users.
 * - Provide a small presentation API.
 *
 * IMPORTANT:
 * - Uses the centralized read-only audit API only.
 * - No recovery execution.
 * - No policy decisions.
 * - No frontend mode changes.
 * - Never clears live-feed activity items.
 */

(function () {
    "use strict";


    const AUDIT_SELECTORS = [
        "#activityFeed",
        "#auditTrail",
        "#auditLog",
        "[data-audit-trail]"
    ];


    /**
     * Find the audit container used by the current template.
     */
    function getAuditContainer() {
        for (
            const selector of AUDIT_SELECTORS
        ) {
            const element =
                document.querySelector(
                    selector
                );

            if (element) {
                return element;
            }
        }

        return null;
    }


    /**
     * Safely convert a value to display text.
     */
    function displayValue(
        value,
        fallback = "—"
    ) {
        if (
            value === null ||
            value === undefined ||
            value === ""
        ) {
            return fallback;
        }

        return String(value);
    }


    /**
     * Format an audit timestamp.
     */
    function formatTimestamp(
        timestamp
    ) {
        if (!timestamp) {
            return "—";
        }

        const date =
            new Date(timestamp);

        if (
            Number.isNaN(
                date.getTime()
            )
        ) {
            return String(timestamp);
        }

        return date.toLocaleString(
            "en-IN",
            {
                dateStyle: "short",
                timeStyle: "medium"
            }
        );
    }


    /**
     * Create a single audit row.
     */
    function createAuditRow(
        event
    ) {
        const row =
            document.createElement("div");

        row.className =
            "audit-row";

        row.dataset.dunnflowAuditRow =
            "true";


        const stage =
            document.createElement("span");

        stage.className =
            "audit-stage";

        stage.textContent =
            displayValue(
                event.stage
            );


        const action =
            document.createElement("span");

        action.className =
            "audit-action";

        action.textContent =
            displayValue(
                event.action_taken ||
                event.action ||
                event.result
            );


        const category =
            document.createElement("span");

        category.className =
            "audit-category";

        category.textContent =
            displayValue(
                event.failure_category
            );


        const guardrail =
            document.createElement("span");

        guardrail.className =
            "audit-guardrail";

        guardrail.textContent =
            displayValue(
                event.guardrail_hit,
                "—"
            );


        const result =
            document.createElement("span");

        result.className =
            "audit-result";

        result.textContent =
            displayValue(
                event.result
            );


        const timestamp =
            document.createElement("span");

        timestamp.className =
            "audit-timestamp";

        timestamp.textContent =
            formatTimestamp(
                event.timestamp ||
                event.created_at
            );


        row.appendChild(stage);
        row.appendChild(action);
        row.appendChild(category);
        row.appendChild(guardrail);
        row.appendChild(result);
        row.appendChild(timestamp);

        return row;
    }


    /**
     * Clear persisted audit rows only.
     *
     * IMPORTANT:
     * The visible #activityFeed is also used by live-feed.js.
     * Never clear the entire container here.
     */
    function clear() {
        const container =
            getAuditContainer();

        if (!container) {
            return;
        }

        container
            .querySelectorAll(".audit-row")
            .forEach((row) => row.remove());
    }


    /**
     * Render persisted audit events without disturbing the
     * live recovery feed.
     *
     * Audit rows and live activity items intentionally coexist
     * in the same visible container:
     *
     *   .audit-row      -> persisted backend audit history
     *   .activity-item  -> live UI activity
     *
     * Only .audit-row elements are replaced here.
     */
    function render(
        events
    ) {
        const container =
            getAuditContainer();

        if (!container) {
            return;
        }

        /*
         * Remove only previously rendered persisted audit rows.
         * Never clear .activity-item elements owned by live-feed.js.
         */
        container
            .querySelectorAll(".audit-row")
            .forEach((row) => row.remove());

        /*
         * Remove only the previous empty-state marker.
         */
        container
            .querySelectorAll(".audit-empty")
            .forEach((element) => element.remove());

        if (
            !Array.isArray(events) ||
            events.length === 0
        ) {
            const empty =
                document.createElement("div");

            empty.className =
                "audit-empty";

            empty.textContent =
                "No persisted audit events available.";

            container.prepend(empty);

            return;
        }

        /*
         * Newest persisted audit event appears first,
         * while existing live activity remains untouched.
         */
        const fragment =
            document.createDocumentFragment();

        events.forEach((event) => {
            if (!event) {
                return;
            }

            fragment.appendChild(
                createAuditRow(event)
            );
        });

        container.prepend(fragment);
    }


    /**
     * Append one audit event.
     */
    function append(
        event
    ) {
        const container =
            getAuditContainer();

        if (
            !container ||
            !event
        ) {
            return;
        }

        container.appendChild(
            createAuditRow(event)
        );
    }


    /**
     * Load persisted audit history from the backend.
     *
     * This is read-only and only renders server-provided events.
     */
    async function load({
        batchId = null,
        subscriptionId = null,
        invoiceId = null
    } = {}) {

        if (
            !window.DunnFlowAPI ||
            typeof window.DunnFlowAPI.getAuditTrail !==
                "function"
        ) {
            throw new Error(
                "DunnFlow audit API is not available."
            );
        }

        const payload =
            await window.DunnFlowAPI.getAuditTrail({
                batchId,
                subscriptionId,
                invoiceId
            });

        const events =
            payload &&
            Array.isArray(payload.events)
                ? payload.events
                : [];

        render(events);

        return payload;
    }



    /**
     * Public audit UI contract.
     */
    window.DunnFlowAudit = {
        render,
        append,
        clear,
        load,

        formatTimestamp
    };
})();