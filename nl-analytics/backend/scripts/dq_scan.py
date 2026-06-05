import duckdb
import pandas as pd
from pathlib import Path

D = Path(r"C:\Users\abhishnair\OneDrive - Deloitte (O365D)\Documents\learning\Dummydata")
con = duckdb.connect()

files = ["customers","orders","order_items","payment","products","reviews","shipments","suppliers"]
for name in files:
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv_auto('{D/(name+'.csv')}', HEADER=TRUE, ALL_VARCHAR=TRUE)")

def section(title):
    print("\n" + "="*90)
    print(title)
    print("="*90)

def show(sql, n=20):
    df = con.execute(sql).fetchdf()
    with pd.option_context('display.max_columns', None, 'display.width', 200, 'display.max_colwidth', 60):
        print(df.head(n).to_string(index=False))
    return df

# 1) Row counts and obvious null patterns
for name in files:
    section(f"{name}: per-column null counts and uniqueness")
    cols = [r[0] for r in con.execute(f"DESCRIBE {name}").fetchall()]
    parts = []
    for c in cols:
        parts.append(f"SUM(CASE WHEN \"{c}\" IS NULL OR TRIM(\"{c}\")='' THEN 1 ELSE 0 END) AS \"null_{c}\"")
    show(f"SELECT COUNT(*) AS rows, {', '.join(parts)} FROM {name}")

# 2) Cross-table referential integrity
section("REF: orders.customer_id present in customers?")
show("SELECT (SELECT COUNT(DISTINCT customer_id) FROM orders WHERE customer_id NOT IN (SELECT customer_id FROM customers)) AS orphan_customer_ids_in_orders")
section("REF: order_items.order_id present in orders?")
show("SELECT (SELECT COUNT(DISTINCT order_id) FROM order_items WHERE order_id NOT IN (SELECT order_id FROM orders)) AS orphan_order_ids_in_items")
section("REF: order_items.product_id present in products?")
show("SELECT (SELECT COUNT(DISTINCT product_id) FROM order_items WHERE product_id NOT IN (SELECT product_id FROM products)) AS orphan_product_ids_in_items")
section("REF: payment.order_id present in orders?")
show("SELECT (SELECT COUNT(DISTINCT order_id) FROM payment WHERE order_id NOT IN (SELECT order_id FROM orders)) AS orphan_order_ids_in_payment")
section("REF: shipments.order_id present in orders?")
show("SELECT (SELECT COUNT(DISTINCT order_id) FROM shipments WHERE order_id NOT IN (SELECT order_id FROM orders)) AS orphan_order_ids_in_shipments")
section("REF: products.supplier_id present in suppliers?")
show("SELECT (SELECT COUNT(DISTINCT supplier_id) FROM products WHERE supplier_id NOT IN (SELECT supplier_id FROM suppliers)) AS orphan_supplier_ids_in_products")
section("REF: reviews.product_id present in products?")
show("SELECT (SELECT COUNT(DISTINCT product_id) FROM reviews WHERE product_id NOT IN (SELECT product_id FROM products)) AS orphan_product_ids_in_reviews")
section("REF: reviews.customer_id present in customers?")
show("SELECT (SELECT COUNT(DISTINCT customer_id) FROM reviews WHERE customer_id NOT IN (SELECT customer_id FROM customers)) AS orphan_customer_ids_in_reviews")

# 3) Duplicates on primary-ish keys
for tbl, key in [("customers","customer_id"),("orders","order_id"),("order_items","order_item_id"),
                 ("payment","payment_id"),("products","product_id"),("reviews","review_id"),
                 ("shipments","shipment_id"),("suppliers","supplier_id")]:
    section(f"DUP: {tbl}.{key}")
    show(f"SELECT {key}, COUNT(*) AS n FROM {tbl} GROUP BY 1 HAVING n>1 ORDER BY n DESC")

# 4) Bad numeric/date strings
section("orders.total_price non-numeric or negative")
show("SELECT total_price, COUNT(*) AS n FROM orders WHERE TRY_CAST(total_price AS DOUBLE) IS NULL OR TRY_CAST(total_price AS DOUBLE) < 0 GROUP BY 1 ORDER BY n DESC LIMIT 20")

section("orders.order_date un-parseable")
show("SELECT order_date, COUNT(*) AS n FROM orders WHERE TRY_CAST(order_date AS DATE) IS NULL GROUP BY 1 ORDER BY n DESC LIMIT 20")

section("order_items numeric issues")
show("SELECT COUNT(*) FILTER (WHERE TRY_CAST(quantity AS BIGINT) IS NULL) AS bad_qty, COUNT(*) FILTER (WHERE TRY_CAST(price_at_purchase AS DOUBLE) IS NULL) AS bad_price, COUNT(*) FILTER (WHERE TRY_CAST(quantity AS BIGINT) <= 0) AS nonpos_qty, COUNT(*) FILTER (WHERE TRY_CAST(price_at_purchase AS DOUBLE) < 0) AS neg_price FROM order_items")

section("products numeric issues")
show("SELECT COUNT(*) FILTER (WHERE TRY_CAST(price AS DOUBLE) IS NULL) AS bad_price, COUNT(*) FILTER (WHERE TRY_CAST(price AS DOUBLE) < 0) AS neg_price FROM products")

section("payment numeric / status values")
show("SELECT COUNT(*) FILTER (WHERE TRY_CAST(amount AS DOUBLE) IS NULL) AS bad_amount, COUNT(*) FILTER (WHERE TRY_CAST(amount AS DOUBLE) < 0) AS neg_amount FROM payment")
section("payment.transaction_status distinct values")
show("SELECT transaction_status, COUNT(*) AS n FROM payment GROUP BY 1 ORDER BY n DESC")
section("payment.payment_method distinct values")
show("SELECT payment_method, COUNT(*) AS n FROM payment GROUP BY 1 ORDER BY n DESC")

section("shipments.shipment_date / delivery_date un-parseable; ordering")
show("SELECT COUNT(*) FILTER (WHERE TRY_CAST(shipment_date AS DATE) IS NULL) AS bad_ship, COUNT(*) FILTER (WHERE TRY_CAST(delivery_date AS DATE) IS NULL) AS bad_deliv, COUNT(*) FILTER (WHERE TRY_CAST(shipment_date AS DATE) IS NOT NULL AND TRY_CAST(delivery_date AS DATE) IS NOT NULL AND TRY_CAST(delivery_date AS DATE) < TRY_CAST(shipment_date AS DATE)) AS deliv_before_ship FROM shipments")
section("shipments.shipment_status distinct")
show("SELECT shipment_status, COUNT(*) AS n FROM shipments GROUP BY 1 ORDER BY n DESC")
section("shipments.carrier distinct")
show("SELECT carrier, COUNT(*) AS n FROM shipments GROUP BY 1 ORDER BY n DESC")

section("reviews.rating outside 1..5 / non-numeric")
show("SELECT rating, COUNT(*) AS n FROM reviews WHERE TRY_CAST(rating AS DOUBLE) IS NULL OR TRY_CAST(rating AS DOUBLE) < 1 OR TRY_CAST(rating AS DOUBLE) > 5 GROUP BY 1 ORDER BY n DESC LIMIT 20")

section("customers.email patterns missing @")
show("SELECT COUNT(*) FILTER (WHERE email NOT LIKE '%@%') AS missing_at FROM customers")
section("customers duplicates by email")
show("SELECT email, COUNT(*) AS n FROM customers GROUP BY 1 HAVING n>1 ORDER BY n DESC LIMIT 20")

section("orders.total_price vs sum(order_items)")
show("""
WITH oi AS (SELECT order_id, SUM(TRY_CAST(quantity AS DOUBLE) * TRY_CAST(price_at_purchase AS DOUBLE)) AS items_sum FROM order_items GROUP BY 1)
SELECT COUNT(*) AS mismatched
FROM orders o JOIN oi USING (order_id)
WHERE ABS(TRY_CAST(o.total_price AS DOUBLE) - oi.items_sum) > 0.01
""")
