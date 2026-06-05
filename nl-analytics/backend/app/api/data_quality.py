from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from .. import db
from .upload import _refresh_data_quality

router = APIRouter(prefix="/sessions", tags=["data_quality"])


@router.get("/{session_id}/data_quality")
def get_data_quality(session_id: str) -> dict:
    if not db.query("SELECT id FROM sessions WHERE id = ?;", (session_id,)):
        raise HTTPException(404, "Session not found")
    rows = _load_issues(session_id)
    # Lazy backfill: if this session was uploaded before the DQ layer existed
    # there will be tables on disk but no persisted issues. Run the scanner
    # once on demand so the UI is useful without forcing a re-upload.
    if not rows:
        has_files = db.query(
            "SELECT 1 FROM files WHERE session_id = ? LIMIT 1;", (session_id,),
        )
        if has_files:
            try:
                _refresh_data_quality(session_id)
                rows = _load_issues(session_id)
            except Exception as e:
                raise HTTPException(500, f"Data quality scan failed: {e}")
    return _to_response(rows)


@router.post("/{session_id}/data_quality/refresh")
def refresh_data_quality(session_id: str) -> dict:
    if not db.query("SELECT id FROM sessions WHERE id = ?;", (session_id,)):
        raise HTTPException(404, "Session not found")
    try:
        _refresh_data_quality(session_id)
    except Exception as e:
        raise HTTPException(500, f"Data quality scan failed: {e}")
    return _to_response(_load_issues(session_id))


def _load_issues(session_id: str):
    return db.query(
        """SELECT table_name, column_name, issue_type, severity, count, message, sample
           FROM data_quality_issues
           WHERE session_id = ?
           ORDER BY CASE severity
                       WHEN 'ERROR' THEN 0
                       WHEN 'WARN'  THEN 1
                       WHEN 'INFO'  THEN 2
                       ELSE 9 END,
                    count DESC, table_name, column_name;""",
        (session_id,),
    )


def _to_response(rows) -> dict:
    issues = []
    summary = {"errors": 0, "warnings": 0, "infos": 0}
    for r in rows:
        sample = json.loads(r["sample"]) if r["sample"] else None
        issues.append({
            "table": r["table_name"],
            "column": r["column_name"],
            "issue_type": r["issue_type"],
            "severity": r["severity"],
            "count": r["count"],
            "message": r["message"],
            "sample": sample,
        })
        if r["severity"] == "ERROR":
            summary["errors"] += 1
        elif r["severity"] == "WARN":
            summary["warnings"] += 1
        else:
            summary["infos"] += 1
    return {"summary": summary, "issues": issues}
