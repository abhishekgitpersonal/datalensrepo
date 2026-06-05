"""Build the prompts for NL->SQL and narration."""
from __future__ import annotations

import re
from collections import deque
from decimal import Decimal, InvalidOperation
from typing import Any

SQL_SYSTEM = """You are an expert data analyst that writes DuckDB SQL queries.
You must:
- Produce exactly ONE SELECT statement (CTEs are fine).
- Use ONLY the tables and columns provided in the schema.
- Quote identifiers with double quotes when they contain special characters.
- Never use INSERT, UPDATE, DELETE, CREATE, DROP, ATTACH, COPY, PRAGMA, or any file-reading functions.
- Prefer explicit JOIN ... ON syntax over comma joins.
- Use the relationships listed under "Known relationships" to join tables.
- Do not assume business-specific columns (e.g. status, country, category, name) unless they exist in schema.
- For medium-complexity questions, prefer the smallest correct join path that answers the question.
- Date/time rules:
    - For weekday/day-of-week, use STRFTIME(date_col, '%A') or DATE_PART('dow', date_col).
    - Do NOT use DATE_PART('day', date_col) to represent weekday (that is day-of-month).
    - For month-level grouping, use DATE_TRUNC('month', date_col) and keep year context.
    - For delays, use DATE_DIFF('day', start_date, end_date) with the exact date columns asked.
    - For "latest" / "most recent" month questions on historical data, derive recency from the data (e.g., MAX(date_col)), not CURRENT_DATE.
- Aggregation correctness rules:
    - If counting orders while joining line-item/detail tables, use COUNT(DISTINCT order_id) to avoid overcounting.
    - For concentration/share questions, compute individual share as value / SUM(value) OVER (); do NOT use cumulative running percentage unless explicitly asked.
    - For seasonal patterns by quarter, prefer grouping by quarter number (EXTRACT(quarter FROM date_col)); include year only when explicitly requested.
    - For generic revenue/sales questions, prefer sales-side metrics such as orders.total_price or item revenue (quantity * price_at_purchase). Do NOT use payment.amount unless the question explicitly asks about payments, transactions, or payment methods.
- If the question is ambiguous, make a reasonable assumption and proceed.
- Return ONLY a JSON object: {"sql": "<the query>", "assumptions": "<brief notes or empty>"}.
No prose outside that JSON.
"""

NARRATE_SYSTEM = """You are a skilled data analyst giving clear, grounded answers.
Given a user question and the result table, write a plain-English response with
three sections in this exact order:

1) Explanation: Directly answer the question conversationally. For simple
   ranking/lookup questions, 2-3 sentences is enough. For analytical questions
   about trends, distributions, comparisons, or time-series, go as deep as the
   data allows — identify patterns, note high/low points, describe movement
   over time, and give meaningful context. There is no sentence limit for complex
   analysis.
2) Summary: a single short line restating the headline answer.
3) Insights: 2-5 bullets (more for complex/analytical questions) with concrete
   comparisons, gaps, percentages, or trends visible in the table.

Rules:
- Use exact values from the table. Do not invent numbers or names.
- Do not repeat the entire table row-by-row.
- If the result is empty, say so and skip the rest.
- Do not start the Explanation with templated stock phrases.
- Do NOT mention SQL, LIMIT clauses, row counts, or query mechanics.
- Hard rule: every numeric value you mention must appear exactly in the visible
  result table or in the total row count stated in the prompt.
"""


def build_sql_prompt(
    question: str,
    schema: dict[str, Any],
    history: list[dict[str, Any]],
    dq_warnings: list[str] | None = None,
    planner_notes: list[str] | None = None,
    few_shot_examples: list[dict[str, str]] | None = None,
) -> str:
    tables = schema.get("tables", [])
    rels = schema.get("relationships", [])

    parts = ["# Schema"]
    for t in tables:
        cols = ", ".join(f'{c["name"]} ({c["type"]})' for c in t["columns"])
        parts.append(f'\n## Table "{t["name"]}" ({t["row_count"]} rows)')
        parts.append(f"Columns: {cols}")

    if rels:
        parts.append("\n# Known relationships")
        for r in rels:
            parts.append(
                f'- "{r["from_table"]}"."{r["from_column"]}" -> '
                f'"{r["to_table"]}"."{r["to_column"]}" (conf {r["confidence"]})'
            )

    if dq_warnings:
        parts.append("\n# Data quality warnings (be defensive)")
        for w in dq_warnings:
            parts.append(f"- {w}")
        parts.append(
            "When a warning is relevant, filter out invalid rows (e.g. add "
            "WHERE col > 0 for negative-value columns, WHERE col BETWEEN 1 AND 5 "
            "for ratings, WHERE col IS NOT NULL for null-heavy join keys)."
        )

    hints = build_datetime_sql_hints(question, schema)
    if hints:
        parts.append("\n# Date/Time hints for this question")
        for hint in hints:
            parts.append(f"- {hint}")

    if planner_notes:
        parts.append("\n# Planner context (relevant tables/columns)")
        for note in planner_notes[:8]:
            parts.append(f"- {note}")

    if few_shot_examples:
        parts.append("\n# Previously successful NL->SQL examples for this dataset")
        parts.append("Use these patterns when relevant, but adapt to the current question and schema.")
        for ex in few_shot_examples[:3]:
            q = (ex.get("question") or "").strip()
            s = (ex.get("sql") or "").strip()
            if not q or not s:
                continue
            parts.append(f"Q: {q}")
            parts.append(f"SQL: {s}")

    if history:
        parts.append("\n# Conversation so far")
        for msg in history[-12:]:
            if msg["role"] == "user":
                parts.append(f'User: {msg.get("question","")}')

    parts.append("\n# Current question")
    parts.append(question.strip())
    parts.append('\nRespond with JSON: {"sql": "...", "assumptions": "..."}')

    return "\n".join(parts)


def build_sql_fix_prompt(
    question: str,
    schema: dict[str, Any],
    bad_sql: str,
    error: str,
    dq_warnings: list[str] | None = None,
) -> str:
    """Ask the model to fix a SQL query that failed validation or execution."""
    tables = schema.get("tables", [])
    rels = schema.get("relationships", [])

    parts = ["# Schema"]
    for t in tables:
        cols = ", ".join(f'{c["name"]} ({c["type"]})' for c in t["columns"])
        parts.append(f'\n## Table "{t["name"]}" ({t["row_count"]} rows)')
        parts.append(f"Columns: {cols}")

    if rels:
        parts.append("\n# Known relationships")
        for r in rels:
            parts.append(
                f'- "{r["from_table"]}"."{r["from_column"]}" -> '
                f'"{r["to_table"]}"."{r["to_column"]}"'
            )

    if dq_warnings:
        parts.append("\n# Data quality warnings (be defensive)")
        for w in dq_warnings:
            parts.append(f"- {w}")

    hints = build_datetime_sql_hints(question, schema)
    if hints:
        parts.append("\n# Date/Time hints for this question")
        for hint in hints:
            parts.append(f"- {hint}")

    parts.append("\n# Original question")
    parts.append(question.strip())
    parts.append("\n# Your previous SQL (FAILED)")
    parts.append(bad_sql)
    parts.append("\n# Error from DuckDB")
    parts.append(error)

    # Targeted hint: if the error mentions a specific table that doesn't have
    # a specific column, re-list that table's actual columns explicitly.
    hint = _explain_binder_error(error, tables, bad_sql)
    if hint:
        parts.append("\n# Targeted hint based on the error")
        parts.append(hint)

    parts.append(
        "\nThe previous SQL was wrong. Carefully re-read the schema and the "
        "relationships above. STRICT RULES:\n"
        "1. EVERY table alias used in SELECT, WHERE, GROUP BY, ORDER BY, or "
        "JOIN ... ON must appear in the FROM clause or in a JOIN clause "
        "(e.g. if you use `oi.product_id`, you MUST have `JOIN order_items "
        "AS oi ON ...`).\n"
        "2. If the error says `Referenced table \"X\" not found`, then alias "
        "X is missing a JOIN. Either add the JOIN, or rewrite without that "
        "alias.\n"
        "3. If the error says `Table \"X\" does not have a column named "
        "\"Y\"`, then Y is NOT on table X. Pick the correct table from the "
        "schema above, or remove the reference.\n"
        "4. Use the full JOIN path through the relationships above. Common "
        "trap: customers -> orders -> order_items -> products (not "
        "customers -> orders -> products directly).\n"
        "5. Every non-aggregated column in SELECT must appear in GROUP BY.\n"
        "6. Do NOT copy the broken parts of the previous SQL verbatim. "
        "Rewrite the affected section from scratch using the schema.\n"
        "Produce a corrected SELECT."
    )
    parts.append('\nRespond with JSON: {"sql": "...", "assumptions": "..."}')
    return "\n".join(parts)


_COL_NOT_FOUND_RE = re.compile(
    r'Table\s+"([^"]+)"\s+does not have a column named\s+"([^"]+)"',
    re.IGNORECASE,
)
_TABLE_NOT_FOUND_RE = re.compile(
    r'Referenced\s+table\s+"([^"]+)"\s+not found',
    re.IGNORECASE,
)


def _explain_binder_error(
    error: str,
    tables: list[dict[str, Any]],
    bad_sql: str,
) -> str | None:
    """Generate a precise hint for common DuckDB binder errors."""
    by_name = {t["name"]: t for t in tables}

    # Case 1: column not found on a specific table
    m = _COL_NOT_FOUND_RE.search(error)
    if m:
        alias_or_table = m.group(1)
        missing_col = m.group(2)

        # The "table" in the error might be an alias. Try to find the real
        # table by scanning the bad SQL for `AS alias` or `JOIN table AS alias`.
        real_table = _resolve_alias(alias_or_table, bad_sql, by_name)
        if real_table and real_table in by_name:
            t = by_name[real_table]
            cols = ", ".join(c["name"] for c in t["columns"])
            # Suggest tables that DO have the missing column
            candidates = [
                tt["name"] for tt in tables
                if any(c["name"] == missing_col for c in tt["columns"])
            ]
            lines = [
                f'Alias `{alias_or_table}` refers to table `{real_table}`. '
                f'`{real_table}` columns are: {cols}.',
                f'Column `{missing_col}` is NOT in `{real_table}`.',
            ]
            if candidates:
                lines.append(
                    f'Tables that DO have a `{missing_col}` column: '
                    f'{", ".join(candidates)}. Use one of those instead.'
                )
            else:
                lines.append(
                    f'No table in the schema has a column named '
                    f'`{missing_col}`. You may have invented it — pick a '
                    f'real column from the schema.'
                )
            return "\n".join(lines)

    # Case 2: referenced table/alias not joined
    m = _TABLE_NOT_FOUND_RE.search(error)
    if m:
        alias = m.group(1)
        return (
            f'Alias `{alias}` is used but never declared in FROM or JOIN. '
            f'Either add `JOIN <real_table> AS {alias} ON ...` using one of '
            f'the relationships above, or rewrite without `{alias}`.'
        )

    return None


_ALIAS_RE_TMPL = (
    r'(?:FROM|JOIN)\s+"?(\w+)"?\s+(?:AS\s+)?{alias}\b'
)


def _resolve_alias(
    alias: str, bad_sql: str, by_name: dict[str, dict[str, Any]],
) -> str | None:
    """Find the real table for an alias used in the bad SQL."""
    # If the "alias" is itself a real table name, return it.
    if alias in by_name:
        return alias
    pattern = re.compile(_ALIAS_RE_TMPL.format(alias=re.escape(alias)), re.I)
    m = pattern.search(bad_sql)
    if m:
        return m.group(1)
    return None


def build_narration_prompt(
    question: str,
    sql: str,
    columns: list[str],
    rows: list[list[Any]],
    total_rows: int,
    dq_warnings: list[str] | None = None,
) -> str:
    preview = rows[:20]
    lines = [
        "Question:", question.strip(),
        f"\nResult ({total_rows} rows total, showing up to 20):",
        " | ".join(columns),
    ]
    for r in preview:
        lines.append(" | ".join("" if v is None else str(v) for v in r))
    if dq_warnings:
        lines.append("\nKnown data quality caveats for this dataset:")
        for w in dq_warnings:
            lines.append(f"- {w}")
        lines.append(
            "If the question is sensitive to any of the above issues, mention "
            "the caveat briefly in the summary so the reader knows the limit."
        )
    # Detect whether the question calls for deep analysis or a quick answer.
    is_analytical = bool(re.search(
        r"trend|over time|month|year|quarter|weekly|daily|annual|histor"
        r"|compare|breakdown|analysis|analyz|distribut|correlat|pattern"
        r"|fluctuat|growth|decline|forecast|period|detail|explain|performance"
        r"|insight|why|how (much|many|often)|movement",
        question.lower(),
    ))
    depth_instruction = (
        "For this analytical question, go deep: identify patterns, trends, "
        "peaks, troughs, and meaningful comparisons across the full visible "
        "result set. Do not artificially limit the length."
        if is_analytical
        else "Keep the explanation focused and concise."
    )
    lines.append(
        "\nWrite the response in this EXACT format:\n"
        "Explanation: <detailed answer; explain trends/comparisons rather than listing rows>\n\n"
        "Summary: <one-line headline that does NOT repeat the Explanation verbatim>\n\n"
        "Insights:\n- <non-duplicative insight 1 with concrete values or deltas>\n- <non-duplicative insight 2 with concrete values or deltas>\n\n"
        + depth_instruction + "\n"
        "STRICT GROUNDING RULES:\n"
        "- Only mention values that appear exactly in the visible table above or in the total row count.\n"
        "- Do not aggregate across rows unless the aggregate value itself appears in the table.\n"
        "- Do not collapse entities (e.g., combine multiple customers into first-name groups).\n"
        "SECTION QUALITY RULES:\n"
        "- Explanation should be the longest section for analytical questions.\n"
        "- Summary should be one concise headline sentence only.\n"
        "- Insights must add new observations (extremes, direction changes, gaps, or concentration), not restate the same sentence."
    )
    return "\n".join(lines)


def build_datetime_sql_hints(question: str, schema: dict[str, Any]) -> list[str]:
    q = question.lower()
    hints: list[str] = []
    date_cols = _schema_date_columns(schema)

    if re.search(r"day\s+of\s+week|weekday", q):
        hints.append(
            "Use weekday extraction with STRFTIME(date_col, '%A') or DATE_PART('dow', date_col); "
            "never DATE_PART('day', date_col) for weekday."
        )

    if re.search(r"\bmonth\b|monthly", q):
        hints.append("For monthly grouping, use DATE_TRUNC('month', date_col) and keep year context.")

    if re.search(r"\byear\b|yearly|annual", q):
        hints.append("For yearly grouping, use DATE_PART('year', date_col) on the relevant date column.")

    if re.search(r"delay|after|between", q):
        if "order_date" in q and "shipment_date" in q:
            hints.append("For shipping delay after order date, use DATE_DIFF('day', order_date, shipment_date).")
        elif "shipment_date" in q and "delivery_date" in q:
            hints.append("For carrier/transit delay, use DATE_DIFF('day', shipment_date, delivery_date).")
        elif "order_date" in q and "delivery_date" in q:
            hints.append("For order-to-delivery delay, use DATE_DIFF('day', order_date, delivery_date).")
        elif any(col in date_cols for col in ("order_date", "shipment_date", "delivery_date")):
            hints.append("For delay questions, compute DATE_DIFF('day', start_date, end_date) using the exact columns asked.")

    return hints


def _schema_date_columns(schema: dict[str, Any]) -> set[str]:
    cols: set[str] = set()
    for table in schema.get("tables", []):
        for col in table.get("columns", []):
            ctype = str(col.get("type", "")).lower()
            name = str(col.get("name", "")).lower()
            if "date" in ctype or "time" in ctype or "date" in name or "time" in name:
                cols.add(name)
    return cols


NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")


def narration_is_grounded(
    text: str,
    question: str,
    columns: list[str],
    rows: list[list[Any]],
    total_rows: int,
) -> bool:
    """Verify every number the narration mentions exists in the actual result.

    Only numeric values are checked — they are deterministic and safe to
    validate. Entity-name checks were removed because multi-word names,
    partial mentions, and paraphrases cause too many false positives that
    replace correct LLM narration with the worse deterministic fallback.
    """
    if not text:
        return False
    allowed_numbers = _allowed_number_literals(question, rows, total_rows)
    for token in NUMBER_RE.findall(text):
        canonical = _canonical_number(token)
        if canonical is None:
            continue
        if canonical not in allowed_numbers:
            return False
    return True


def _allowed_entity_names(rows: list[list[Any]], columns: list[str]) -> set[str]:
    """Extract all non-numeric string values from result rows as allowed entity names.
    
    STRICT: Only allows names that actually appear in this specific result set,
    not names that exist elsewhere in the database.
    """
    allowed: set[str] = set()
    for row in rows:
        for i, cell in enumerate(row):
            if cell is None:
                continue
            cell_str = str(cell).strip()
            if not cell_str:
                continue
            # Only allow non-numeric strings
            try:
                float(cell_str)
                continue  # Skip pure numeric cells
            except ValueError:
                allowed.add(cell_str)
    return allowed


def _narration_entity_names_valid(text: str, allowed_entities: set[str]) -> bool:
    """Check if narration mentions only entity names from the ACTUAL result set.
    
    Extract capitalized words and proper nouns from narration and verify each 
    one appears in the result data. This catches LLM hallucinations like 
    "Phone Grip, Food Processor, Microphone" when those products aren't in 
    the actual result set returned by the query.
    
    STRICT: We require exact or very close matches in the result set.
    """
    if not text or not allowed_entities:
        return True  # Can't validate if narration or data is empty
    
    # Extract capitalized words and proper nouns (heuristic: Title Case words)
    words = text.split()
    suspicious_names: list[str] = []
    
    for word in words:
        # Clean punctuation but preserve the word
        clean_word = word.strip("'\"(),.:;-")
        if not clean_word or len(clean_word) < 2:
            continue
        # Flag capitalized words that look like entity names
        # (not common words like "Explanation", "Summary", etc.)
        if (clean_word[0].isupper() and 
            not clean_word[0].isdigit() and
            clean_word not in {
                "Explanation", "Summary", "Insights", "The", "Here", "These", 
                "All", "Top", "More", "And", "By", "From", "For", "With",
                "Average", "Total", "Count", "Reviews", "Rating", "Products",
                "Customers", "Orders", "Suppliers", "Higher", "Lower", "Gap",
                "Runner", "Followed", "Full", "Result", "Complete", "Set"
            }):
            suspicious_names.append(clean_word)
    
    # For each suspicious name, check if it appears in the allowed entities
    # Use multiple matching strategies:
    for name in suspicious_names:
        found = False
        
        # Strategy 1: Exact match (case-insensitive)
        if any(name.lower() == e.lower() for e in allowed_entities):
            found = True
        
        # Strategy 2: Substring match (part of a multi-word entity like "John" in "John Williams")
        if not found:
            for entity in allowed_entities:
                if name.lower() in entity.lower():
                    found = True
                    break
        
        # Strategy 3: Reverse substring (entity is part of narration phrase)
        # If NO match found via strategies 1-2, it's likely a hallucination
        if name[0].isupper() and len(name) > 3:
            if not found:
                # This is a potential hallucination (looks like entity name, not in result)
                # Double-check: is this in a suspicious context (comma list)?
                if f"{name}," in text or f"{name};" in text or f"{name} and" in text:
                    # This looks like a list item that doesn't match our data
                    return False
    
    return True


def build_deterministic_narration(
    question: str,
    columns: list[str],
    rows: list[list[Any]],
    total_rows: int,
) -> str:
    if not rows:
        return (
            "Explanation: The query returned no rows, so there is no data to "
            "summarize for this question.\n\n"
            "Summary: No rows matched this question.\n\n"
            "Insights:\n- The result table is empty."
        )

    cols = list(columns)
    visible = len(rows)

    def _to_text(value: Any) -> str:
        return "NULL" if value is None else str(value)

    def _looks_numeric(value: Any) -> bool:
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    def _pretty_col(col: str) -> str:
        return col.replace("_", " ")

    def _as_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _looks_time_like_column(name: str, values: list[Any]) -> bool:
        lower = name.lower()
        if any(k in lower for k in ["date", "month", "year", "time", "period"]):
            return True
        sample = [v for v in values[:5] if v is not None]
        if not sample:
            return False
        try:
            parsed = pd.to_datetime([str(v) for v in sample], errors="coerce")
            return bool(parsed.notna().all())
        except Exception:
            return False

    # Time-series path: one time-like column and at least one numeric metric.
    time_idx = -1
    for i, col in enumerate(cols):
        series = [r[i] if i < len(r) else None for r in rows]
        if _looks_time_like_column(col, series):
            time_idx = i
            break

    numeric_indices = [
        i for i, _c in enumerate(cols)
        if any(_looks_numeric(r[i]) for r in rows if i < len(r) and r[i] is not None)
    ]

    if time_idx >= 0 and numeric_indices:
        metric_idx = numeric_indices[0] if numeric_indices[0] != time_idx else (numeric_indices[1] if len(numeric_indices) > 1 else -1)
        if metric_idx >= 0:
            points: list[tuple[str, float]] = []
            for row in rows:
                if time_idx >= len(row) or metric_idx >= len(row):
                    continue
                x = row[time_idx]
                y = _as_float(row[metric_idx])
                if x is None or y is None:
                    continue
                points.append((str(x), y))

            if len(points) >= 2:
                start_label, start_val = points[0]
                end_label, end_val = points[-1]
                peak_label, peak_val = max(points, key=lambda p: p[1])
                low_label, low_val = min(points, key=lambda p: p[1])
                delta = end_val - start_val
                pct = (delta / start_val * 100.0) if start_val != 0 else None
                direction = "increased" if delta > 0 else ("decreased" if delta < 0 else "was flat")

                explanation = (
                    f"Explanation: Month-by-month, {_pretty_col(cols[metric_idx])} starts at {start_val} in {start_label} "
                    f"and ends at {end_val} in {end_label}. Overall it {direction} by {abs(delta)}"
                )
                if pct is not None:
                    explanation += f" ({pct:.2f}%)."
                else:
                    explanation += "."
                explanation += (
                    f" The highest month is {peak_label} at {peak_val}, while the lowest month is {low_label} at {low_val}."
                )

                summary_line = (
                    f"Summary: {_pretty_col(cols[metric_idx]).capitalize()} {direction} from {start_label} to {end_label}, "
                    f"peaking at {peak_val} in {peak_label}."
                )

                insights: list[str] = [
                    f"- Net change across the period: {delta} ({pct:.2f}% if start is non-zero)." if pct is not None else f"- Net change across the period: {delta}.",
                    f"- Peak-to-trough spread is {peak_val - low_val} ({peak_label} vs {low_label}).",
                ]

                # Add largest month-over-month movement when possible.
                mom_changes: list[tuple[str, float]] = []
                for i in range(1, len(points)):
                    prev_label, prev_val = points[i - 1]
                    curr_label, curr_val = points[i]
                    mom_changes.append((f"{prev_label} -> {curr_label}", curr_val - prev_val))
                if mom_changes:
                    jump_label, jump_val = max(mom_changes, key=lambda p: p[1])
                    drop_label, drop_val = min(mom_changes, key=lambda p: p[1])
                    insights.append(f"- Largest month-over-month increase: {jump_label} ({jump_val}).")
                    if drop_val < 0:
                        insights.append(f"- Largest month-over-month decline: {drop_label} ({drop_val}).")

                return explanation + "\n\n" + summary_line + "\n\nInsights:\n" + "\n".join(insights)

    # Generic non-time-series fallback.
    show_cols = cols[: min(4, len(cols))]
    top_n = min(5, visible)
    name_like_idx = [i for i, c in enumerate(show_cols) if "name" in c.lower()]

    def _entity_label(row: list[Any]) -> str:
        if name_like_idx:
            parts = []
            for i in name_like_idx[:2]:
                if i < len(row) and row[i] is not None:
                    parts.append(str(row[i]))
            if parts:
                return " ".join(parts)
        for i, _ in enumerate(show_cols):
            if i < len(row) and row[i] is not None and not _looks_numeric(row[i]):
                return str(row[i])
        return "Top row"

    def _metric_pairs(row: list[Any]) -> list[str]:
        metrics: list[str] = []
        for i, c in enumerate(show_cols):
            if i >= len(row):
                continue
            v = row[i]
            if v is None:
                continue
            if _looks_numeric(v) or i not in name_like_idx:
                metrics.append(f"{_pretty_col(c)} {_to_text(v)}")
        return metrics

    top_mentions: list[str] = []
    for idx in range(top_n):
        row = rows[idx]
        entity = _entity_label(row)
        metrics = _metric_pairs(row)
        top_mentions.append(f"{entity} ({', '.join(metrics[:2])})" if metrics else entity)

    explanation = (
        f"Explanation: The result is led by {top_mentions[0]}"
        + (f", followed by {top_mentions[1]}." if len(top_mentions) > 1 else ".")
    )
    if total_rows > top_n:
        explanation += f" This preview shows the first {top_n} rows out of {total_rows} total."

    summary_line = f"Summary: {top_mentions[0]} is the top result in the current output."

    insights = [
        f"- Visible rows: {visible} out of {total_rows} total.",
        f"- Top entries in order: {', '.join(top_mentions[: min(3, len(top_mentions))])}.",
    ]
    if total_rows > visible:
        insights.append("- Additional rows exist beyond the visible preview and may change deeper ranking context.")

    return explanation + "\n\n" + summary_line + "\n\nInsights:\n" + "\n".join(insights)


def _allowed_number_literals(question: str, rows: list[list[Any]], total_rows: int) -> set[str]:
    allowed: set[str] = set()
    for token in NUMBER_RE.findall(question.lower()):
        c = _canonical_number(token)
        if c is not None:
            allowed.add(c)

    c_total = _canonical_number(str(total_rows))
    if c_total is not None:
        allowed.add(c_total)

    for row in rows:
        for cell in row:
            c = _canonical_number(str(cell))
            if c is not None:
                allowed.add(c)
    return allowed


def _canonical_number(value: str) -> str | None:
    raw = value.strip().replace(",", "")
    if raw.endswith("%"):
        raw = raw[:-1]
    if not raw:
        return None
    try:
        d = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return format(d.normalize(), "f").rstrip("0").rstrip(".") or "0"


TOKEN_RE = re.compile(r"[a-z0-9_]+")
STOPWORDS = {
    "a", "an", "and", "are", "at", "across", "after", "all", "average",
    "by", "day", "days", "did", "do", "each", "for", "from", "get", "had",
    "has", "have", "highest", "how", "in", "is", "longest", "many", "most",
    "money", "of", "on", "or", "per", "placed", "show",
    "spent", "than", "that", "the", "their", "them", "there", "to", "top",
    "total", "value", "was", "what", "which", "who", "with",
}


def focus_schema_for_question(question: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Reduce schema noise for simple questions by keeping likely relevant tables.

    Returns the original schema when confidence is low or when the focused slice
    would not materially reduce prompt size.
    """
    tables = schema.get("tables", [])
    relationships = schema.get("relationships", [])
    if len(tables) <= 3:
        return schema

    question_tokens = _question_tokens(question)
    if not question_tokens:
        return schema

    scored: list[tuple[int, str]] = []
    for table in tables:
        score = _table_relevance_score(question, question_tokens, table)
        if score > 0:
            scored.append((score, table["name"]))

    if not scored:
        return schema

    scored.sort(key=lambda item: (-item[0], item[1]))
    top_names = [name for _, name in scored[:2]]
    selected_names = _expand_with_join_bridge(top_names, relationships)

    if len(selected_names) >= len(tables):
        return schema

    focused_tables = [table for table in tables if table["name"] in selected_names]
    focused_relationships = [
        rel for rel in relationships
        if rel.get("from_table") in selected_names and rel.get("to_table") in selected_names
    ]

    if len(focused_tables) < 1:
        return schema

    return {
        **schema,
        "tables": focused_tables,
        "relationships": focused_relationships,
    }


def filter_history_for_sql(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only recent user questions to avoid leaking stale SQL/aliases."""
    filtered: deque[dict[str, Any]] = deque(maxlen=6)
    for msg in history:
        if msg.get("role") == "user" and msg.get("question"):
            filtered.append({"role": "user", "question": msg["question"]})
    return list(filtered)


def _question_tokens(question: str) -> set[str]:
    raw_tokens = TOKEN_RE.findall(question.lower())
    tokens: set[str] = set()
    for token in raw_tokens:
        if token in STOPWORDS:
            continue
        tokens.add(token)
        stem = _stem_token(token)
        if stem != token:
            tokens.add(stem)
    return tokens


def _table_relevance_score(question: str, question_tokens: set[str], table: dict[str, Any]) -> int:
    table_name = str(table["name"]).lower()
    table_tokens = _name_tokens(table_name)
    score = 0

    if table_name in question.lower() or table_name.rstrip("s") in question.lower():
        score += 6

    score += 4 * len(question_tokens & table_tokens)

    for column in table.get("columns", []):
        col_name = str(column["name"]).lower()
        col_tokens = _name_tokens(col_name)
        overlap = question_tokens & col_tokens
        if overlap:
            score += len(overlap)
            if col_name in question.lower():
                score += 2

    return score


def _name_tokens(name: str) -> set[str]:
    tokens = set(TOKEN_RE.findall(name.lower().replace("__", "_")))
    expanded = set(tokens)
    for token in tokens:
        parts = [part for part in token.split("_") if part]
        expanded.update(parts)
        stem = _stem_token(token)
        if stem != token:
            expanded.add(stem)
        for part in parts:
            stem = _stem_token(part)
            if stem != part:
                expanded.add(stem)
    return expanded


def _stem_token(token: str) -> str:
    stem = token
    for suffix in ("ments", "ment", "ings", "ing", "ed", "es", "s"):
        if stem.endswith(suffix) and len(stem) - len(suffix) >= 3:
            stem = stem[: -len(suffix)]
            break
    if len(stem) >= 2 and stem[-1] == stem[-2]:
        stem = stem[:-1]
    return stem


def _expand_with_join_bridge(table_names: list[str], relationships: list[dict[str, Any]]) -> set[str]:
    selected = set(table_names)
    if len(table_names) < 2:
        return selected

    graph: dict[str, set[str]] = {}
    for rel in relationships:
        left = rel.get("from_table")
        right = rel.get("to_table")
        if not left or not right:
            continue
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)

    start, goal = table_names[0], table_names[1]
    if goal in graph.get(start, set()):
        return selected

    queue: deque[tuple[str, list[str]]] = deque([(start, [start])])
    seen = {start}
    while queue:
        node, path = queue.popleft()
        for neighbor in graph.get(node, set()):
            if neighbor in seen:
                continue
            next_path = path + [neighbor]
            if neighbor == goal:
                return set(next_path)
            seen.add(neighbor)
            queue.append((neighbor, next_path))

    return selected


def _fmt_row(row: dict[str, Any]) -> str:
    items = []
    for k, v in row.items():
        s = str(v) if v is not None else "NULL"
        if len(s) > 40:
            s = s[:37] + "..."
        items.append(f"{k}={s}")
    return "{" + ", ".join(items) + "}"
