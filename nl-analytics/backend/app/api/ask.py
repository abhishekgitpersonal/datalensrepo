from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from .. import db
from ..config import settings
from ..core.chart_picker import pick_chart
from ..core.executor import ExecutionError, dataframe_to_payload, run_sql
from ..core.profiler import full_schema
from ..core.semantic_layer import (
    fetch_similar_sql_examples,
    plan_schema_for_question,
    record_successful_sql,
)
from ..core.sql_intent_guard import find_intent_violations
from ..core.sql_validator import (
    SqlValidationError, extract_sql_from_llm_output, validate_and_prepare,
)
from ..llm.ollama_client import OllamaError, generate, generate_stream
from ..llm.prompts import (
    NARRATE_SYSTEM, SQL_SYSTEM, build_narration_prompt, build_sql_fix_prompt,
    build_deterministic_narration, build_sql_prompt, filter_history_for_sql,
    focus_schema_for_question, narration_is_grounded,
)
from ..models import AskRequest

router = APIRouter(prefix="/sessions", tags=["ask"])
log = logging.getLogger("app.ask")


def _sse(event: str, data) -> dict:
    return {"event": event, "data": json.dumps(data, default=str)}


async def _ask_stream(session_id: str, question: str, request: Request) -> AsyncIterator[dict]:
    t0 = time.time()

    # 1. Persist user message
    user_msg_id = db.execute(
        "INSERT INTO messages (session_id, role, question) VALUES (?, 'user', ?);",
        (session_id, question),
    )
    yield _sse("user_message", {"id": user_msg_id, "question": question})

    # 2. Schema + history
    try:
        schema = full_schema(session_id)
    except Exception as e:
        err = f"Could not load schema: {e}"
        _persist_error(session_id, err)
        yield _sse("error", {"message": err})
        return

    if not schema["tables"]:
        err = "No tables in this session. Upload at least one CSV first."
        _persist_error(session_id, err)
        yield _sse("error", {"message": err})
        return

    history_rows = db.query(
        "SELECT role, question, text, sql FROM messages "
        "WHERE session_id = ? AND id < ? ORDER BY id ASC;",
        (session_id, user_msg_id),
    )
    history = [dict(r) for r in history_rows]
    sql_history = filter_history_for_sql(history)

    allowed_tables = {t["name"] for t in schema["tables"]}
    table_columns = {
        t["name"]: {c["name"] for c in t["columns"]}
        for t in schema["tables"]
    }
    relationships = schema.get("relationships", [])

    # Query-time planner: narrow schema using semantic index, then apply
    # existing lexical focus pass for additional prompt compression.
    plan = plan_schema_for_question(session_id, question, schema)
    focused_schema = focus_schema_for_question(question, plan["schema"])
    planner_notes = plan.get("notes", [])
    few_shot_examples = fetch_similar_sql_examples(schema, question, max_examples=3)

    # Pull persisted DQ warnings (top-N severity-ordered) for prompt context.
    dq_rows = db.query(
        """SELECT severity, message FROM data_quality_issues
           WHERE session_id = ?
           ORDER BY CASE severity
                       WHEN 'ERROR' THEN 0
                       WHEN 'WARN'  THEN 1
                       WHEN 'INFO'  THEN 2
                       ELSE 9 END,
                    count DESC LIMIT 8;""",
        (session_id,),
    )
    dq_warnings = [f"[{r['severity']}] {r['message']}" for r in dq_rows]

    async def disconnected() -> bool:
        return await request.is_disconnected()

    # 3. Generate SQL (start with fast model; retries escalate to strong model)
    yield _sse("status", {"stage": "generating_sql", "model": settings.ollama_sql_fast_model})
    if await disconnected():
        return
    sql_prompt = build_sql_prompt(
        question,
        focused_schema,
        sql_history,
        dq_warnings=dq_warnings,
        planner_notes=planner_notes,
        few_shot_examples=few_shot_examples,
    )
    try:
        raw = await generate(
            sql_prompt,
            model=settings.ollama_sql_fast_model,
            system=SQL_SYSTEM,
            json_mode=True,
            temperature=0.1,
        )
    except OllamaError as e:
        _persist_error(session_id, str(e))
        yield _sse("error", {"message": f"LLM error: {e}"})
        return

    if await disconnected():
        return

    sql_text = extract_sql_from_llm_output(raw)
    if not sql_text:
        msg = "Model returned no SQL. Try rephrasing the question."
        _persist_error(session_id, msg)
        yield _sse("error", {"message": msg})
        return

    # 4. Validate + execute. On failure, retry up to MAX_RETRIES times with the
    #    strong model (hybrid escalation: fast first, then powerful).
    safe_sql: str | None = None
    df = None
    last_error: str | None = None
    last_attempted_sql = sql_text
    log.info(
        "ask: first SQL attempt (model=%s): %s",
        settings.ollama_sql_fast_model, sql_text,
    )
    MAX_RETRIES = 2  # total of up to 3 attempts (1 initial + 2 retries)
    for attempt in range(MAX_RETRIES + 1):
        intent_issues = find_intent_violations(question, last_attempted_sql)
        if intent_issues:
            last_error = "intent: " + " | ".join(intent_issues)
            safe_sql = None
        else:
            try:
                safe_sql = validate_and_prepare(
                    last_attempted_sql,
                    allowed_tables,
                    settings.sql_row_limit,
                    table_columns=table_columns,
                    relationships=relationships,
                )
            except SqlValidationError as e:
                last_error = f"validation: {e}"
                safe_sql = None
            else:
                if await disconnected():
                    return
                yield _sse("sql", {"sql": safe_sql})
                yield _sse("status", {"stage": "executing"})
                try:
                    df = run_sql(session_id, safe_sql)
                    last_error = None
                    break
                except ExecutionError as e:
                    last_error = f"execution: {e}"
                    df = None

        # Failed. If we still have a retry left, escalate to the strong model.
        if attempt < MAX_RETRIES:
            log.warning(
                "ask: attempt %d failed (%s); escalating to %s",
                attempt + 1, last_error, settings.ollama_sql_model,
            )
            yield _sse(
                "status",
                {"stage": "retrying_sql", "model": settings.ollama_sql_model},
            )
            fix_prompt = build_sql_fix_prompt(
                question, focused_schema, last_attempted_sql, last_error or "unknown error",
                dq_warnings=dq_warnings,
            )
            try:
                raw = await generate(
                    fix_prompt,
                    model=settings.ollama_sql_model,  # strong model on retry
                    system=SQL_SYSTEM,
                    json_mode=True,
                    temperature=0.4,  # higher temp on retry to diverge from the bad answer
                )
            except OllamaError as e:
                msg = f"SQL retry failed: {e}"
                _persist_error(session_id, msg, sql=last_attempted_sql)
                yield _sse("error", {"message": msg, "sql": last_attempted_sql})
                return
            fixed = extract_sql_from_llm_output(raw)
            if not fixed:
                msg = f"Model could not fix the SQL. {last_error}"
                _persist_error(session_id, msg, sql=last_attempted_sql)
                yield _sse("error", {"message": msg, "sql": last_attempted_sql})
                return
            log.info(
                "ask: retry SQL attempt (model=%s): %s",
                settings.ollama_sql_model, fixed,
            )
            last_attempted_sql = fixed
            if await disconnected():
                return

    if df is None or safe_sql is None:
        msg = f"SQL failed after retry: {last_error}"
        _persist_error(session_id, msg, sql=last_attempted_sql)
        yield _sse("error", {"message": msg, "sql": last_attempted_sql})
        return

    # Learning loop: store successful NL->SQL pairs by dataset signature
    # for future few-shot reuse. Non-fatal if persistence fails.
    try:
        record_successful_sql(schema, question, safe_sql)
    except Exception:
        pass

    payload = dataframe_to_payload(df)
    if await disconnected():
        return
    yield _sse("result", payload)

    # 6. Chart
    chart = pick_chart(df)
    if chart:
        if await disconnected():
            return
        yield _sse("chart", chart)

    # 7. Narration — buffer silently, validate, then emit a single verified text event.
    # This prevents the jarring swap the user sees when streamed text gets replaced
    # by the deterministic fallback. The "narrating…" status indicator runs while
    # we buffer, and the final clean answer appears all at once.
    yield _sse("status", {"stage": "narrating"})
    if await disconnected():
        return
    narration_prompt = build_narration_prompt(
        question, safe_sql, payload["columns"], payload["rows"], payload["total_rows"],
        dq_warnings=dq_warnings,
    )
    chunks: list[str] = []
    try:
        async for tok in generate_stream(
            narration_prompt,
            model=settings.ollama_narrate_model,
            system=NARRATE_SYSTEM,
            temperature=0.3,
        ):
            if await disconnected():
                return
            chunks.append(tok)
            # Do NOT stream text_delta to the client. Buffer silently so the
            # grounding check can run before the user sees any text, eliminating
            # the visual swap where good streaming text gets overwritten.
    except OllamaError as e:
        yield _sse("warning", {"message": f"Narration failed: {e}"})

    narration = "".join(chunks).strip()
    grounded = bool(narration) and narration_is_grounded(
        narration,
        question,
        payload["columns"],
        payload["rows"],
        payload["total_rows"],
    )
    if (not narration) or (not grounded):
        if await disconnected():
            return
        narration = build_deterministic_narration(
            question,
            payload["columns"],
            payload["rows"],
            payload["total_rows"],
        )
        yield _sse("text", {"text": narration, "replaced": True})
    else:
        if await disconnected():
            return
        yield _sse("text", {"text": narration, "replaced": False})

    # 8. Persist assistant message
    msg_id = db.execute(
        """INSERT INTO messages
           (session_id, role, sql, text, chart_spec, result_preview, row_count)
           VALUES (?, 'assistant', ?, ?, ?, ?, ?);""",
        (
            session_id,
            safe_sql,
            narration,
            json.dumps(chart) if chart else None,
            json.dumps(payload),
            payload["total_rows"],
        ),
    )
    db.execute(
        "UPDATE sessions SET updated_at = datetime('now') WHERE id = ?;",
        (session_id,),
    )

    yield _sse("done", {
        "id": msg_id,
        "elapsed_ms": int((time.time() - t0) * 1000),
    })


def _persist_error(session_id: str, message: str, sql: str | None = None) -> None:
    db.execute(
        """INSERT INTO messages (session_id, role, error, sql)
           VALUES (?, 'assistant', ?, ?);""",
        (session_id, message, sql),
    )


@router.post("/{session_id}/ask")
async def ask(session_id: str, body: AskRequest, request: Request):
    if not db.query("SELECT id FROM sessions WHERE id = ?;", (session_id,)):
        raise HTTPException(404, "Session not found")
    return EventSourceResponse(_ask_stream(session_id, body.question, request))
