"""Schema inference and foreign-key candidate detection."""
from __future__ import annotations

from typing import Any

from .session_manager import open_duckdb


def get_tables(session_id: str) -> list[str]:
    con = open_duckdb(session_id, read_only=True)
    try:
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name;"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def describe_table(session_id: str, table: str, sample_n: int = 3) -> dict[str, Any]:
    con = open_duckdb(session_id, read_only=True)
    try:
        cols = con.execute(f'PRAGMA table_info("{table}");').fetchall()
        # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
        columns = [{"name": c[1], "type": c[2]} for c in cols]
        sample = con.execute(
            f'SELECT * FROM "{table}" USING SAMPLE {sample_n} ROWS;'
        ).fetchdf()
        sample_rows = sample.astype(object).where(sample.notna(), None).to_dict("records")
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table}";').fetchone()[0]
        return {
            "name": table,
            "columns": columns,
            "sample_rows": sample_rows,
            "row_count": int(row_count),
            "col_count": len(columns),
        }
    finally:
        con.close()


def detect_relationships(session_id: str) -> list[dict[str, Any]]:
    """Heuristic FK detection:
      - Column names ending in _id (other than the table's own pk)
      - or matching another table's column name
      - confirmed when a sample of values is contained in the candidate parent column.
    """
    con = open_duckdb(session_id, read_only=True)
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='main';"
            ).fetchall()
        ]
        # Build column index: table -> [col names]
        cols: dict[str, list[str]] = {}
        for t in tables:
            cols[t] = [c[1] for c in con.execute(f'PRAGMA table_info("{t}");').fetchall()]

        # Identify likely PKs: column named "<table_singular>_id" or "id" in the same table
        pk_candidates: dict[str, list[str]] = {t: [] for t in tables}
        for t, cs in cols.items():
            for c in cs:
                if c.lower() == "id" or c.lower() == f"{t.lower().rstrip('s')}_id":
                    pk_candidates[t].append(c)

        results: list[dict[str, Any]] = []

        def _affinity(child_col: str, parent: str) -> int:
            """Higher score = better-matching parent for a foreign-key column.

            We prefer parents whose name stem matches the FK column's stem
            (e.g. ``product_id`` -> ``products``) so we don't accidentally
            map ``product_id`` to ``customers.customer_id`` just because the
            ID ranges happen to overlap.
            """
            c = child_col.lower()
            p = parent.lower()
            stem = c[:-3] if c.endswith("_id") else c  # 'product'
            p_singular = p.rstrip("s")
            if stem == p_singular:
                return 3  # 'product_id' -> 'products'
            if stem == p:
                return 3  # 'product_id' -> 'product'
            if stem in p or p_singular in stem:
                return 2  # partial overlap
            if c in cols.get(parent, []):
                return 1  # literal column-name match
            return 0

        for child in tables:
            for col in cols[child]:
                if not col.lower().endswith("_id"):
                    continue
                # Skip if it's the child's own PK
                if col in pk_candidates.get(child, []):
                    continue
                # Rank parents by name affinity so we pick the semantically
                # correct table even when several share ID ranges.
                ranked_parents = sorted(
                    (p for p in tables if p != child),
                    key=lambda p: _affinity(col, p),
                    reverse=True,
                )
                for parent in ranked_parents:
                    parent_pks = pk_candidates.get(parent, [])
                    # Try: parent has same column name, or parent has its conventional PK
                    parent_col = None
                    if col in cols[parent]:
                        parent_col = col
                    elif parent_pks:
                        # Use the first PK candidate
                        parent_col = parent_pks[0]
                    if not parent_col:
                        continue
                    # Verify via sample containment
                    try:
                        conf = _containment_confidence(con, child, col, parent, parent_col)
                    except Exception:
                        conf = 0.0
                    if conf >= 0.8:
                        results.append(
                            {
                                "from_table": child,
                                "from_column": col,
                                "to_table": parent,
                                "to_column": parent_col,
                                "confidence": round(conf, 2),
                            }
                        )
                        break  # one parent per child column
        return results
    finally:
        con.close()


def _containment_confidence(
    con, child: str, child_col: str, parent: str, parent_col: str
) -> float:
    row = con.execute(
        f'''
        WITH s AS (
            SELECT DISTINCT "{child_col}" AS v
            FROM "{child}"
            WHERE "{child_col}" IS NOT NULL
            USING SAMPLE 200 ROWS
        )
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN EXISTS (
                SELECT 1 FROM "{parent}" p WHERE p."{parent_col}" = s.v
            ) THEN 1 ELSE 0 END) AS matched
        FROM s;
        '''
    ).fetchone()
    total, matched = row
    if not total:
        return 0.0
    return float(matched) / float(total)


def full_schema(session_id: str) -> dict[str, Any]:
    # Fresh sessions have no DuckDB file yet — return an empty schema instead
    # of letting the read-only connect raise an IOException.
    from .session_manager import duckdb_path

    if not duckdb_path(session_id).exists():
        return {"tables": [], "relationships": []}
    tables = [describe_table(session_id, t) for t in get_tables(session_id)]
    rels = detect_relationships(session_id)
    return {"tables": tables, "relationships": rels}
