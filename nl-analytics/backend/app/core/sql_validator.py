"""SQL safety: parse with sqlglot, enforce SELECT-only and identifier allow-list."""
from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

# Functions we forbid entirely (file I/O, FFI, attach, install, copy, etc.)
BLOCKED_FUNCS = {
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto",
    "read_blob", "read_text", "copy", "attach", "detach", "install", "load",
    "pragma", "set", "reset", "shell", "system",
}

BLOCKED_KEYWORDS_RE = re.compile(
    r"\b(ATTACH|DETACH|INSTALL|LOAD|COPY|PRAGMA|EXPORT|IMPORT|CALL|SET|RESET|"
    r"INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CREATE|DROP|ALTER|GRANT|REVOKE|"
    r"VACUUM|ANALYZE|CHECKPOINT)\b",
    re.IGNORECASE,
)

WEEKDAY_DAYPART_MISUSE_RE = re.compile(
    r"date_part\s*\(\s*'day'\s*,[^\)]*\)\s+as\s+(?:\"?day_of_week\"?|\"?weekday\"?)",
    re.IGNORECASE,
)


class SqlValidationError(Exception):
    pass


def validate_and_prepare(
    sql: str,
    allowed_tables: set[str],
    row_limit: int,
    table_columns: dict[str, set[str]] | None = None,
    relationships: list[dict[str, str]] | None = None,
) -> str:
    """Validate the SQL string, inject a LIMIT if missing, return the cleaned SQL."""
    if not sql or not sql.strip():
        raise SqlValidationError("Empty SQL")

    sql = _strip_trailing_semicolons(sql).strip()

    # Quick keyword scan first
    if BLOCKED_KEYWORDS_RE.search(sql):
        raise SqlValidationError("SQL contains a forbidden keyword (DDL/DML/utility).")

    # Common semantic trap: DATE_PART('day', ...) is day-of-month, not weekday.
    if WEEKDAY_DAYPART_MISUSE_RE.search(sql):
        raise SqlValidationError(
            "For weekday questions, DATE_PART('day', ...) is invalid. "
            "Use STRFTIME(date_col, '%A') or DATE_PART('dow', date_col) instead."
        )

    try:
        parsed = sqlglot.parse(sql, read="duckdb")
    except sqlglot.errors.ParseError as e:
        raise SqlValidationError(f"Could not parse SQL: {e}") from e

    if len(parsed) != 1 or parsed[0] is None:
        raise SqlValidationError("Only a single SELECT statement is allowed.")

    stmt = parsed[0]

    # Allow only SELECT or UNION at the top level (CTEs are attached as `with` arg of Select)
    if not isinstance(stmt, (exp.Select, exp.Union)):
        raise SqlValidationError(
            f"Only SELECT/UNION statements allowed (got {type(stmt).__name__})."
        )

    # Blocked functions
    for fn in stmt.find_all(exp.Func):
        name = (fn.sql_name() or "").lower()
        if name in BLOCKED_FUNCS:
            raise SqlValidationError(f"Function not allowed: {name}")
    for anon in stmt.find_all(exp.Anonymous):
        name = (anon.this or "").lower() if isinstance(anon.this, str) else ""
        if name in BLOCKED_FUNCS:
            raise SqlValidationError(f"Function not allowed: {name}")

    # Table allow-list
    referenced = set()
    for tbl in stmt.find_all(exp.Table):
        # Ignore CTE references (their name will match a CTE alias defined in WITH)
        referenced.add(tbl.name)

    cte_names = {cte.alias_or_name for cte in stmt.find_all(exp.CTE)}
    bad = {t for t in referenced if t and t not in allowed_tables and t not in cte_names}
    if bad:
        raise SqlValidationError(
            f"Unknown table(s): {sorted(bad)}. Allowed: {sorted(allowed_tables)}"
        )

    # Optional semantic check: for qualified columns like alias.col, verify
    # that the referenced column exists on the referenced base table.
    if table_columns:
        _validate_qualified_columns(stmt, table_columns, cte_names)

    # Optional semantic check: require JOIN predicates to follow known
    # relationship edges from schema profiling.
    if relationships:
        _validate_join_paths(stmt, relationships, cte_names)

    # Inject LIMIT if outer SELECT doesn't have one
    final = _ensure_limit(stmt, row_limit)
    return final.sql(dialect="duckdb")


def _strip_trailing_semicolons(sql: str) -> str:
    return sql.rstrip().rstrip(";").rstrip()


def _ensure_limit(stmt: exp.Expression, row_limit: int) -> exp.Expression:
    # Use sqlglot's helper which handles Select / Union / With correctly
    if isinstance(stmt, (exp.Select, exp.Union)) and not stmt.args.get("limit"):
        return stmt.limit(row_limit, copy=False)
    return stmt


def _build_alias_map(stmt: exp.Expression) -> dict[str, str]:
    """Map table aliases to base table names for the current statement."""
    alias_map: dict[str, str] = {}
    for tbl in stmt.find_all(exp.Table):
        table_name = tbl.name
        if not table_name:
            continue
        alias_map[table_name] = table_name
        alias = tbl.alias_or_name
        if alias:
            alias_map[alias] = table_name
    return alias_map


def _validate_qualified_columns(
    stmt: exp.Expression,
    table_columns: dict[str, set[str]],
    cte_names: set[str],
) -> None:
    alias_map = _build_alias_map(stmt)
    for col in stmt.find_all(exp.Column):
        # Unqualified columns are hard to disambiguate statically; skip.
        table_or_alias = col.table
        if not table_or_alias:
            continue

        # CTE columns are not validated here because we don't materialize CTE
        # schemas in this checker.
        if table_or_alias in cte_names:
            continue

        base_table = alias_map.get(table_or_alias, table_or_alias)
        if base_table in cte_names:
            continue

        cols = table_columns.get(base_table)
        if cols is None:
            # Unknown tables are caught by allow-list validation above.
            continue

        if col.name not in cols:
            raise SqlValidationError(
                f'Column "{col.name}" does not exist on table "{base_table}" '
                f'(referenced as "{table_or_alias}.{col.name}").'
            )


def _validate_join_paths(
    stmt: exp.Expression,
    relationships: list[dict[str, str]],
    cte_names: set[str],
) -> None:
    alias_map = _build_alias_map(stmt)
    allowed_edges = _build_relationship_edge_set(relationships)
    if not allowed_edges:
        return

    for join in stmt.find_all(exp.Join):
        on_expr = join.args.get("on")
        if on_expr is None:
            # USING/CROSS/NATURAL joins are left untouched here.
            continue

        for eq in on_expr.find_all(exp.EQ):
            left = eq.this
            right = eq.expression
            if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                continue
            if not left.table or not right.table:
                continue

            left_table = alias_map.get(left.table, left.table)
            right_table = alias_map.get(right.table, right.table)
            if left_table in cte_names or right_table in cte_names:
                continue
            if left_table == right_table:
                continue

            edge = frozenset(((left_table, left.name), (right_table, right.name)))
            if edge not in allowed_edges:
                raise SqlValidationError(
                    "JOIN does not follow known relationships: "
                    f'"{left_table}"."{left.name}" = "{right_table}"."{right.name}".'
                )


def _build_relationship_edge_set(
    relationships: list[dict[str, str]],
) -> set[frozenset[tuple[str, str]]]:
    edges: set[frozenset[tuple[str, str]]] = set()
    for rel in relationships:
        src = (rel.get("from_table", ""), rel.get("from_column", ""))
        dst = (rel.get("to_table", ""), rel.get("to_column", ""))
        if not all(src) or not all(dst):
            continue
        edges.add(frozenset((src, dst)))
    return edges


def extract_sql_from_llm_output(raw: str) -> str:
    """Pull SQL out of fenced code blocks or JSON the LLM may have returned."""
    import json as _json

    raw = (raw or "").strip()
    if not raw:
        return ""
    # Try strict JSON first (we asked for json_mode)
    try:
        obj = _json.loads(raw)
        if isinstance(obj, dict) and isinstance(obj.get("sql"), str):
            return obj["sql"].strip()
    except (ValueError, TypeError):
        pass
    # ```sql ... ```
    m = re.search(r"```(?:sql)?\s*(.+?)```", raw, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Loose JSON regex fallback
    m = re.search(r'"sql"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
    if m:
        return bytes(m.group(1), "utf-8").decode("unicode_escape").strip()
    return raw
