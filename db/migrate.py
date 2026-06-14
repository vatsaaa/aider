"""Run database migrations by executing `db/schema.sql` against AIDER_DATABASE_URL.

This script reads the SQL file and executes it using SQLAlchemy. It is
intended to be run as a standalone command: `python db/migrate.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, text

# When this script is executed as `python db/migrate.py`, Python sets
# `sys.path[0]` to the directory containing the script (db/). That means
# imports like `from core.config import settings` fail because the project
# root is not on the import path. Prepend the repository root so relative
# imports succeed when running the script directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.config import settings


def run_migration(database_url: Optional[str] = None) -> None:
    """Execute the SQL migration script against `database_url`.

    Args:
        database_url: Optional database URL; if None, use `settings.AIDER_DATABASE_URL`.

    Raises:
        RuntimeError: if execution of the SQL script fails.
    """

    db_url = database_url or settings.AIDER_DATABASE_URL
    if not db_url:
        raise RuntimeError("AIDER_DATABASE_URL is not configured")

    sql_path = Path(__file__).resolve().parents[0] / "schema.sql"
    if not sql_path.exists():
        raise RuntimeError(f"Schema file not found: {sql_path}")

    sql = sql_path.read_text()

    engine = create_engine(db_url)
    with engine.begin() as conn:
        driver_conn = conn.connection.driver_connection
        cursor = driver_conn.cursor()
        for statement in _split_sql_statements(sql):
            if engine.dialect.name == "sqlite":
                if statement.upper().startswith("CREATE EXTENSION") or statement.upper().startswith("ALTER TABLE"):
                    continue
                statement = statement.replace("DEFAULT gen_random_uuid()", "")
                statement = statement.replace("CREATE OR REPLACE VIEW", "CREATE VIEW")
                statement = statement.replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP")
                statement = statement.replace("date_trunc('day', created_at)", "date(created_at)")
                statement = statement.replace("ILIKE", "LIKE")
            cursor.execute(statement)
        cursor.close()


def _split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into executable statements.

    The schema file is intentionally simple and does not use semicolons inside
    string literals, so a straightforward split is sufficient here.
    """

    statements = []
    for chunk in sql.split(";"):
        cleaned = chunk.strip()
        if not cleaned:
            continue
        if cleaned.startswith("--"):
            lines = [line for line in cleaned.splitlines() if not line.strip().startswith("--")]
            cleaned = "\n".join(lines).strip()
            if not cleaned:
                continue
        statements.append(cleaned)
    return statements


def main(argv: Optional[list] = None) -> int:
    """CLI entrypoint for running migrations. Returns exit code.

    Args:
        argv: Optional list of arguments; not used currently.
    """

    try:
        run_migration()
        print("Migration completed successfully.")
        return 0
    except Exception as exc:  # pragma: no cover - script runner
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
