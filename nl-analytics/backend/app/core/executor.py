"""Run validated SQL on a session's DuckDB with a timeout and row cap."""
from __future__ import annotations

import threading
from typing import Any

import pandas as pd

from ..config import settings
from .session_manager import open_duckdb


class ExecutionError(Exception):
    pass


def run_sql(session_id: str, sql: str) -> pd.DataFrame:
    con = open_duckdb(session_id, read_only=True)

    timed_out = {"v": False}

    def _interrupt():
        timed_out["v"] = True
        try:
            con.interrupt()
        except Exception:
            pass

    timer = threading.Timer(settings.sql_timeout_seconds, _interrupt)
    timer.daemon = True
    timer.start()
    try:
        df = con.execute(sql).fetchdf()
    except Exception as e:
        if timed_out["v"]:
            raise ExecutionError(
                f"Query exceeded {settings.sql_timeout_seconds}s timeout."
            ) from e
        raise ExecutionError(str(e)) from e
    finally:
        timer.cancel()
        con.close()

    if len(df) > settings.sql_row_limit:
        df = df.head(settings.sql_row_limit)
    return df


def dataframe_to_payload(df: pd.DataFrame, preview_rows: int = 50) -> dict[str, Any]:
    safe = df.head(preview_rows).copy()
    # Normalize timestamps / NaN
    for c in safe.columns:
        if pd.api.types.is_datetime64_any_dtype(safe[c]):
            safe[c] = safe[c].astype(str)
    safe = safe.astype(object).where(safe.notna(), None)
    return {
        "columns": list(df.columns),
        "rows": safe.values.tolist(),
        "total_rows": int(len(df)),
    }
