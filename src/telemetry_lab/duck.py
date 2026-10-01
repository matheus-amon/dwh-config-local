"""DuckDB staging layer.

Generators hand over pandas frames; this module puts them through a real relational store with
declared types, primary keys and NOT NULL constraints before anything is written to CSV. That
means a generator bug surfaces as a constraint violation at generation time rather than as a
dbt test failure three repos downstream.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

import duckdb
import pandas as pd

from .schema import RAW_COLUMNS, RAW_DDL


class StagingWarehouse:
    """A thin, disposable DuckDB database used to validate and order raw frames."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._con = duckdb.connect(str(database))

    def __enter__(self) -> "StagingWarehouse":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def create_all(self) -> None:
        for ddl in RAW_DDL.values():
            self._con.execute(ddl)

    def append(self, table: str, frame: pd.DataFrame) -> None:
        """Append one frame, ordered to the declared column list."""
        if frame.empty:
            return
        columns = RAW_COLUMNS[table]
        missing = set(columns) - set(frame.columns)
        if missing:
            raise ValueError(f"{table}: missing columns {sorted(missing)}")
        ordered = frame.loc[:, list(columns)]
        self._con.register("_batch", ordered)
        try:
            self._con.execute(f"INSERT INTO {table} SELECT * FROM _batch")
        finally:
            self._con.unregister("_batch")

    def append_all(self, table: str, frames: Iterable[pd.DataFrame]) -> int:
        total = 0
        for frame in frames:
            self.append(table, frame)
            total += len(frame)
        return total

    def frame(self, table: str, order_by: str | None = None) -> pd.DataFrame:
        sql = f"SELECT * FROM {table}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        return self._con.execute(sql).df()

    def counts(self, tables: Iterable[str]) -> dict[str, int]:
        return {t: int(self._con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in tables}

    def export_csv(self, directory: Path, tables: Iterable[str] | None = None) -> dict[str, Path]:
        """Write each raw table to ``<directory>/<table>.csv``."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        targets = list(tables) if tables is not None else list(RAW_COLUMNS)
        for table in targets:
            key = RAW_COLUMNS[table][0]
            path = directory / f"{table}.csv"
            self._con.execute(
                f"COPY (SELECT {', '.join(RAW_COLUMNS[table])} FROM {table} "
                f"ORDER BY {key}) TO '{path.as_posix()}' (HEADER, DELIMITER ',')"
            )
            written[table] = path
        return written

    def close(self) -> None:
        self._con.close()


def chunked(frame: pd.DataFrame, size: int) -> Iterator[pd.DataFrame]:
    """Yield ``frame`` in slices of at most ``size`` rows."""
    for start in range(0, len(frame), size):
        yield frame.iloc[start : start + size]
