from __future__ import annotations

from decimal import Decimal
from typing import Any


def narrate_from_rows(
    question: str,
    columns: list[str],
    rows: list[list[Any]],
    total_rows: int,
) -> str:
    if not rows:
        return "Summary: No rows matched the question.\nInsights:\n- The result set is empty."

    preview_count = len(rows)
    row_dicts = [dict(zip(columns, row, strict=False)) for row in rows]
    top_row = row_dicts[0]
    summary = f"Summary: Top result: {_format_row(top_row, max_items=4)}"

    insights: list[str] = [
        f"- Showing {preview_count} of {total_rows} rows from the result."
    ]

    numeric_cols = [
        col for col in columns
        if any(_to_number(row_dict.get(col)) is not None for row_dict in row_dicts[:3])
    ]
    key_numeric = numeric_cols[0] if numeric_cols else None

    if key_numeric is not None:
        top_value = _to_number(top_row.get(key_numeric))
        if top_value is not None:
            insights.append(
                f"- The leading row has {key_numeric} = {_format_scalar(top_row.get(key_numeric))}."
            )

    if len(row_dicts) > 1:
        second_row = row_dicts[1]
        if key_numeric is not None:
            top_value = _to_number(top_row.get(key_numeric))
            second_value = _to_number(second_row.get(key_numeric))
            if top_value is not None and second_value is not None:
                diff = top_value - second_value
                insights.append(
                    f"- Compared with the next row, the difference in {key_numeric} is {_format_number(diff)}."
                )
            else:
                insights.append(
                    f"- The next row is {_format_row(second_row, max_items=3)}."
                )
        else:
            insights.append(
                f"- The next row is {_format_row(second_row, max_items=3)}."
            )

    if total_rows > preview_count:
        insights.append(
            "- Additional rows exist beyond the preview, but this summary only uses visible rows."
        )

    return summary + "\nInsights:\n" + "\n".join(insights[:4])


def _format_row(row: dict[str, Any], max_items: int) -> str:
    items = []
    for index, (key, value) in enumerate(row.items()):
        if index >= max_items:
            break
        items.append(f"{key}={_format_scalar(value)}")
    return ", ".join(items)


def _format_scalar(value: Any) -> str:
    number = _to_number(value)
    if number is not None:
        return _format_number(number)
    if value is None:
        return "NULL"
    return str(value)


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return None


def _format_number(value: float) -> str:
    rounded = round(value, 2)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}"