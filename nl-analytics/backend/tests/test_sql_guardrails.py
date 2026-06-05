import unittest

from app.core.sql_validator import SqlValidationError, validate_and_prepare


ALLOWED_TABLES = {"customers", "orders", "order_items", "products", "reviews"}
TABLE_COLUMNS = {
    "customers": {"customer_id", "first_name", "last_name"},
    "orders": {"order_id", "customer_id", "ordered_at"},
    "order_items": {"order_id", "product_id", "quantity"},
    "products": {"product_id", "supplier_id", "price"},
    "reviews": {"review_id", "customer_id", "product_id", "rating"},
}
RELATIONSHIPS = [
    {
        "from_table": "orders",
        "from_column": "customer_id",
        "to_table": "customers",
        "to_column": "customer_id",
    },
    {
        "from_table": "order_items",
        "from_column": "order_id",
        "to_table": "orders",
        "to_column": "order_id",
    },
    {
        "from_table": "order_items",
        "from_column": "product_id",
        "to_table": "products",
        "to_column": "product_id",
    },
    {
        "from_table": "reviews",
        "from_column": "customer_id",
        "to_table": "customers",
        "to_column": "customer_id",
    },
    {
        "from_table": "reviews",
        "from_column": "product_id",
        "to_table": "products",
        "to_column": "product_id",
    },
]


class SqlGuardrailsTests(unittest.TestCase):
    def _validate(self, sql: str) -> str:
        return validate_and_prepare(
            sql,
            ALLOWED_TABLES,
            row_limit=100,
            table_columns=TABLE_COLUMNS,
            relationships=RELATIONSHIPS,
        )

    def test_valid_multi_hop_join_passes(self):
        sql = """
        SELECT c.customer_id, SUM(oi.quantity) AS qty
        FROM customers AS c
        JOIN orders AS o ON o.customer_id = c.customer_id
        JOIN order_items AS oi ON oi.order_id = o.order_id
        JOIN products AS p ON p.product_id = oi.product_id
        GROUP BY c.customer_id
        """
        out = self._validate(sql)
        self.assertIn("LIMIT", out.upper())

    def test_invalid_direct_join_is_rejected(self):
        sql = """
        SELECT c.customer_id
        FROM customers c
        JOIN products p ON c.customer_id = p.product_id
        """
        with self.assertRaises(SqlValidationError) as ctx:
            self._validate(sql)
        self.assertIn("JOIN does not follow known relationships", str(ctx.exception))

    def test_wrong_alias_column_is_rejected(self):
        sql = """
        SELECT c.customer_id
        FROM customers c
        JOIN reviews r ON c.customer_id = r.order_id
        """
        with self.assertRaises(SqlValidationError) as ctx:
            self._validate(sql)
        self.assertIn("does not exist on table", str(ctx.exception))

    def test_reverse_edge_direction_is_allowed(self):
        sql = """
        SELECT o.order_id
        FROM orders o
        JOIN customers c ON c.customer_id = o.customer_id
        """
        out = self._validate(sql)
        self.assertIn("LIMIT", out.upper())

    def test_day_of_week_daypart_misuse_is_rejected(self):
        sql = """
        SELECT DATE_PART('day', o.ordered_at) AS day_of_week, AVG(1) AS avg_x
        FROM orders o
        GROUP BY day_of_week
        """
        with self.assertRaises(SqlValidationError) as ctx:
            self._validate(sql)
        self.assertIn("DATE_PART('day', ...)", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
