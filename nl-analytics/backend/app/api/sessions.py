from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from .. import db
from ..core.session_manager import new_session_id, delete_session
from ..models import SessionCreate, SessionOut

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut)
def create_session(body: SessionCreate) -> SessionOut:
    sid = new_session_id()
    db.execute(
        "INSERT INTO sessions (id, name) VALUES (?, ?);",
        (sid, body.name or "New session"),
    )
    row = db.query("SELECT * FROM sessions WHERE id = ?;", (sid,))[0]
    return SessionOut(
        id=row["id"],
        name=row["name"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=list[SessionOut])
def list_sessions() -> list[SessionOut]:
    rows = db.query(
        """
        SELECT s.*,
               (SELECT COUNT(*) FROM files f WHERE f.session_id = s.id) AS file_count,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count
        FROM sessions s
        ORDER BY datetime(s.updated_at) DESC;
        """
    )
    return [
        SessionOut(
            id=r["id"],
            name=r["name"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            file_count=r["file_count"],
            message_count=r["message_count"],
        )
        for r in rows
    ]


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: str) -> SessionOut:
    rows = db.query(
        """
        SELECT s.*,
               (SELECT COUNT(*) FROM files f WHERE f.session_id = s.id) AS file_count,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count
        FROM sessions s WHERE s.id = ?;
        """,
        (session_id,),
    )
    if not rows:
        raise HTTPException(404, "Session not found")
    r = rows[0]
    return SessionOut(
        id=r["id"], name=r["name"],
        created_at=r["created_at"], updated_at=r["updated_at"],
        file_count=r["file_count"], message_count=r["message_count"],
    )


@router.delete("/{session_id}", status_code=204, response_class=Response)
def remove_session(session_id: str) -> Response:
    db.execute("DELETE FROM sessions WHERE id = ?;", (session_id,))
    delete_session(session_id)
    return Response(status_code=204)


@router.get("/{session_id}/history")
def history(session_id: str) -> list[dict]:
    import json
    rows = db.query(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC;",
        (session_id,),
    )
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "role": r["role"],
            "question": r["question"],
            "sql": r["sql"],
            "text": r["text"],
            "chart_spec": json.loads(r["chart_spec"]) if r["chart_spec"] else None,
            "result_preview": json.loads(r["result_preview"]) if r["result_preview"] else None,
            "row_count": r["row_count"],
            "error": r["error"],
            "created_at": r["created_at"],
        })
    return out
