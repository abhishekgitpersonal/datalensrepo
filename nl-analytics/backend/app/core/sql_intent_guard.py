"""Question-aware SQL intent checks to catch semantically wrong but executable SQL."""
from __future__ import annotations

import re


def find_intent_violations(question: str, sql: str) -> list[str]:
    q = (question or "").lower()
    s = (sql or "").lower()
    issues: list[str] = []

    asks_revenue = bool(re.search(r"revenue|sales|gmv|income", q))
    asks_payment_specific = bool(re.search(r"payment|transaction|paid|collection|payment\s+method", q))
    uses_payment_amount = "payment" in s and re.search(r"\b(amount|payment_method|transaction_status)\b", s)
    if asks_revenue and not asks_payment_specific and uses_payment_amount:
        issues.append(
            "Generic revenue questions should use sales/order revenue (for example orders.total_price or item revenue), not payment.amount unless payments are explicitly requested."
        )

    # Historical data questions should derive recency from data, not system date.
    if re.search(r"latest|most\s+recent|last\s+month", q):
        if "current_date" in s or "now()" in s:
            issues.append(
                "Use data-driven recency (MAX(date_col)) instead of CURRENT_DATE/NOW() for latest-month logic."
            )

    # If question asks order counts and SQL joins detail tables, COUNT(*) inflates counts.
    asks_order_count = bool(re.search(r"order\s+count|count\s+of\s+orders", q))
    has_join = " join " in s
    count_star = bool(re.search(r"count\s*\(\s*(\*|1)\s*\)", s))
    has_distinct_order = bool(re.search(r"count\s*\(\s*distinct\s+[^\)]*order_id", s))
    if asks_order_count and has_join and count_star and not has_distinct_order:
        issues.append(
            "Order count with joins must use COUNT(DISTINCT order_id), not COUNT(*)."
        )

    # Concentration/share questions should use individual share, not cumulative windows.
    asks_concentration = bool(re.search(r"concentrat|share|percentage", q))
    asks_cumulative = bool(re.search(r"cumulative|running", q))
    uses_cumulative_window = "over (order by" in s
    if asks_concentration and not asks_cumulative and uses_cumulative_window:
        issues.append(
            "Concentration should use individual share (value / total), not cumulative running percentage."
        )

    # Seasonal-by-quarter usually means quarter-of-year pattern, not quarter timeline buckets.
    asks_seasonal_quarter = "season" in q and "quarter" in q
    uses_quarter_bucket = "date_trunc('quarter'" in s or 'date_trunc("quarter"' in s
    uses_quarter_number = "extract(quarter" in s or "date_part('quarter'" in s
    if asks_seasonal_quarter and uses_quarter_bucket and not uses_quarter_number:
        issues.append(
            "Seasonal-by-quarter analysis should group by quarter number (EXTRACT(quarter FROM date_col))."
        )

    return issues
