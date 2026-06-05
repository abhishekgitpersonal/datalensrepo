"""Pick a sensible chart type from a result DataFrame. Returns a Plotly figure dict."""
from __future__ import annotations

from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_chart_spec(spec: dict[str, Any]) -> bool:
    """Return True only when the chart spec is safe to send to the browser.

    Catches empty data arrays, mismatched x/y lengths, and all-null traces
    that would cause Plotly to render a blank or error state.
    """
    if not spec:
        return False
    traces = spec.get("data", [])
    if not traces:
        return False
    for trace in traces:
        x = trace.get("x") or trace.get("labels") or []
        y = trace.get("y") or trace.get("values") or []
        if not x and not y:
            return False
        if x and y and len(x) != len(y):
            return False

        def _all_empty(arr: list) -> bool:
            return all(v is None or (isinstance(v, float) and v != v) for v in arr)

        if x and _all_empty(x):
            return False
        if y and _all_empty(y):
            return False
    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def pick_chart(df: pd.DataFrame) -> dict[str, Any] | None:
    """Build a chart spec from *df*, validate it, and return it or None."""
    spec = _build_chart(df)
    if spec is None:
        return None
    if not _validate_chart_spec(spec):
        return None
    return spec


# ---------------------------------------------------------------------------
# Internal chart-selection logic
# ---------------------------------------------------------------------------

def _build_chart(df: pd.DataFrame) -> dict[str, Any] | None:
    if df is None or df.empty:
        return None
    if len(df) == 1 and df.shape[1] == 1:
        return None  # single scalar — no chart needed

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    date_cols = [
        c for c in df.columns
        if pd.api.types.is_datetime64_any_dtype(df[c]) or _looks_like_date(df[c])
    ]
    cat_cols = [c for c in df.columns if c not in numeric_cols and c not in date_cols]

    # Time series: date-like axis + numeric measures
    if date_cols and numeric_cols:
        x = _best_time_axis(date_cols)
        xs = pd.to_datetime(df[x], errors="coerce").astype(str).tolist()
        traces = [
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": c,
                "x": xs,
                "y": [v if v is not None and v == v else None for v in df[c].tolist()],
            }
            for c in numeric_cols[:5]
        ]
        return _fig(traces, title=f"{', '.join(numeric_cols[:5])} over {x}", xaxis=x, yaxis="value")

    # 1 categorical + 1 numeric
    if len(cat_cols) == 1 and len(numeric_cols) == 1:
        c, n = cat_cols[0], numeric_cols[0]
        head = df.head(50).copy()
        if pd.api.types.is_numeric_dtype(head[n]):
            head = head.sort_values(by=n, ascending=False)
        labels = head[c].astype(str).tolist()
        values = head[n].tolist()

        if 2 <= len(head) <= 8:
            traces = [{"type": "pie", "labels": labels, "values": values, "name": n}]
            return _fig(traces, title=f"{n} share by {c}", xaxis=c, yaxis=n)

        traces = [{"type": "bar", "x": labels[:30], "y": values[:30], "name": n}]
        return _fig(traces, title=f"{n} by {c}", xaxis=c, yaxis=n)

    # 2+ numeric => scatter
    if len(numeric_cols) >= 2 and len(df) > 1:
        x, y = numeric_cols[0], numeric_cols[1]
        traces = [{
            "type": "scatter",
            "mode": "markers",
            "x": df[x].tolist(),
            "y": df[y].tolist(),
            "name": f"{y} vs {x}",
        }]
        return _fig(traces, title=f"{y} vs {x}", xaxis=x, yaxis=y)

    # Multiple cats + numeric => grouped bar on first cat
    if cat_cols and numeric_cols:
        c, n = cat_cols[0], numeric_cols[0]
        head = df.head(30)
        traces = [{"type": "bar", "x": head[c].astype(str).tolist(), "y": head[n].tolist(), "name": n}]
        return _fig(traces, title=f"{n} by {c}", xaxis=c, yaxis=n)

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _best_time_axis(date_cols: list[str]) -> str:
    ranked = sorted(
        date_cols,
        key=lambda c: 0 if any(k in c.lower() for k in ["date", "time", "month", "week", "year"]) else 1,
    )
    return ranked[0]


def _looks_like_date(s: pd.Series) -> bool:
    if s.dtype != object:
        return False
    sample = s.dropna().astype(str).head(5)
    if sample.empty:
        return False
    try:
        pd.to_datetime(sample, errors="raise")
        return True
    except Exception:
        return False


def _fig(traces: list[dict], title: str, xaxis: str, yaxis: str) -> dict[str, Any]:
    return {
        "data": traces,
        "layout": {
            "title": title,
            "xaxis": {"title": xaxis},
            "yaxis": {"title": yaxis},
            "margin": {"l": 50, "r": 20, "t": 50, "b": 60},
            "height": 380,
        },
    }
