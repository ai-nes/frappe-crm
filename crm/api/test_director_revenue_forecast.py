from datetime import date
from zoneinfo import ZoneInfo

from frappe.tests.utils import FrappeTestCase

from crm.api import director_revenue_forecast


class TestDirectorRevenueForecast(FrappeTestCase):
	def test_response_keeps_finance_totals_and_no_transaction_pii(self):
		response = director_revenue_forecast._build_response(
			"2026",
			"admission-year",
			{"id": "all", "label": "Toàn hệ thống", "campus": None},
			date(2026, 1, 1),
			date(2026, 12, 31),
			ZoneInfo("Asia/Ho_Chi_Minh"),
			[
				{
					"student": "STU-1",
					"gross_amount": 100,
					"award_amount": 10,
					"recognized_amount": 90,
					"recognition_period": "2026-06-15",
				}
			],
			[
				{
					"name": "PAY-1",
					"student": "STU-1",
					"amount": 90,
					"status": "Received",
					"received_at": "2026-06-15 10:00:00",
					"business_period": "2026-06-15",
				}
			],
			{"revenue": 120, "enrollment": 2},
			10,
			[],
		)

		self.assertEqual(response["summary"]["actualRevenue"], 90.0)
		self.assertEqual(response["model"]["netRevenue"], 90.0)
		self.assertEqual(response["summary"]["revenueGap"], 30.0)
		self.assertEqual(response["transactions"][0]["title"], "Khoản thu tuyển sinh")
		self.assertNotIn("student", response["transactions"][0])

	def test_invalid_limit_and_date_range_are_rejected(self):
		with self.assertRaises(Exception):
			director_revenue_forecast._parse_limit(51)
		with self.assertRaises(Exception):
			director_revenue_forecast._resolve_range(
				"2026", "admission-year", "2026-02-01", "2026-01-01", ZoneInfo("Asia/Ho_Chi_Minh")
			)
