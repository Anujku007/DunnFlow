from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from backend.data.db import (
    get_batch_run,
    get_batch_metrics,
    get_invoices,
    get_recovery_actions,
    get_audit_log,
)


REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)


def generate_batch_report(batch_id: str) -> str:
    batch = get_batch_run(batch_id)
    metrics = get_batch_metrics(batch_id)
    invoices = get_invoices(batch_id=batch_id)
    actions = get_recovery_actions(batch_id=batch_id)
    audit = get_audit_log(batch_id=batch_id)

    report_path = REPORT_DIR / f"dunnflow_report_{batch_id}.pdf"

    styles = getSampleStyleSheet()

    title_style = styles["Title"]
    heading_style = styles["Heading2"]
    body_style = styles["BodyText"]

    doc = SimpleDocTemplate(
        str(report_path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    story = []

    # ---------------------------------------------------------
    # HEADER
    # ---------------------------------------------------------

    story.append(Paragraph("DUNNFLOW", title_style))
    story.append(
        Paragraph(
            "Autonomous Revenue Recovery Report",
            heading_style,
        )
    )

    story.append(Spacer(1, 10))

    story.append(
        Paragraph(
            f"<b>Batch ID:</b> {batch_id}",
            body_style,
        )
    )

    if batch:
        story.append(
            Paragraph(
                f"<b>Batch Status:</b> {batch.get('status', '-')}",
                body_style,
            )
        )

    story.append(Spacer(1, 15))

    # ---------------------------------------------------------
    # METRICS
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "Recovery Metrics",
            heading_style,
        )
    )

    story.append(Spacer(1, 6))

    metric_data = [
        ["Metric", "Value"],
        [
            "Revenue at Risk",
            f"INR {metrics.get('historical_amount_at_risk', 0) / 100:,.2f}",
        ],
        [
            "Recovered Amount",
            f"INR {metrics.get('amount_recovered', 0) / 100:,.2f}",
        ],
        [
            "Recovery Rate",
            f"{metrics.get('recovery_rate_pct', 0)}%",
        ],
        [
            "Cases In Progress",
            str(metrics.get("in_progress_count", 0)),
        ],
        [
            "Blocked Cases",
            str(metrics.get("blocked_count", 0)),
        ],
        [
            "Manual Review",
            str(metrics.get("manual_review_count", 0)),
        ],
        [
            "Guardrail Blocks",
            str(metrics.get("guardrail_blocks", 0)),
        ],
    ]

    metrics_table = Table(
        metric_data,
        colWidths=[80 * mm, 80 * mm],
    )

    metrics_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#202936"),
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.grey,
                ),
                (
                    "PADDING",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
            ]
        )
    )

    story.append(metrics_table)
    story.append(Spacer(1, 15))

    # ---------------------------------------------------------
    # RECOVERY CASES
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "Recovery Cases",
            heading_style,
        )
    )

    story.append(Spacer(1, 6))

    case_data = [
        [
            "Invoice",
            "Failure",
            "Action",
            "Status",
        ]
    ]

    for invoice in invoices:
        invoice_id = invoice.get("invoice_id", "-")
        failure = invoice.get("failure_category", "-")

        related_actions = [
            action
            for action in actions
            if action.get("invoice_id") == invoice_id
        ]

        if related_actions:
            action = related_actions[-1]

            case_data.append(
                [
                    invoice_id,
                    failure,
                    action.get("action_type", "-"),
                    action.get("status", "-"),
                ]
            )
        else:
            case_data.append(
                [
                    invoice_id,
                    failure,
                    "-",
                    invoice.get("status", "-"),
                ]
            )

    if len(case_data) == 1:
        case_data.append(
            ["-", "-", "-", "No cases"]
        )

    cases_table = Table(
        case_data,
        colWidths=[
            42 * mm,
            35 * mm,
            45 * mm,
            35 * mm,
        ],
    )

    cases_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#202936"),
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.grey,
                ),
                (
                    "PADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
            ]
        )
    )

    story.append(cases_table)
    story.append(Spacer(1, 15))

    # ---------------------------------------------------------
    # AUDIT TRAIL
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "Audit Trail",
            heading_style,
        )
    )

    story.append(Spacer(1, 6))

    audit_data = [
        [
            "Stage",
            "Result",
            "Action",
            "Detail",
        ]
    ]

    for entry in audit:
        audit_data.append(
            [
                entry.get("stage", "-"),
                entry.get("result", "-"),
                entry.get("action_taken", "-"),
                entry.get("detail", "-"),
            ]
        )

    if len(audit_data) == 1:
        audit_data.append(
            ["-", "-", "-", "No audit entries"]
        )

    audit_table = Table(
        audit_data,
        colWidths=[
            25 * mm,
            30 * mm,
            40 * mm,
            62 * mm,
        ],
        repeatRows=1,
    )

    audit_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor("#202936"),
                ),
                (
                    "TEXTCOLOR",
                    (0, 0),
                    (-1, 0),
                    colors.white,
                ),
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.grey,
                ),
                (
                    "PADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
                (
                    "FONTSIZE",
                    (0, 0),
                    (-1, -1),
                    7,
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "TOP",
                ),
            ]
        )
    )

    story.append(audit_table)
    story.append(Spacer(1, 15))

    story.append(
        Paragraph(
            "DunnFlow · Autonomous Revenue Recovery · Synthetic Test Mode",
            body_style,
        )
    )

    doc.build(story)

    return str(report_path)