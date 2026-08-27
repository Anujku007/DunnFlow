"""
DunnFlow recovery scheduler.

Responsibility
--------------
Select recovery actions whose scheduled time has arrived.

This is intentionally a lightweight scheduler for the buildathon.

It does NOT:
    - make recovery decisions
    - execute payments
    - mark revenue as recovered

It only answers:

    "Which previously planned recovery actions are due now?"

Real-world behavior:
    decision_engine
        -> creates planned action with scheduled_for
        -> scheduler waits until due
        -> execution.py executes it

Demo behavior:
    A controllable `as_of` timestamp allows the demo to fast-forward time
    without actually waiting hours or days.

Examples:
    bank timeout retry:
        scheduled for T+1 hour

    insufficient funds retry:
        scheduled for T+1 day

The demo can pass `as_of = scheduled_for` to execute these actions
immediately while preserving the correct scheduled timestamp.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.data.db import (
    get_recovery_actions,
)
from backend.data.db import (
    get_recovery_actions,
)


# ===========================================================================
# TIME HELPERS
# ===========================================================================

def _now() -> datetime:
    """Return current UTC time."""
    return datetime.now(timezone.utc)


def _parse_timestamp(
    value: str | None,
) -> datetime | None:
    """Parse an ISO timestamp into UTC."""

    if not value:
        return None

    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


# ===========================================================================
# DUE ACTION LOGIC
# ===========================================================================

def is_action_due(
    action: dict,
    *,
    as_of: datetime | None = None,
) -> bool:
    """
    Return True if a planned action is currently due.

    Rules:
        - action must have status == "planned"
        - action must have a valid scheduled_for timestamp
        - scheduled_for <= as_of
    """

    if action.get("status") != "planned":
        return False

    scheduled_for = _parse_timestamp(
        action.get("scheduled_for")
    )

    if scheduled_for is None:
        return False

    current_time = as_of or _now()

    if current_time.tzinfo is None:
        current_time = current_time.replace(
            tzinfo=timezone.utc
        )

    current_time = current_time.astimezone(
        timezone.utc
    )

    return scheduled_for <= current_time


def get_due_actions(
    batch_id: str,
    *,
    as_of: datetime | None = None,
) -> list[dict]:
    """
    Return all planned recovery actions whose scheduled time has arrived.
    """

    planned_actions = get_recovery_actions(
        batch_id=batch_id,
        status="planned",
    )

    due_actions = [
        action
        for action in planned_actions
        if is_action_due(
            action,
            as_of=as_of,
        )
    ]

    # Earliest due action first.
    due_actions.sort(
        key=lambda action: (
            action.get("scheduled_for")
            or "",
            action.get("action_id", 0),
        )
    )

    return due_actions


# ===========================================================================
# DEMO CLOCK
# ===========================================================================

def get_demo_time_for_action(
    action: dict,
) -> datetime:
    """
    Return a demo timestamp that makes the supplied action due.

    This is NOT altering the action's scheduled time.

    Example:
        action scheduled for tomorrow
        -> demo execution time = tomorrow

    This lets the pitch video demonstrate scheduled workflows instantly.
    """

    scheduled_for = _parse_timestamp(
        action.get("scheduled_for")
    )

    if scheduled_for is None:
        return _now()

    return scheduled_for


# ===========================================================================
# BATCH SCHEDULER
# ===========================================================================

def schedule_batch(
    batch_id: str,
    *,
    as_of: datetime | None = None,
) -> dict:
    """
    Inspect a batch and return its currently due actions.

    Nothing is executed here.
    """

    current_time = as_of or _now()

    planned_actions = get_recovery_actions(
        batch_id=batch_id,
        status="planned",
    )

    due_actions = [
        action
        for action in planned_actions
        if is_action_due(
            action,
            as_of=current_time,
        )
    ]

    not_due_actions = [
        action
        for action in planned_actions
        if not is_action_due(
            action,
            as_of=current_time,
        )
    ]

    return {
        "batch_id": batch_id,
        "as_of": current_time.isoformat(
            timespec="seconds"
        ),
        "planned_count": len(planned_actions),
        "due_count": len(due_actions),
        "not_due_count": len(not_due_actions),
        "due_actions": due_actions,
        "not_due_actions": not_due_actions,
    }

def run_demo_stage(
    batch_id: str,
    stage: str,
) -> dict:
    """
    Return due actions for a deterministic benchmark stage.

    Supported stages:

        now
        one_hour
        one_day

    No action is executed here.
    """

    timestamps = get_batch_demo_timestamps(
        batch_id
    )

    stage_times = {
        "now": timestamps["now"],
        "one_hour": timestamps["one_hour"],
        "one_day": timestamps["one_day"],
    }

    if stage not in stage_times:
        raise ValueError(
            "Unknown demo stage. "
            "Use 'now', 'one_hour', or 'one_day'."
        )

    demo_time = stage_times[
        stage
    ]

    report = schedule_batch(
        batch_id,
        as_of=demo_time,
    )

    return {
        **report,
        "demo_stage": stage,
        "demo_time": demo_time.isoformat(
            timespec="seconds"
        ),
        "batch_started_at": timestamps[
            "batch_started_at"
        ].isoformat(
            timespec="seconds"
        ),
    }

def get_batch_demo_timestamps(batch_id: str) -> dict:
    """
    Calculate deterministic demo timestamps anchored to the batch start time.

    The demo clock is based on:

        batch.started_at = T0

    Therefore:

        now      = T0
        one_hour = T0 + 1 hour
        one_day  = T0 + 24 hours

    This prevents the benchmark timeline from changing depending on when the
    developer happens to run the command.

    No database timestamps are modified.
    """

    from datetime import timedelta

    from backend.data.db import get_batch_run

    batch = get_batch_run(
        batch_id
    )

    if not batch:
        raise ValueError(
            f"Batch '{batch_id}' does not exist."
        )

    batch_start = _parse_timestamp(
        batch.get("started_at")
    )

    if batch_start is None:
        raise ValueError(
            f"Batch '{batch_id}' has an invalid started_at timestamp."
        )

    return {
        "now": batch_start,
        "first_due": batch_start,
        "one_hour": batch_start + timedelta(hours=1),
        "one_day": batch_start + timedelta(days=1),
        "batch_started_at": batch_start,
    }


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    from backend.data.db import list_batch_runs

    batches = list_batch_runs(
        limit=1
    )

    if not batches:
        print("No batch runs found.")
        raise SystemExit(1)

    batch_id = batches[0]["batch_id"]

    # ---------------------------------------------------------------
    # Real current-time check
    # ---------------------------------------------------------------

    report = schedule_batch(
        batch_id
    )

    print()
    print("=" * 64)
    print("DUNNFLOW SCHEDULER")
    print("=" * 64)
    print(
        f"Batch ID:             {report['batch_id']}"
    )
    print(
        f"Current time:         {report['as_of']}"
    )
    print(
        f"Planned actions:      {report['planned_count']}"
    )
    print(
        f"Due now:              {report['due_count']}"
    )
    print(
        f"Not due yet:          {report['not_due_count']}"
    )

    print()
    print("Due actions:")

    for action in report["due_actions"]:
        print(
            f"  #{action['action_id']} "
            f"{action['action_type']} "
            f"invoice={action.get('invoice_id')}"
        )

    print()
    print("=" * 64)