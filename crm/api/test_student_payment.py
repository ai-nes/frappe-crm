from unittest import TestCase
from unittest.mock import patch

import frappe

from crm.api.student_payment import record_event


class TestStudentPaymentApi(TestCase):
	def test_sales_profiles_cannot_record_payment_events(self):
		for role in ("Sale", "CTV Sale", "Lead Sale"):
			with self.subTest(role=role):
				with (
					patch.object(frappe.session, "user", f"{role.lower()}@example.com"),
					patch.object(frappe, "get_roles", return_value=[role]),
				):
					with self.assertRaises(frappe.PermissionError):
						record_event("PAYMENT-1", "Received", "2026-09-07 10:00:00", "REF-1")
