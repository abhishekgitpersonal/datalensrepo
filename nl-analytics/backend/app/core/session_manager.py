"""Per-session DuckDB + filesystem layout."""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

import duckdb

from ..config import settings


SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_]")


def safe_table_name(filename: str) -> str:
    stem = Path(filename).stem
    name = SAFE_NAME_RE.sub("_", stem).strip("_").lower()
    if not name:
        name = "table"
    if name[0].isdigit():
        name = "t_" + name
    return name[:60]


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def session_dir(session_id: str) -> Path:
    p = settings.storage_path / "sessions" / session_id
    (p / "raw").mkdir(parents=True, exist_ok=True)
    return p


def duckdb_path(session_id: str) -> Path:
    return session_dir(session_id) / "data.duckdb"


def open_duckdb(session_id: str, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(duckdb_path(session_id)), read_only=read_only)
    # Harden: no external file/network access from generated SQL
    try:
        con.execute("SET enable_external_access = false;")
    except duckdb.Error:
        pass
    return con


def delete_session(session_id: str) -> None:
    p = settings.storage_path / "sessions" / session_id
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


def load_csv_into_duckdb(
    session_id: str,
    csv_path: Path,
    table_name: str,
) -> tuple[int, int]:
    """Load a CSV file into the session DuckDB as table_name. Replaces if exists.
    Returns (row_count, col_count)."""
    # Open writable connection (external access allowed only here, briefly)
    con = duckdb.connect(str(duckdb_path(session_id)))
    try:
        t = _qi(table_name)
        con.execute(f"DROP TABLE IF EXISTS {t};")

        # Generic and scalable ingest for arbitrary CSVs:
        # - normalize header names for cleaner SQL
        # - parse common missing-value markers as NULL
        # - cap schema inference scan for large files
        con.execute(
            f"""
            CREATE TABLE {t} AS
            SELECT *
            FROM read_csv_auto(
                ?,
                header = TRUE,
                normalize_names = TRUE,
                sample_size = {int(settings.csv_infer_sample_rows)},
                ignore_errors = TRUE,
                nullstr = ['', 'na', 'n/a', 'null', 'none', 'nan', 'NA', 'N/A', 'NULL', 'None', 'NaN']
            );
            """,
            [str(csv_path)],
        )

        _normalize_missing_strings(con, table_name)
        _try_cast_columns(con, table_name)
        if settings.outlier_clip_enabled:
            _clip_numeric_outliers(con, table_name)

        row_count = con.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
        col_count = len(
            con.execute(f"PRAGMA table_info({t});").fetchall()
        )
        return int(row_count), int(col_count)
    finally:
        con.close()


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_info(con: duckdb.DuckDBPyConnection, table_name: str) -> list[tuple]:
    return con.execute(f"PRAGMA table_info({_qi(table_name)});").fetchall()


def _normalize_missing_strings(con: duckdb.DuckDBPyConnection, table_name: str) -> None:
    """Convert common textual missing markers to NULL in string columns."""
    markers = "('', 'na', 'n/a', 'null', 'none', 'nan')"
    for _, col_name, col_type, *_ in _table_info(con, table_name):
        ctype = (col_type or "").upper()
        if "CHAR" not in ctype and "VARCHAR" not in ctype and "TEXT" not in ctype:
            continue
        c = _qi(col_name)
        t = _qi(table_name)
        con.execute(
            f"""
            UPDATE {t}
            SET {c} = NULL
            WHERE {c} IS NOT NULL
              AND lower(trim(CAST({c} AS VARCHAR))) IN {markers};
            """
        )


def _try_cast_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> None:
    """Cast string columns to numeric/timestamp when parse ratio is high."""
    ratio = float(settings.cleansing_cast_ratio)
    t = _qi(table_name)
    for _, col_name, col_type, *_ in _table_info(con, table_name):
        ctype = (col_type or "").upper()
        if "CHAR" not in ctype and "VARCHAR" not in ctype and "TEXT" not in ctype:
            continue
        c = _qi(col_name)

        non_null = con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE {c} IS NOT NULL"
        ).fetchone()[0]
        if not non_null or int(non_null) < 20:
            continue

        numeric_ok = con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE {c} IS NOT NULL AND TRY_CAST({c} AS DOUBLE) IS NOT NULL"
        ).fetchone()[0]
        if float(numeric_ok) / float(non_null) >= ratio:
            con.execute(
                f"ALTER TABLE {t} ALTER COLUMN {c} SET DATA TYPE DOUBLE USING TRY_CAST({c} AS DOUBLE)"
            )
            continue

        ts_ok = con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE {c} IS NOT NULL AND TRY_CAST({c} AS TIMESTAMP) IS NOT NULL"
        ).fetchone()[0]
        if float(ts_ok) / float(non_null) >= ratio:
            con.execute(
                f"ALTER TABLE {t} ALTER COLUMN {c} SET DATA TYPE TIMESTAMP USING TRY_CAST({c} AS TIMESTAMP)"
            )


def _clip_numeric_outliers(con: duckdb.DuckDBPyConnection, table_name: str) -> None:
    """Winsorize extreme values for floating/decimal columns to reduce skew."""
    t = _qi(table_name)
    lq = float(settings.outlier_clip_lower_q)
    uq = float(settings.outlier_clip_upper_q)
    if not (0.0 <= lq < uq <= 1.0):
        return

    clip_types = ("DOUBLE", "FLOAT", "REAL", "DECIMAL")
    for _, col_name, col_type, *_ in _table_info(con, table_name):
        ctype = (col_type or "").upper()
        if not any(tp in ctype for tp in clip_types):
            continue
        c = _qi(col_name)

        non_null = con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE {c} IS NOT NULL"
        ).fetchone()[0]
        if not non_null or int(non_null) < 200:
            continue

        lo, hi = con.execute(
            f"SELECT quantile_cont({c}, ?), quantile_cont({c}, ?) FROM {t} WHERE {c} IS NOT NULL",
            [lq, uq],
        ).fetchone()
        if lo is None or hi is None or lo >= hi:
            continue

        con.execute(
            f"""
            UPDATE {t}
            SET {c} = CASE
                WHEN {c} < ? THEN ?
                WHEN {c} > ? THEN ?
                ELSE {c}
            END
            WHERE {c} IS NOT NULL;
            """,
            [lo, lo, hi, hi],
        )
