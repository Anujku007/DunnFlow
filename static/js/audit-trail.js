/*
 * DunnFlow — Audit Trail UI
 *
 * Responsibilities:
 * - Render audit events.
 * - Format audit information for judges/users.
 * - Provide a small presentation API.
 *
 * IMPORTANT:
 * - No API calls.
 * - No recovery execution.
 * - No policy decisions.
 * - No frontend mode changes.
 */

(function () {
    "use strict";


    const AUDIT_SELECTORS = [
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
     * Clear the audit trail.
     */
    function clear() {
        const container =
            getAuditContainer();

        if (!container) {
            return;
        }

        container.innerHTML = "";
    }


    /**
     * Render audit events.
     */
    function render(
        events
    ) {
        const container =
            getAuditContainer();

        if (!container) {
            return;
        }

        container.innerHTML = "";

        if (
            !Array.isArray(events) ||
            events.length === 0
        ) {
            const empty =
                document.createElement("div");

            empty.className =
                "audit-empty";

            empty.textContent =
                "No audit events available.";

            container.appendChild(
                empty
            );

            return;
        }


        events.forEach((event) => {
            if (!event) {
                return;
            }

            container.appendChild(
                createAuditRow(event)
            );
        });
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
     * Public audit UI contract.
     */
    window.DunnFlowAudit = {
        render,
        append,
        clear,

        formatTimestamp
    };
})();