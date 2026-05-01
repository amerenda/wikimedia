import os
from pathlib import Path

import psycopg


def get_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return dsn


def apply_schema() -> None:
    schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
    sql = schema_path.read_text()
    with psycopg.connect(get_dsn()) as conn:
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
