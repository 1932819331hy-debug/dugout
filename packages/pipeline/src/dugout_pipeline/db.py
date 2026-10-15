"""DuckDB warehouse: connection, schema bootstrap, idempotent upserts, provenance."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from dugout_verify.ledger import LEDGER_DDL

from dugout_pipeline.http import FetchResult

# Additive, idempotent schema changes. CREATE TABLE IF NOT EXISTS does not add columns to existing tables.
MIGRATIONS = [
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS xg DOUBLE",
    "ALTER TABLE clubs ADD COLUMN IF NOT EXISTS address VARCHAR",
    "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS saves INTEGER",
    "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS influence DOUBLE",
    "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS creativity DOUBLE",
    "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS threat DOUBLE",
    "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS bps INTEGER",
    "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS xgc DOUBLE",
    "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS tackles INTEGER",
    "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS recoveries INTEGER",
    "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS cbi INTEGER",
    "ALTER TABLE player_match_stats ADD COLUMN IF NOT EXISTS defensive_contribution INTEGER",
]


def connect(path: Path | str = ":memory:", read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if read_only:  # models only read the warehouse; no schema bootstrap, no lock against the pipeline
        return duckdb.connect(str(path), read_only=True)
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("SET TimeZone = 'UTC'")
    con.execute(files("dugout_pipeline").joinpath("schema.sql").read_text())
    con.execute(LEDGER_DDL)
    for stmt in MIGRATIONS:  # additive changes for warehouses created by older versions (e.g. CI cache)
        con.execute(stmt)
    return con


def upsert(con: duckdb.DuckDBPyConnection, table: str, rows: Iterable[Mapping[str, Any]]) -> int:
    """INSERT OR REPLACE rows by column name. Columns missing from rows are left NULL."""
    df = pd.DataFrame(list(rows))
    if df.empty:
        return 0
    if pk := primary_key(con, table):  # last row wins for duplicate keys within one batch
        df = df.drop_duplicates(subset=pk, keep="last")
    con.register("_upsert_df", df)
    try:
        con.execute(f"INSERT OR REPLACE INTO {table} BY NAME SELECT * FROM _upsert_df")
    finally:
        con.unregister("_upsert_df")
    return len(df)


def primary_key(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    row = con.execute(
        "SELECT constraint_column_names FROM duckdb_constraints() WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'",
        [table],
    ).fetchone()
    return list(row[0]) if row else []


def provenance_sink(con: duckdb.DuckDBPyConnection):
    def sink(result: FetchResult) -> None:
        con.execute(
            "INSERT OR IGNORE INTO provenance VALUES (?,?,?,?,?,?)",
            [
                hashlib.sha256(result.content).hexdigest(),
                result.source,
                result.url,
                result.status,
                len(result.content),
                result.fetched_at,
            ],
        )

    return sink


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    tables = [
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()
    ]
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in sorted(tables)}
