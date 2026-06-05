from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db
from ..core.profiler import full_schema

router = APIRouter(prefix="/sessions", tags=["schema"])


@router.get("/{session_id}/schema")
def get_schema(session_id: str) -> dict:
    if not db.query("SELECT id FROM sessions WHERE id = ?;", (session_id,)):
        raise HTTPException(404, "Session not found")
    return full_schema(session_id)
