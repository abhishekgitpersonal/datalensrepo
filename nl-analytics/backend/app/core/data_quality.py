"""Data quality scanner.

Runs a battery of structural and semantic checks against a session's DuckDB
and produces a serializable report. The output is used to:
  1. Persist warnings in SQLite (so the UI can show them anytime).
  2. Feed the highest-severity items into the LLM prompt as caveats, so
     answers acknowledge known data quirks instead of inventing values.

Severities
----------
ERROR   Breaks queries or trustworthiness (duplicate PKs, all-null column,
        large fraction of orphan FKs, type cast impossible).
WARN    Reduces accuracy (nulls in PK/FK, negative price/qty, out-of-range
        ratings, malformed emails, future/very old dates, small fraction of
        orphan FKs, low duplicate rate on identifier columns).
INFO    Cosmetic / informational (low-cardinality enums, leading/trailing
        whitespace stripped, mixed-case in categorical columns).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date
from typing import Any, Iterable

import duckdb

from .profiler import detect_relationships
from .session_manager import open_duckdb


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    table: str
    column: str | None
    issue_type: str
    severity: str            # ERROR | WARN | INFO
    count: int
    message: str
    sample: list[Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

NUMERIC_TYPES = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
                 "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT",
                 "DECIMAL", "DOUBLE", "FLOAT", "REAL", "NUMERIC"}
DATE_TYPES = {"DATE", "TIMESTAMP", "TIMESTAMP_NS", "TIMESTAMP_MS",
              "TIMESTAMP_S", "TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ"}
TEXT_TYPES = {"VARCHAR", "TEXT", "STRING", "CHAR"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def scan_session(session_id: str) -> dict[str, Any]:
    """Run all DQ checks for an entire session."""
    con = open_duckdb(session_id, read_only=True)
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main' ORDER BY 1;"
            ).fetchall()
        ]
        table_reports: list[dict[str, Any]] = []
        for t in tables:
            table_reports.append(scan_table(con, t))
    finally:
        con.close()

    rel_issues = _relationship_issues(session_id)
    summary = _summarize(table_reports, rel_issues)
    return {
        "tables": table_reports,
        "relationship_issues": [i.to_dict() for i in rel_issues],
        "summary": summary,
    }


def scan_table(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, Any]:
    cols = con.execute(f'PRAGMA table_info("{table}");').fetchall()
    # PRAGMA: cid, name, type, notnull, dflt_value, pk
    columns = [{"name": c[1], "type": (c[2] or "").upper()} for c in cols]
    row_count = int(con.execute(f'SELECT COUNT(*) FROM "{table}";').fetchone()[0])

    issues: list[Issue] = []
    if row_count == 0:
        issues.append(Issue(table, None, "empty_table", "ERROR", 0,
                            f'Table "{table}" has no rows.'))
        return {"name": table, "row_count": row_count,
                "issues": [i.to_dict() for i in issues]}

    issues.extend(_null_checks(con, table, columns, row_count))
    issues.extend(_duplicate_pk_checks(con, table, columns))
    issues.extend(_numeric_checks(con, table, columns))
    issues.extend(_rating_checks(con, table, columns))
    issues.extend(_date_checks(con, table, columns))
    issues.extend(_email_checks(con, table, columns))
    issues.extend(_text_hygiene_checks(con, table, columns))

    return {
        "name": table,
        "row_count": row_count,
        "issues": [i.to_dict() for i in issues],
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _null_checks(con, table: str, columns: list[dict], row_count: int) -> list[Issue]:
    out: list[Issue] = []
    if not columns:
        return out
    parts = []
    for c in columns:
        nm = c["name"]
        if c["type"] in TEXT_TYPES or c["type"].startswith("VARCHAR"):
            parts.append(f"SUM(CASE WHEN \"{nm}\" IS NULL OR TRIM(\"{nm}\")='' THEN 1 ELSE 0 END) AS \"{nm}\"")
        else:
            parts.append(f'SUM(CASE WHEN "{nm}" IS NULL THEN 1 ELSE 0 END) AS "{nm}"')
    sql = f"SELECT {', '.join(parts)} FROM \"{table}\""
    row = con.execute(sql).fetchone()
    for c, value in zip(columns, row, strict=False):
        n = int(value or 0)
        if n == 0:
            continue
        col = c["name"]
        is_keyish = col.lower().endswith("_id") or col.lower() == "id"
        pct = n / row_count
        if n == row_count:
            sev = "ERROR"
            msg = f'Column "{col}" is entirely null/blank.'
        elif is_keyish:
            sev = "ERROR" if pct > 0.05 else "WARN"
            msg = f'Identifier column "{col}" has {n} null/blank values ({pct:.1%}).'
        elif pct > 0.20:
            sev = "WARN"
            msg = f'Column "{col}" is {pct:.0%} null/blank ({n} rows).'
        else:
            sev = "INFO"
            msg = f'Column "{col}" has {n} null/blank values ({pct:.1%}).'
        out.append(Issue(table, col, "null_values", sev, n, msg))
    return out


def _duplicate_pk_checks(con, table: str, columns: list[dict]) -> list[Issue]:
    out: list[Issue] = []
    pk_candidates = [c["name"] for c in columns
                     if c["name"].lower() == "id"
                     or c["name"].lower() == f"{table.lower().rstrip('s')}_id"]
    for col in pk_candidates:
        row = con.execute(
            f'SELECT COUNT(*) - COUNT(DISTINCT "{col}") AS dups FROM "{table}";'
        ).fetchone()
        dups = int(row[0] or 0)
        if dups > 0:
            samples = [r[0] for r in con.execute(
                f'SELECT "{col}" FROM "{table}" GROUP BY 1 HAVING COUNT(*)>1 LIMIT 5;'
            ).fetchall()]
            out.append(Issue(
                table, col, "duplicate_key", "ERROR", dups,
                f'Identifier column "{col}" has {dups} duplicate value(s); '
                f'PK uniqueness violated.',
                sample=samples,
            ))
    return out


def _numeric_checks(con, table: str, columns: list[dict]) -> list[Issue]:
    out: list[Issue] = []
    money_like = {"price", "amount", "total_price", "revenue", "cost",
                  "price_at_purchase"}
    qty_like = {"quantity", "qty", "units", "count"}
    for c in columns:
        nm = c["name"]
        ctype = c["type"]
        if not any(t in ctype for t in NUMERIC_TYPES):
            continue
        lname = nm.lower()
        if lname in money_like or "price" in lname or "amount" in lname:
            neg = int(con.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{nm}" < 0;'
            ).fetchone()[0] or 0)
            if neg > 0:
                out.append(Issue(table, nm, "negative_value", "WARN", neg,
                                 f'Numeric column "{nm}" has {neg} negative value(s); '
                                 'aggregations may understate totals.'))
        if lname in qty_like or lname.endswith("_qty") or lname.endswith("_count"):
            nonpos = int(con.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{nm}" <= 0;'
            ).fetchone()[0] or 0)
            if nonpos > 0:
                out.append(Issue(table, nm, "non_positive_quantity", "WARN", nonpos,
                                 f'Quantity column "{nm}" has {nonpos} non-positive value(s).'))
    return out


def _rating_checks(con, table: str, columns: list[dict]) -> list[Issue]:
    out: list[Issue] = []
    for c in columns:
        if c["name"].lower() != "rating":
            continue
        bad = int(con.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{c["name"]}" IS NOT NULL '
            f'AND ("{c["name"]}" < 1 OR "{c["name"]}" > 5);'
        ).fetchone()[0] or 0)
        if bad > 0:
            out.append(Issue(table, c["name"], "rating_out_of_range", "WARN", bad,
                             f'Column "{c["name"]}" has {bad} value(s) outside 1..5.'))
    return out


def _date_checks(con, table: str, columns: list[dict]) -> list[Issue]:
    out: list[Issue] = []
    today_iso = date.today().isoformat()
    for c in columns:
        nm = c["name"]
        ctype = c["type"]
        if not any(t in ctype for t in DATE_TYPES) and "date" not in nm.lower():
            continue
        try:
            future = int(con.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE TRY_CAST("{nm}" AS DATE) > DATE \'{today_iso}\';'
            ).fetchone()[0] or 0)
        except duckdb.Error:
            future = 0
        try:
            very_old = int(con.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE TRY_CAST("{nm}" AS DATE) < DATE \'1990-01-01\';'
            ).fetchone()[0] or 0)
        except duckdb.Error:
            very_old = 0
        try:
            unparsed = int(con.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{nm}" IS NOT NULL AND TRY_CAST("{nm}" AS DATE) IS NULL;'
            ).fetchone()[0] or 0)
        except duckdb.Error:
            unparsed = 0
        if future > 0:
            out.append(Issue(table, nm, "future_date", "WARN", future,
                             f'Column "{nm}" has {future} date value(s) in the future.'))
        if very_old > 0:
            out.append(Issue(table, nm, "very_old_date", "INFO", very_old,
                             f'Column "{nm}" has {very_old} date value(s) before 1990.'))
        if unparsed > 0:
            out.append(Issue(table, nm, "unparseable_date", "WARN", unparsed,
                             f'Column "{nm}" has {unparsed} value(s) that cannot be parsed as a date.'))
    return out


def _email_checks(con, table: str, columns: list[dict]) -> list[Issue]:
    out: list[Issue] = []
    for c in columns:
        if "email" not in c["name"].lower():
            continue
        nm = c["name"]
        bad = int(con.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{nm}" IS NOT NULL '
            f"AND NOT regexp_matches(\"{nm}\", '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$');"
        ).fetchone()[0] or 0)
        if bad > 0:
            out.append(Issue(table, nm, "invalid_email", "WARN", bad,
                             f'Column "{nm}" has {bad} value(s) that are not valid emails.'))
    return out


def _text_hygiene_checks(con, table: str, columns: list[dict]) -> list[Issue]:
    out: list[Issue] = []
    for c in columns:
        ctype = c["type"]
        if not (ctype.startswith("VARCHAR") or ctype in TEXT_TYPES):
            continue
        nm = c["name"]
        try:
            trimmable = int(con.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{nm}" IS NOT NULL '
                f'AND ("{nm}" != TRIM("{nm}"));'
            ).fetchone()[0] or 0)
        except duckdb.Error:
            trimmable = 0
        if trimmable > 0:
            out.append(Issue(table, nm, "untrimmed_whitespace", "INFO", trimmable,
                             f'Column "{nm}" has {trimmable} value(s) with leading/trailing whitespace.'))
    return out


def _relationship_issues(session_id: str) -> list[Issue]:
    rels = detect_relationships(session_id)
    out: list[Issue] = []
    if not rels:
        return out
    con = open_duckdb(session_id, read_only=True)
    try:
        for r in rels:
            ft, fc, pt, pc = r["from_table"], r["from_column"], r["to_table"], r["to_column"]
            try:
                row = con.execute(
                    f'SELECT COUNT(*) FROM "{ft}" c '
                    f'WHERE c."{fc}" IS NOT NULL '
                    f'AND NOT EXISTS (SELECT 1 FROM "{pt}" p WHERE p."{pc}" = c."{fc}");'
                ).fetchone()
                total = con.execute(
                    f'SELECT COUNT(*) FROM "{ft}" WHERE "{fc}" IS NOT NULL;'
                ).fetchone()[0]
            except duckdb.Error:
                continue
            orphans = int(row[0] or 0)
            total = int(total or 0)
            if orphans == 0 or total == 0:
                continue
            pct = orphans / total
            sev = "ERROR" if pct > 0.10 else "WARN"
            out.append(Issue(
                ft, fc, "broken_foreign_key", sev, orphans,
                f'Foreign key "{ft}.{fc}" -> "{pt}.{pc}" has {orphans} '
                f'orphan value(s) ({pct:.1%}). Joins will drop those rows.',
            ))
    finally:
        con.close()
    return out


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _summarize(tables: list[dict[str, Any]], rels: list[Issue]) -> dict[str, int]:
    s = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for t in tables:
        for i in t["issues"]:
            s[i["severity"]] = s.get(i["severity"], 0) + 1
    for i in rels:
        s[i.severity] = s.get(i.severity, 0) + 1
    return {"errors": s["ERROR"], "warnings": s["WARN"], "infos": s["INFO"]}


def top_warnings_for_prompt(report: dict[str, Any], limit: int = 8) -> list[str]:
    """Return human-readable lines describing the most important DQ issues,
    suitable for embedding in an LLM system prompt."""
    severity_order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    items: list[tuple[int, str]] = []
    for t in report.get("tables", []):
        for i in t.get("issues", []):
            items.append((severity_order.get(i["severity"], 9),
                          f'[{i["severity"]}] {i["message"]}'))
    for i in report.get("relationship_issues", []):
        items.append((severity_order.get(i["severity"], 9),
                      f'[{i["severity"]}] {i["message"]}'))
    items.sort(key=lambda x: x[0])
    return [msg for _, msg in items[:limit]]


def collect_warnings(session_id: str) -> list[Issue]:
    """Iterate persisted warnings from SQLite via the db helper. Used by
    callers that don't want to re-run a full scan."""
    raise NotImplementedError  # callers use the db helper directly
