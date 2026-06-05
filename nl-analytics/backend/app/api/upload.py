from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import db
from ..config import settings
from ..core.data_quality import scan_session
from ..core.semantic_layer import rebuild_semantic_index
from ..core.session_manager import (
    safe_table_name, session_dir, load_csv_into_duckdb,
)

router = APIRouter(prefix="/sessions", tags=["upload"])


def _refresh_data_quality(session_id: str) -> dict:
    """Re-scan the entire session and persist issues. Returns the report."""
    db.execute(
        "DELETE FROM data_quality_issues WHERE session_id = ?;",
        (session_id,),
    )
    report = scan_session(session_id)
    for t in report.get("tables", []):
        for i in t.get("issues", []):
            db.execute(
                """INSERT INTO data_quality_issues
                   (session_id, table_name, column_name, issue_type, severity, count, message, sample)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
                (
                    session_id, i["table"], i.get("column"), i["issue_type"],
                    i["severity"], int(i.get("count") or 0), i["message"],
                    json.dumps(i["sample"]) if i.get("sample") else None,
                ),
            )
    for i in report.get("relationship_issues", []):
        db.execute(
            """INSERT INTO data_quality_issues
               (session_id, table_name, column_name, issue_type, severity, count, message, sample)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
            (
                session_id, i["table"], i.get("column"), i["issue_type"],
                i["severity"], int(i.get("count") or 0), i["message"],
                json.dumps(i["sample"]) if i.get("sample") else None,
            ),
        )
    return report


@router.post("/{session_id}/upload")
async def upload(session_id: str, files: list[UploadFile] = File(...)) -> dict:
    # Verify session
    if not db.query("SELECT id FROM sessions WHERE id = ?;", (session_id,)):
        raise HTTPException(404, "Session not found")

    existing = db.query(
        "SELECT COUNT(*) AS c FROM files WHERE session_id = ?;", (session_id,)
    )[0]["c"]

    sdir = session_dir(session_id)
    uploaded = []
    skipped = []

    for f in files:
        if not f.filename:
            skipped.append({"filename": "", "reason": "missing filename"})
            continue
        if not f.filename.lower().endswith(".csv"):
            skipped.append({"filename": f.filename, "reason": "not a .csv"})
            continue
        if existing + len(uploaded) >= settings.max_files_per_session:
            skipped.append({"filename": f.filename, "reason": "file limit reached"})
            continue

        # Stream to disk while enforcing size. Close the file before handing
        # the path to DuckDB — on Windows the writer must release the handle
        # first or DuckDB hits a sharing violation.
        dest = sdir / "raw" / f.filename
        size = 0
        max_bytes = settings.max_upload_mb * 1024 * 1024
        oversize = False
        with dest.open("wb") as out:
            while chunk := await f.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    oversize = True
                    break
                out.write(chunk)

        if oversize:
            dest.unlink(missing_ok=True)
            skipped.append({"filename": f.filename, "reason": f"exceeds {settings.max_upload_mb} MB"})
            continue

        table = safe_table_name(f.filename)
        try:
            rows, cols = load_csv_into_duckdb(session_id, dest, table)
        except Exception as e:
            dest.unlink(missing_ok=True)
            skipped.append({"filename": f.filename, "reason": f"load failed: {e}"})
            continue
        db.execute(
            """INSERT OR REPLACE INTO files
               (session_id, table_name, original_filename, row_count, col_count)
               VALUES (?, ?, ?, ?, ?);""",
            (session_id, table, f.filename, rows, cols),
        )
        uploaded.append({
            "filename": f.filename, "table_name": table,
            "row_count": rows, "col_count": cols,
        })

    db.execute(
        "UPDATE sessions SET updated_at = datetime('now') WHERE id = ?;",
        (session_id,),
    )
    dq_report = _refresh_data_quality(session_id)
    semantic_summary = rebuild_semantic_index(session_id, dq_report)
    return {
        "uploaded": uploaded,
        "skipped": skipped,
        "data_quality": dq_report.get("summary", {}),
        "semantic_index": semantic_summary,
    }


@router.delete("/{session_id}/files/{table_name}")
def delete_file(session_id: str, table_name: str) -> dict:
    rows = db.query(
        "SELECT original_filename FROM files WHERE session_id=? AND table_name=?;",
        (session_id, table_name),
    )
    if not rows:
        raise HTTPException(404, "File not found")
    fn = rows[0]["original_filename"]

    # Drop the table from DuckDB
    from ..core.session_manager import open_duckdb
    con = open_duckdb(session_id, read_only=False)
    try:
        con.execute(f'DROP TABLE IF EXISTS "{table_name}";')
    finally:
        con.close()

    # Remove from disk
    p = session_dir(session_id) / "raw" / fn
    p.unlink(missing_ok=True)
    db.execute(
        "DELETE FROM files WHERE session_id=? AND table_name=?;",
        (session_id, table_name),
    )
    # Rescan to drop any DQ entries that referenced this table.
    try:
        report = _refresh_data_quality(session_id)
        rebuild_semantic_index(session_id, report)
    except Exception:
        # Non-fatal: deletion succeeded even if scan can't run on empty session.
        pass
    return {"ok": True}
