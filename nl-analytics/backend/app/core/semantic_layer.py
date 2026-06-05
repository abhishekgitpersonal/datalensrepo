"""Semantic layer: upload-time metadata indexing + query-time planning + NL->SQL memory."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

import sqlglot
from sqlglot import exp

from .. import db
from .profiler import full_schema
from .sql_intent_guard import find_intent_violations

TOKEN_RE = re.compile(r"[a-z0-9_]+")


def dataset_signature(schema: dict[str, Any]) -> str:
    """Create a stable signature for a dataset shape (tables/columns/types)."""
    normalized: list[dict[str, Any]] = []
    for table in sorted(schema.get("tables", []), key=lambda t: t.get("name", "")):
        cols = sorted(
            [
                {
                    "name": str(c.get("name", "")).lower(),
                    "type": str(c.get("type", "")).lower(),
                }
                for c in table.get("columns", [])
            ],
            key=lambda c: c["name"],
        )
        normalized.append({"table": str(table.get("name", "")).lower(), "columns": cols})

    payload = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def rebuild_semantic_index(session_id: str, dq_report: dict[str, Any] | None = None) -> dict[str, int]:
    """Rebuild semantic index rows for a session from schema + DQ signals."""
    schema = full_schema(session_id)
    dq_map = _dq_severity_map(session_id, dq_report)

    db.execute("DELETE FROM semantic_index WHERE session_id = ?;", (session_id,))

    row_count = 0
    for table in schema.get("tables", []):
        tname = table["name"]
        t_sev = dq_map.get((tname, ""))

        db.execute(
            """INSERT INTO semantic_index
               (session_id, table_name, column_name, data_type, role, tags, dq_severity, updated_at)
               VALUES (?, ?, NULL, NULL, ?, ?, ?, datetime('now'));""",
            (
                session_id,
                tname,
                "dimension",
                json.dumps(sorted(_table_tags(tname))),
                t_sev,
            ),
        )
        row_count += 1

        for col in table.get("columns", []):
            cname = col.get("name", "")
            ctype = str(col.get("type", ""))
            role = _column_role(cname, ctype)
            tags = sorted(_column_tags(tname, cname, ctype, role))
            sev = dq_map.get((tname, cname), t_sev)
            db.execute(
                """INSERT INTO semantic_index
                   (session_id, table_name, column_name, data_type, role, tags, dq_severity, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'));""",
                (session_id, tname, cname, ctype, role, json.dumps(tags), sev),
            )
            row_count += 1

    return {"semantic_rows": row_count, "tables": len(schema.get("tables", []))}


def plan_schema_for_question(
    session_id: str,
    question: str,
    schema: dict[str, Any],
    max_tables: int = 4,
) -> dict[str, Any]:
    """Return a narrowed schema + planner notes based on semantic index relevance."""
    tables = schema.get("tables", [])
    if len(tables) <= max_tables:
        return {"schema": schema, "notes": []}

    tokens = _tokens(question)
    if not tokens:
        return {"schema": schema, "notes": []}

    rows = db.query(
        """SELECT table_name, column_name, role, tags, dq_severity
           FROM semantic_index WHERE session_id = ?;""",
        (session_id,),
    )
    if not rows:
        return {"schema": schema, "notes": []}

    score_by_table: dict[str, float] = defaultdict(float)
    evidence_by_table: dict[str, list[str]] = defaultdict(list)

    wants_time = bool(tokens & {"trend", "month", "monthly", "year", "quarter", "time", "over", "period"})
    wants_metric = bool(tokens & {"revenue", "sales", "amount", "count", "total", "sum", "avg", "average", "top", "highest", "lowest"})

    for r in rows:
        table_name = r["table_name"]
        column_name = r["column_name"] or ""
        role = (r["role"] or "dimension").lower()
        tag_list = _safe_json_list(r["tags"])
        blob_tokens = set(_tokens(" ".join([table_name, column_name, " ".join(tag_list)])))

        overlap = tokens & blob_tokens
        if not overlap:
            continue

        base = float(len(overlap))
        if role == "date" and wants_time:
            base += 2.5
        if role == "metric" and wants_metric:
            base += 1.8
        if role == "identifier":
            base -= 0.3

        sev = (r["dq_severity"] or "").upper()
        if sev == "ERROR":
            base *= 0.9

        score_by_table[table_name] += base
        if column_name:
            evidence_by_table[table_name].append(f"{column_name} ({role})")

    if not score_by_table:
        return {"schema": schema, "notes": []}

    ranked = sorted(score_by_table.items(), key=lambda x: (-x[1], x[0]))
    selected = {name for name, _ in ranked[:max_tables]}

    # Include direct relationship neighbors to preserve joinability.
    for rel in schema.get("relationships", []):
        src = rel.get("from_table")
        dst = rel.get("to_table")
        if src in selected and len(selected) < max_tables + 1:
            selected.add(dst)
        if dst in selected and len(selected) < max_tables + 1:
            selected.add(src)

    narrowed_tables = [t for t in tables if t.get("name") in selected]
    narrowed_rels = [
        r for r in schema.get("relationships", [])
        if r.get("from_table") in selected and r.get("to_table") in selected
    ]

    notes: list[str] = []
    for table_name, score in ranked[:max_tables]:
        if table_name not in selected:
            continue
        ev = ", ".join(evidence_by_table.get(table_name, [])[:3])
        notes.append(f"Selected table {table_name} (score {score:.1f}) based on: {ev}")

    return {
        "schema": {**schema, "tables": narrowed_tables, "relationships": narrowed_rels},
        "notes": notes,
    }


def fetch_similar_sql_examples(
    schema: dict[str, Any],
    question: str,
    max_examples: int = 3,
) -> list[dict[str, str]]:
    """Fetch similar successful NL->SQL examples for the same dataset signature."""
    sig = dataset_signature(schema)
    candidates = db.query(
        """SELECT id, question, sql, success_count
           FROM nl_sql_memory
           WHERE dataset_signature = ?
           ORDER BY success_count DESC, last_used_at DESC
           LIMIT 80;""",
        (sig,),
    )
    if not candidates:
        return []

    q_tokens = _tokens(question)
    scored: list[tuple[float, int, str, str]] = []
    for row in candidates:
        # Ignore historically stored examples that are now known to be
        # semantically invalid for the question they answered.
        if find_intent_violations(row["question"], row["sql"]):
            continue
        c_tokens = _tokens(row["question"])
        if not c_tokens:
            continue
        overlap = len(q_tokens & c_tokens)
        if overlap == 0:
            continue
        union = len(q_tokens | c_tokens) or 1
        jaccard = overlap / union
        score = jaccard + (0.05 * min(int(row["success_count"]), 10))
        scored.append((score, int(row["id"]), row["question"], row["sql"]))

    scored.sort(key=lambda x: (-x[0], x[1]))
    picked = scored[:max_examples]
    for _score, row_id, _q, _sql in picked:
        db.execute(
            "UPDATE nl_sql_memory SET last_used_at = datetime('now') WHERE id = ?;",
            (row_id,),
        )

    return [{"question": q, "sql": sql} for _s, _id, q, sql in picked]


def record_successful_sql(schema: dict[str, Any], question: str, sql: str) -> None:
    """Persist a successful NL->SQL mapping for future few-shot reuse."""
    if not question.strip() or not sql.strip():
        return

    sig = dataset_signature(schema)
    tables_json = json.dumps(sorted(_extract_tables_from_sql(sql)))

    db.execute(
        """INSERT INTO nl_sql_memory (dataset_signature, question, sql, tables_json, success_count)
           VALUES (?, ?, ?, ?, 1)
           ON CONFLICT(dataset_signature, question, sql)
           DO UPDATE SET
             success_count = success_count + 1,
             last_used_at = datetime('now');""",
        (sig, question.strip(), sql.strip(), tables_json),
    )

    # Keep memory bounded per dataset signature.
    db.execute(
        """DELETE FROM nl_sql_memory
           WHERE id IN (
               SELECT id FROM nl_sql_memory
               WHERE dataset_signature = ?
               ORDER BY last_used_at DESC
               LIMIT -1 OFFSET 400
           );""",
        (sig,),
    )


def _column_role(name: str, ctype: str) -> str:
    n = str(name).lower()
    t = str(ctype).lower()

    if any(k in t for k in ["date", "time", "timestamp"]) or any(k in n for k in ["date", "month", "year", "time"]):
        return "date"
    if any(k in t for k in ["int", "double", "float", "decimal", "numeric", "real"]):
        return "metric"
    if n == "id" or n.endswith("_id"):
        return "identifier"
    return "dimension"


def _table_tags(table_name: str) -> set[str]:
    tags = set(_tokens(table_name))
    if table_name.lower().endswith("s"):
        tags.add(table_name.lower()[:-1])
    return tags


def _column_tags(table_name: str, col_name: str, ctype: str, role: str) -> set[str]:
    tags = set(_tokens(f"{table_name} {col_name} {ctype} {role}"))
    lower = col_name.lower()
    if "amount" in lower or "revenue" in lower or "sales" in lower:
        tags.update({"revenue", "sales", "amount", "metric"})
    if "count" in lower or lower.startswith("num_"):
        tags.update({"count", "volume", "metric"})
    if any(k in lower for k in ["date", "month", "year", "time"]):
        tags.update({"trend", "time", "period", "date"})
    return tags


def _dq_severity_map(
    session_id: str,
    dq_report: dict[str, Any] | None,
) -> dict[tuple[str, str], str]:
    order = {"": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
    result: dict[tuple[str, str], str] = {}

    def _set(key: tuple[str, str], sev: str) -> None:
        current = result.get(key, "")
        if order.get(sev, 0) >= order.get(current, 0):
            result[key] = sev

    # Prefer persisted DQ issues (works even if report is not passed).
    rows = db.query(
        "SELECT table_name, column_name, severity FROM data_quality_issues WHERE session_id = ?;",
        (session_id,),
    )
    for r in rows:
        _set((r["table_name"], r["column_name"] or ""), str(r["severity"]).upper())

    # Merge any in-memory report payload if provided.
    if dq_report:
        for table in dq_report.get("tables", []):
            for issue in table.get("issues", []):
                _set((issue.get("table", ""), issue.get("column", "")), str(issue.get("severity", "")).upper())
        for issue in dq_report.get("relationship_issues", []):
            _set((issue.get("table", ""), issue.get("column", "")), str(issue.get("severity", "")).upper())

    return result


def _extract_tables_from_sql(sql: str) -> set[str]:
    try:
        parsed = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return set()
    out: set[str] = set()
    for tbl in parsed.find_all(exp.Table):
        if tbl.name:
            out.add(tbl.name)
    return out


def _safe_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
    except Exception:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    return []


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall((text or "").lower()))
