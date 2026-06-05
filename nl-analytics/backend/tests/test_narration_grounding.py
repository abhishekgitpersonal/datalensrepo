import unittest

from app.llm.prompts import build_deterministic_narration, narration_is_grounded


class NarrationGroundingTests(unittest.TestCase):
    def test_rejects_invented_numeric_claims(self):
        text = (
            "Summary: Mary and John combined spent 43111.08.\n"
            "Insights:\n- Sunday had 22 orders."
        )
        columns = ["first_name", "last_name", "total_spent"]
        rows = [
            ["John", "Williams", 19651.7],
            ["James", "Natalie", 17567.0],
        ]
        self.assertFalse(
            narration_is_grounded(
                text,
                "Which 10 customers have spent the most total money across all their orders?",
                columns,
                rows,
                total_rows=10,
            )
        )

    def test_rejects_hallucinated_entity_names(self):
        """Reject narration that mentions customer names not in the result set."""
        text = (
            "Explanation: The top 10 customers are James Garcia, James Jones, James Smith, "
            "and also Samuel, Lawrence, Roger, Patrick, Alexander, Diana, Lauren.\n"
            "Insights:\n- Samuel, Lawrence, Roger are in the top 10."
        )
        columns = ["first_name", "last_name", "order_count"]
        rows = [
            ["James", "Garcia", 5],
            ["James", "Jones", 4],
            ["James", "Smith", 3],
            ["James", "Brown", 2],
            ["James", "Davis", 1],
        ]
        # This should be rejected because Samuel, Lawrence, Roger don't appear in the result
        self.assertFalse(
            narration_is_grounded(
                text,
                "Top 10 customers by orders",
                columns,
                rows,
                total_rows=10,
            )
        )

    def test_accepts_grounded_entity_names(self):
        """Accept narration that only mentions entities present in result."""
        text = (
            "Explanation: The top 5 customers by orders are James Garcia (5 orders), "
            "James Jones (4 orders), and James Smith (3 orders).\n"
            "Insights:\n- James Garcia leads, followed by James Jones."
        )
        columns = ["first_name", "last_name", "order_count"]
        rows = [
            ["James", "Garcia", 5],
            ["James", "Jones", 4],
            ["James", "Smith", 3],
        ]
        self.assertTrue(
            narration_is_grounded(
                text,
                "Top 10 customers by orders",
                columns,
                rows,
                total_rows=10,
            )
        )

    def test_rejects_hallucinated_product_names_in_lists(self):
        """Reject narration mentioning products not in the result set (from the real bug)."""
        text = (
            "Explanation: The top-rated product is a tie between Phone Grip, Food Processor, "
            "Microphone, Gaming Mouse Pad, Power Strip, Smart Watch, Portable Charger, "
            "Document Scanner, Bluetooth Headphones, and Bath Towels, all of which have "
            "an average rating of 4.0 or higher."
        )
        columns = ["product_name", "review_count", "avg_rating"]
        rows = [
            ["Coffee Maker", 7, 1.0],
            ["Computer Speakers", 7, 2.0],
            ["Smart Watch", 7, 5.0],
            ["Desk Organizer", 7, 3.0],
            ["Webcam HD", 7, 1.0],
        ]
        # Should reject because Phone Grip, Food Processor, Microphone, etc.
        # don't appear in the actual result set
        self.assertFalse(
            narration_is_grounded(
                text,
                "Top 10 products by review count",
                columns,
                rows,
                total_rows=10,
            )
        )

    def test_accepts_only_result_set_products(self):
        """Accept narration that mentions only products from the result set."""
        text = (
            "Explanation: The top products include Coffee Maker (7 reviews, 1.0 rating), "
            "Computer Speakers (7 reviews, 2.0 rating), and Smart Watch (7 reviews, 5.0 rating)."
        )
        columns = ["product_name", "review_count", "avg_rating"]
        rows = [
            ["Coffee Maker", 7, 1.0],
            ["Computer Speakers", 7, 2.0],
            ["Smart Watch", 7, 5.0],
        ]
        self.assertTrue(
            narration_is_grounded(
                text,
                "Top 10 products by review count",
                columns,
                rows,
                total_rows=10,
            )
        )
    def test_accepts_visible_values_only(self):
        text = (
            "Summary: Top result is first_name=John, last_name=Williams, total_spent=19651.7.\n"
            "Insights:\n- The full result has 10 total row(s)."
        )
        columns = ["first_name", "last_name", "total_spent"]
        rows = [
            ["John", "Williams", 19651.7],
            ["James", "Natalie", 17567.0],
        ]
        self.assertTrue(
            narration_is_grounded(
                text,
                "Which 10 customers have spent the most total money across all their orders?",
                columns,
                rows,
                total_rows=10,
            )
        )

    def test_deterministic_narration_has_safe_shape(self):
        out = build_deterministic_narration(
            "Which 10 customers have spent the most total money across all their orders?",
            ["first_name", "last_name", "total_spent"],
            [["John", "Williams", 19651.7], ["James", "Natalie", 17567.0]],
            10,
        )
        self.assertIn("Explanation:", out)
        self.assertIn("Summary:", out)
        self.assertIn("Insights:", out)
        self.assertIn("John Williams", out)
        self.assertIn("19651.7", out)


if __name__ == "__main__":
    unittest.main()