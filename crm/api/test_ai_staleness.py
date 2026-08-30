"""Unit coverage for fail-closed AI read-model freshness handling."""

from datetime import datetime, timedelta
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api._ai_staleness import ai_field_or_unavailable


class TestAIStaleness(FrappeTestCase):
    def test_missing_timestamp_is_unavailable(self):
        result = ai_field_or_unavailable({"ai_summary": "old"}, "ai_summary")

        self.assertFalse(result["ai_available"])
        self.assertEqual(result["reason"], "missing_generated_at")

    def test_stale_value_is_hidden(self):
        now = datetime(2026, 8, 29, 12, 0, 0)
        with patch("crm.api._ai_staleness.now_datetime", return_value=now):
            result = ai_field_or_unavailable(
                {
                    "ai_summary": "old",
                    "ai_generated_at": now - timedelta(days=2),
                },
                "ai_summary",
                threshold_seconds=86_400,
            )

        self.assertFalse(result["ai_available"])
        self.assertEqual(result["reason"], "stale")
        self.assertNotIn("value", result)

    def test_fresh_value_is_returned(self):
        now = datetime(2026, 8, 29, 12, 0, 0)
        with patch("crm.api._ai_staleness.now_datetime", return_value=now):
            result = ai_field_or_unavailable(
                {
                    "ai_summary": "fresh",
                    "ai_generated_at": now - timedelta(minutes=5),
                },
                "ai_summary",
                threshold_seconds=86_400,
            )

        self.assertTrue(result["ai_available"])
        self.assertEqual(result["value"], "fresh")

    def test_fresh_missing_value_is_unavailable(self):
        now = datetime(2026, 8, 29, 12, 0, 0)
        with patch("crm.api._ai_staleness.now_datetime", return_value=now):
            result = ai_field_or_unavailable(
                {"ai_generated_at": now - timedelta(minutes=5)},
                "ai_summary",
                threshold_seconds=86_400,
            )

        self.assertFalse(result["ai_available"])
        self.assertEqual(result["reason"], "missing_value")

    def test_invalid_threshold_is_unavailable(self):
        now = datetime(2026, 8, 29, 12, 0, 0)
        with (
            patch("crm.api._ai_staleness.now_datetime", return_value=now),
            patch("crm.api._ai_staleness.ai_staleness_threshold_seconds", return_value=None),
        ):
            result = ai_field_or_unavailable(
                {"ai_summary": "fresh", "ai_generated_at": now},
                "ai_summary",
            )

        self.assertFalse(result["ai_available"])
        self.assertEqual(result["reason"], "invalid_staleness_threshold")

    def test_invalid_timestamp_does_not_reach_formatter(self):
        result = ai_field_or_unavailable(
            {"ai_summary": "fresh", "ai_generated_at": "not-a-timestamp"},
            "ai_summary",
        )

        self.assertFalse(result["ai_available"])
        self.assertEqual(result["reason"], "invalid_generated_at")
        self.assertIsNone(result["generated_at"])
