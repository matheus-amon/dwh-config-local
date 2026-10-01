"""Loads generated CSVs into Postgres so dbt can read them as sources.

dbt runs against the database, not against files, so the raw layer has to land somewhere with
types and constraints. ``COPY`` is used because a million rows through row-by-row INSERT is
minutes of work that COPY does in about a second.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import RAW_TABLES
from .schema import RAW_TABLE_COLUMNS

#: Postgres schema the dbt project declares its sources against.
RAW_SCHEMA = "raw"


def connection_kwargs() -> dict[str, object]:
    """Connection settings, read from the environment.

    ``WAREHOUSE_*`` is what docker-compose.telemetry.yml and .env.telemetry.example define. The
    ``POSTGRES_*`` and ``DBT_*`` spellings are accepted as fallbacks so the generator can be
    pointed at the other Postgres in this repo, or at a managed instance, without code changes.
    """
    user = (
        os.getenv("WAREHOUSE_USER")
        or os.getenv("POSTGRES_USER")
        or os.getenv("DBT_USER")
    )
    password = (
        os.getenv("WAREHOUSE_PASSWORD")
        or os.getenv("POSTGRES_PASSWORD")
        or os.getenv("DBT_PASSWORD")
    )

    missing = [
        name
        for name, value in (
            ("WAREHOUSE_PASSWORD (or POSTGRES_PASSWORD / DBT_PASSWORD)", password),
            ("WAREHOUSE_USER (or POSTGRES_USER / DBT_USER)", user),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"missing {', '.join(missing)} in the environment; "
            "start from .env.telemetry.example"
        )

    return {
        "dbname": os.getenv("WAREHOUSE_DB") or os.getenv("POSTGRES_DB") or "saas_dw",
        "user": user,
        "password": password,
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("WAREHOUSE_PORT") or os.getenv("POSTGRES_PORT", "5434")),
    }


def create_raw_schema(conn) -> None:
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}")


def _ddl(table: str) -> str:
    columns = ",\n    ".join(
        f"{name} {sql_type}" for name, sql_type in RAW_TABLE_COLUMNS[table].items()
    )
    return f"CREATE TABLE {RAW_SCHEMA}.{table} (\n    {columns}\n)"


def ensure_raw_tables(conn, tables: tuple[str, ...] = RAW_TABLES, recreate: bool = False) -> list[str]:
    """Make sure every raw table exists, and start from an empty table.

    The default path creates the table only if it is absent and then TRUNCATEs it. Dropping the
    table instead would cascade to the dbt staging views that read from it, so a plain reload
    would break the warehouse until the next ``dbt build``. ``recreate=True`` exists for the
    other case — a column was added, renamed or retyped — where the existing table is genuinely
    the wrong shape.
    """
    create_raw_schema(conn)
    ensured = []
    for table in tables:
        if recreate:
            conn.execute(f"DROP TABLE IF EXISTS {RAW_SCHEMA}.{table} CASCADE")
            conn.execute(_ddl(table))
        else:
            conn.execute(_ddl(table).replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
            conn.execute(f"TRUNCATE {RAW_SCHEMA}.{table}")
        ensured.append(table)
    return ensured


def copy_csv(conn, table: str, directory: Path) -> int:
    """COPY a generated CSV into its raw table and return the row count."""
    path = Path(directory) / f"{table}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist; run 'telemetry-lab generate' first")

    columns = ", ".join(RAW_TABLE_COLUMNS[table])
    with path.open("rb") as handle:
        with conn.cursor().copy(
            f"COPY {RAW_SCHEMA}.{table} ({columns}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE)"
        ) as copy:
            while chunk := handle.read(1 << 20):
                copy.write(chunk)
    return int(conn.execute(f"SELECT count(*) FROM {RAW_SCHEMA}.{table}").fetchone()[0])


def load(directory: Path, tables: tuple[str, ...] = RAW_TABLES, recreate: bool = False) -> dict[str, int]:
    """Rebuild the raw layer from the CSVs in ``directory``.

    A COPY against a table whose shape no longer matches the CSVs fails loudly rather than
    silently loading a subset, which is the intended behaviour: fix the schema or re-run with
    ``recreate=True``.
    """
    import psycopg

    with psycopg.connect(**connection_kwargs()) as conn:
        ensure_raw_tables(conn, tables, recreate=recreate)
        return {table: copy_csv(conn, table, directory) for table in tables}
