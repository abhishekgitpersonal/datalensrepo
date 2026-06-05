import duckdb
con = duckdb.connect()
print(con.execute("SELECT transaction_status, COUNT(*) AS n FROM read_csv_auto('C:/Users/abhishnair/OneDrive - Deloitte (O365D)/Documents/learning/Dummydata/payment.csv') GROUP BY 1 ORDER BY n DESC").fetchdf())
print()
print(con.execute("""
SELECT p.payment_method, p.transaction_status, COUNT(*) AS txn_count, ROUND(SUM(p.amount),2) AS total_amount
FROM read_csv_auto('C:/Users/abhishnair/OneDrive - Deloitte (O365D)/Documents/learning/Dummydata/orders.csv') o
JOIN read_csv_auto('C:/Users/abhishnair/OneDrive - Deloitte (O365D)/Documents/learning/Dummydata/payment.csv') p
  ON p.order_id = o.order_id
GROUP BY 1,2
ORDER BY 1,2
""").fetchdf())
