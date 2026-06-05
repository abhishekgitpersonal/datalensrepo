import unittest

from app.llm.prompts import build_sql_prompt, filter_history_for_sql, focus_schema_for_question


SCHEMA = {
    "tables": [
        {
            "name": "customers",
            "row_count": 10000,
            "columns": [
                {"name": "customer_id", "type": "BIGINT"},
                {"name": "first_name", "type": "VARCHAR"},
                {"name": "last_name", "type": "VARCHAR"},
            ],
        },
        {
            "name": "orders",
            "row_count": 15000,
            "columns": [
                {"name": "order_id", "type": "BIGINT"},
                {"name": "order_date", "type": "DATE"},
                {"name": "customer_id", "type": "BIGINT"},
                {"name": "total_price", "type": "DOUBLE"},
            ],
        },
        {
            "name": "payment",
            "row_count": 15000,
            "columns": [
                {"name": "payment_id", "type": "BIGINT"},
                {"name": "order_id", "type": "BIGINT"},
                {"name": "payment_method", "type": "VARCHAR"},
            ],
        },
        {
            "name": "shipments",
            "row_count": 15000,
            "columns": [
                {"name": "shipment_id", "type": "BIGINT"},
                {"name": "order_id", "type": "BIGINT"},
                {"name": "shipment_date", "type": "DATE"},
                {"name": "delivery_date", "type": "DATE"},
            ],
        },
        {
            "name": "products",
            "row_count": 2000,
            "columns": [
                {"name": "product_id", "type": "BIGINT"},
                {"name": "product_name", "type": "VARCHAR"},
            ],
        },
    ],
    "relationships": [
        {
            "from_table": "orders",
            "from_column": "customer_id",
            "to_table": "customers",
            "to_column": "customer_id",
            "confidence": 1,
        },
        {
            "from_table": "payment",
            "from_column": "order_id",
            "to_table": "orders",
            "to_column": "order_id",
            "confidence": 1,
        },
        {
            "from_table": "shipments",
            "from_column": "order_id",
            "to_table": "orders",
            "to_column": "order_id",
            "confidence": 1,
        },
    ],
}


class PromptFocusingTests(unittest.TestCase):
    def test_focuses_customer_spend_question_to_two_tables(self):
        focused = focus_schema_for_question(
            "Which 10 customers have spent the most total money across all their orders?",
            SCHEMA,
        )

        self.assertEqual(
            {table["name"] for table in focused["tables"]},
            {"customers", "orders"},
        )

    def test_focuses_shipping_question_to_orders_and_shipments(self):
        focused = focus_schema_for_question(
            "What percentage of orders were shipped more than 7 days after order_date?",
            SCHEMA,
        )

        self.assertEqual(
            {table["name"] for table in focused["tables"]},
            {"orders", "shipments"},
        )

    def test_filter_history_keeps_only_user_questions(self):
        history = [
            {"role": "user", "question": "How many orders are there?"},
            {"role": "assistant", "text": "There are 15000 orders.", "sql": "SELECT COUNT(*) FROM orders"},
            {"role": "user", "question": "Which 10 customers have spent the most?"},
        ]

        filtered = filter_history_for_sql(history)

        self.assertEqual(
            filtered,
            [
                {"role": "user", "question": "How many orders are there?"},
                {"role": "user", "question": "Which 10 customers have spent the most?"},
            ],
        )

    def test_sql_prompt_does_not_embed_previous_assistant_sql(self):
        prompt = build_sql_prompt(
            "Which 10 customers have spent the most total money across all their orders?",
            SCHEMA,
            filter_history_for_sql(
                [
                    {"role": "user", "question": "How many orders are there?"},
                    {"role": "assistant", "text": "There are 15000 orders.", "sql": "SELECT COUNT(*) FROM orders"},
                ]
            ),
        )

        self.assertIn("User: How many orders are there?", prompt)
        self.assertNotIn("Assistant SQL:", prompt)
        self.assertNotIn("SELECT COUNT(*) FROM orders", prompt)


if __name__ == "__main__":
    unittest.main()