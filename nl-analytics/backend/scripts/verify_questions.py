import duckdb
from pathlib import Path

D = Path(r"C:\Users\abhishnair\OneDrive - Deloitte (O365D)\Documents\learning\Dummydata")
con = duckdb.connect()
for name in ["customers","orders","order_items","payment","products","reviews","shipments","suppliers"]:
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv_auto('{D / (name + '.csv')}', HEADER=TRUE)")

def show(title, sql):
    print("="*80)
    print(title)
    print("-"*80)
    print(sql.strip())
    print("-"*80)
    print(con.execute(sql).fetchdf().to_string(index=False))
    print()

show("Q1: Top 5 customers by total spend (customers + orders)",
"""
SELECT c.first_name, c.last_name, ROUND(SUM(o.total_price),2) AS total_spent, COUNT(o.order_id) AS orders_count
FROM customers c JOIN orders o ON o.customer_id = c.customer_id
GROUP BY c.customer_id, c.first_name, c.last_name
ORDER BY total_spent DESC
LIMIT 5
""")

show("Q2: Top 5 product categories by revenue (order_items + products)",
"""
SELECT p.category, ROUND(SUM(oi.quantity * oi.price_at_purchase),2) AS revenue, SUM(oi.quantity) AS units
FROM order_items oi JOIN products p ON p.product_id = oi.product_id
GROUP BY p.category
ORDER BY revenue DESC
LIMIT 5
""")

show("Q3: Top 5 suppliers by revenue (suppliers + products + order_items)",
"""
SELECT s.supplier_name, ROUND(SUM(oi.quantity * oi.price_at_purchase),2) AS revenue
FROM suppliers s
JOIN products p ON p.supplier_id = s.supplier_id
JOIN order_items oi ON oi.product_id = p.product_id
GROUP BY s.supplier_id, s.supplier_name
ORDER BY revenue DESC
LIMIT 5
""")

show("Q4: Average shipping delay days by carrier (orders + shipments)",
"""
SELECT sh.carrier,
       ROUND(AVG(DATE_DIFF('day', o.order_date::DATE, sh.shipment_date::DATE)),2) AS avg_delay_days,
       COUNT(*) AS shipments
FROM orders o JOIN shipments sh ON sh.order_id = o.order_id
GROUP BY sh.carrier
ORDER BY avg_delay_days
""")

show("Q5: Payment method totals among successful transactions (orders + payment)",
"""
SELECT p.payment_method, COUNT(*) AS txn_count, ROUND(SUM(p.amount),2) AS total_amount
FROM orders o JOIN payment p ON p.order_id = o.order_id
WHERE LOWER(p.transaction_status) = 'success'
GROUP BY p.payment_method
ORDER BY total_amount DESC
""")

show("Q6: Top 5 highest-rated products with at least 5 reviews (products + reviews)",
"""
SELECT p.product_name, ROUND(AVG(r.rating),2) AS avg_rating, COUNT(*) AS review_count
FROM products p JOIN reviews r ON r.product_id = p.product_id
GROUP BY p.product_id, p.product_name
HAVING COUNT(*) >= 5
ORDER BY avg_rating DESC, review_count DESC
LIMIT 5
""")

show("Q7: Weekday of order with highest order count (orders only — single table, skip)",
"""
SELECT 1 AS skip
""")

show("Q7b: Best month by order revenue (orders + order_items)",
"""
SELECT STRFTIME(o.order_date::DATE, '%Y-%m') AS month,
       ROUND(SUM(oi.quantity * oi.price_at_purchase),2) AS revenue,
       COUNT(DISTINCT o.order_id) AS orders
FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
GROUP BY month
ORDER BY revenue DESC
LIMIT 5
""")
