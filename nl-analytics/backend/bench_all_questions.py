from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
SESSION_ID = "b4bd984a8441"
OUT_JSON = Path("bench_results_all_questions.json")
TIMEOUT_SECONDS = 70.0

# Full bank from easiest to hardest (130 prompts)
QUESTIONS = [
    "How many customers are there?",
    "How many orders are there?",
    "How many products are there?",
    "How many suppliers are there?",
    "How many reviews are there?",
    "How many shipments are there?",
    "How many payment records are there?",
    "How many order_items rows are there?",
    "Show top 20 customers by customer_id.",
    "Show top 20 products by product_id.",
    "What is the min, max, and average product price?",
    "How many products are in each category?",
    "How many suppliers are in each country?",
    "How many reviews are there for each rating?",
    "What is the average review rating overall?",
    "How many unique payment methods exist?",
    "Count orders by order_status.",
    "Count shipments by shipping_status.",
    "Show all columns in customers with 10 sample rows.",
    "Show all columns in products with 10 sample rows.",
    "How many orders did each customer place?",
    "Top 10 customers by number of orders.",
    "Which suppliers have the most products?",
    "Top 10 products by number of reviews.",
    "Average rating by product.",
    "Average rating by supplier.",
    "Total reviews per supplier.",
    "Orders per day.",
    "Orders per month.",
    "Orders per year.",
    "Payments by payment method count.",
    "Payments by payment method percent.",
    "Shipments per carrier.",
    "Average shipping cost by carrier.",
    "Average shipping time by carrier.",
    "Which countries have the most suppliers?",
    "Top 10 cheapest products.",
    "Top 10 most expensive products.",
    "Products with no reviews.",
    "Customers with no orders.",
    "Top 10 products by quantity sold.",
    "Top 10 products by revenue.",
    "Top 10 suppliers by revenue.",
    "Revenue by category.",
    "Revenue by month.",
    "Revenue by payment method.",
    "Revenue by supplier country.",
    "Average order value by month.",
    "Average order value by day of week.",
    "Customers by total spend.",
    "Top 10 customers by spend.",
    "Top 10 customers by average order value.",
    "Repeat customers vs one-time customers.",
    "Products with highest average rating and at least 10 reviews.",
    "Suppliers with highest average rating and at least 20 reviews.",
    "Orders that have payment but no shipment.",
    "Orders that have shipment but no payment.",
    "Customers who ordered but never reviewed.",
    "Products ordered but never reviewed.",
    "Suppliers whose products have never been reviewed.",
    "For each supplier, what percent of their orders were paid by credit card?",
    "For each category, what percent of revenue came from each payment method?",
    "What is average shipping delay by supplier?",
    "Which suppliers have the highest late-shipment rate?",
    "Which customers have the highest return/cancel rate?",
    "Which products are high-sales but low-rating?",
    "Which products are low-sales but high-rating?",
    "Revenue from 5-star reviewed products by supplier.",
    "Revenue from products with no reviews by supplier.",
    "Average rating before vs after 2024-01-01.",
    "Customers who reviewed products they never purchased.",
    "Orders where payment amount doesn\'t match computed item total.",
    "Supplier concentration: percent of total revenue by top 5 suppliers.",
    "Category concentration: percent of total revenue by top category.",
    "Shipping cost as percent of order value by carrier.",
    "Customers with high spend but low review activity.",
    "Customers with many reviews but low spend.",
    "Supplier-level conversion: reviewed products that got sold.",
    "Product lifecycle: first sale date, last sale date, total sales.",
    "Products with longest gap between reviews.",
    "Top 5 customers by spend on products from a specific supplier.",
    "Top 5 suppliers by revenue from products with at least one 5-star review.",
    "Highest-rated supplier per category, tie break by review count.",
    "Category winners by revenue per month.",
    "Top 3 customers per supplier by spend.",
    "Top 3 products per category by revenue.",
    "For each supplier, median order value and 90th percentile order value.",
    "Customer cohorts by first order month and 30/60/90-day retention.",
    "RFM segmentation (recency, frequency, monetary).",
    "Churn risk: customers with declining monthly spend trend.",
    "New vs returning customer revenue by month.",
    "Rolling 7-day revenue and rolling 30-day revenue.",
    "Revenue decomposition: price effect vs quantity effect over time.",
    "Supplier-country monthly growth ranking.",
    "Payment-method share shift month-over-month.",
    "Products with accelerating/decelerating demand trend.",
    "Seasonality index by category (monthly normalization).",
    "Customers likely to repeat from recency and frequency.",
    "Review sentiment proxy from rating trend and volume.",
    "Basket diversity: average distinct categories per order by customer segment.",
    "Rank suppliers within each country by revenue and average rating.",
    "Top N products per month by revenue with dense ranking.",
    "Contribution of top 20 percent customers to total revenue.",
    "Gini-style inequality proxy for customer spend.",
    "Supplier share-of-wallet by customer.",
    "Cross-sell affinity: products frequently bought together.",
    "Category transition matrix between first and second purchases.",
    "Time-to-second-order distribution by acquisition month.",
    "Review lag: days between purchase and review by category.",
    "Shipping SLA breach rate by carrier and destination.",
    "Weighted rating by Bayesian shrinkage for products.",
    "Revenue-at-risk from low-rated high-volume products.",
    "Outlier detection: anomalous orders by z-score of value.",
    "Forecast-ready features: monthly lag features per category.",
    "Retention curve by customer cohort.",
    "Win-back candidates: high historic spend and long inactivity.",
    "Price elasticity proxy by product over time.",
    "Supplier reliability score from on-time rate, rating, and fulfillment.",
    "Customer quality score from CLV proxy, return behavior, and engagement.",
    "Composite leaderboard: supplier rank by revenue, rating, and fulfillment.",
    "Top N dimensions by metric Y.",
    "Bottom N dimensions by metric Y.",
    "Trend of metric Y by day/week/month/quarter/year.",
    "Compare metric Y across segment A vs segment B.",
    "Share percentage of metric Y by dimension X.",
    "Correlation between metric A and metric B.",
    "Before and after date D analysis for metric Y.",
    "Cohort retention by first event date.",
    "Top K per category using rank within group.",
    "Exception report where expected business rule fails.",
]


@dataclass
class AskResult:
    question: str
    ok: bool
    status: str
    error: str | None
    sql: str | None
    elapsed_ms: int


def ask_once(client: httpx.Client, question: str, timeout_s: float = TIMEOUT_SECONDS) -> AskResult:
    url = f"{BASE_URL}/sessions/{SESSION_ID}/ask"
    start = time.time()

    got_done = False
    got_result = False
    got_error = None
    last_sql = None

    with client.stream("POST", url, json={"question": question}, timeout=timeout_s) as r:
        r.raise_for_status()

        event = None
        data_lines: list[str] = []

        for raw in r.iter_lines():
            line = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
            line = line.rstrip("\r")

            if line == "":
                if event is not None:
                    payload = "\n".join(data_lines).strip()
                    obj = None
                    if payload:
                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError:
                            obj = None

                    if event == "sql" and isinstance(obj, dict):
                        last_sql = obj.get("sql")
                    elif event == "error":
                        if isinstance(obj, dict):
                            got_error = obj.get("message") or payload
                        else:
                            got_error = payload or "unknown error"
                        break
                    elif event == "result":
                        got_result = True
                        break
                    elif event == "done":
                        got_done = True
                        break

                event = None
                data_lines = []
                continue

            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())

    elapsed = int((time.time() - start) * 1000)

    if (got_done or got_result) and not got_error:
        return AskResult(question, True, "ok", None, last_sql, elapsed)
    if got_error:
        return AskResult(question, False, "error", got_error, last_sql, elapsed)
    return AskResult(question, False, "unknown", "stream ended without done/error", last_sql, elapsed)


def classify_error(msg: str | None) -> str:
    if not msg:
        return "unknown"
    m = msg.lower()
    if "could not reach ollama" in m or "connection" in m:
        return "infra"
    if "validation:" in m:
        return "validation"
    if "binder error" in m or "parser" in m or "execution:" in m:
        return "sql_logic"
    return "other"


def main() -> None:
    results: list[dict] = []
    done_idxs: set[int] = set()

    if OUT_JSON.exists():
        try:
            existing = json.loads(OUT_JSON.read_text(encoding="utf-8"))
            existing_results = existing.get("results", [])
            if isinstance(existing_results, list):
                for row in existing_results:
                    if isinstance(row, dict) and isinstance(row.get("idx"), int):
                        done_idxs.add(row["idx"])
                        results.append(row)
                if done_idxs:
                    print(f"Resuming from checkpoint: {len(done_idxs)} already completed", flush=True)
        except Exception:
            pass

    with httpx.Client() as client:
        for i, q in enumerate(QUESTIONS, start=1):
            if i in done_idxs:
                continue
            print(f"[{i:03d}/{len(QUESTIONS)}] {q}", flush=True)
            try:
                res = ask_once(client, q)
            except Exception as e:
                res = AskResult(
                    question=q,
                    ok=False,
                    status="client_error",
                    error=str(e),
                    sql=None,
                    elapsed_ms=0,
                )

            bucket = classify_error(res.error)
            row = {
                "idx": i,
                "question": res.question,
                "ok": res.ok,
                "status": res.status,
                "error": res.error,
                "error_bucket": bucket,
                "sql": res.sql,
                "elapsed_ms": res.elapsed_ms,
            }
            results.append(row)

            # checkpoint each question so long runs are resumable/inspectable
            OUT_JSON.write_text(
                json.dumps({"summary": {"in_progress": True}, "results": results}, indent=2),
                encoding="utf-8",
            )

            verdict = "OK" if res.ok else f"FAIL ({bucket})"
            print(f"    -> {verdict} in {res.elapsed_ms} ms", flush=True)

    total = len(results)
    ok = sum(1 for r in results if r["ok"])
    fail = total - ok

    by_bucket: dict[str, int] = {}
    for r in results:
        if r["ok"]:
            continue
        by_bucket[r["error_bucket"]] = by_bucket.get(r["error_bucket"], 0) + 1

    avg_ms_ok = int(sum(r["elapsed_ms"] for r in results if r["ok"]) / max(ok, 1))

    summary = {
        "session_id": SESSION_ID,
        "base_url": BASE_URL,
        "total_questions": total,
        "ok_answers": ok,
        "failed_answers": fail,
        "accuracy_percent": round((ok / total) * 100, 2),
        "avg_elapsed_ms_for_ok": avg_ms_ok,
        "failure_buckets": by_bucket,
    }

    payload = {"summary": summary, "results": results}
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"Saved report to: {OUT_JSON.resolve()}")


if __name__ == "__main__":
    main()
