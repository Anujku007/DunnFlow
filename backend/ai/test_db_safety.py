"""Safety guard for database-writing DunnFlow test scripts."""

import os
from pathlib import Path

from backend.data.db import DB_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = (PROJECT_ROOT / "dunnflow.db").resolve()
TEST_DB_DIRECTORY = (PROJECT_ROOT / ".test_dbs").resolve()


def require_isolated_test_db() -> None:
    """Refuse test execution unless an isolated test DB is selected."""
    selected_db = DB_PATH.resolve()

    if os.environ.get("DUNNFLOW_ALLOW_TEST_DB_WRITES") != "1":
        raise RuntimeError(
            "Test blocked: set DUNNFLOW_ALLOW_TEST_DB_WRITES=1 "
            "only when intentionally using an isolated test database."
        )

    if selected_db == DEFAULT_DB_PATH:
        raise RuntimeError(
            f"Test blocked: refusing to modify the application database: "
            f"{selected_db}"
        )

    try:
        selected_db.relative_to(TEST_DB_DIRECTORY)
    except ValueError:
        raise RuntimeError(
            f"Test blocked: database must be inside {TEST_DB_DIRECTORY}; "
            f"selected database is {selected_db}"
        )

    if selected_db.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise RuntimeError(
            f"Test blocked: unexpected test database extension: {selected_db}"
        )

    print(f"TEST DATABASE SAFETY CHECK PASSED: {selected_db}")
