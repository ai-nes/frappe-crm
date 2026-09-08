"""Focused HTTP adapter tests for Lead processing commands."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import lead_processing


class TestLeadProcessingAPI(FrappeTestCase):
	def test_status_endpoint_forwards_requested_status(self):
		expected = {
			"status": "PROCESSING",
			"resolution": "PENDING",
			"lead": "LEAD-2026-00001",
		}
		with patch.object(lead_processing, "_update_processing_status", return_value=expected) as command:
			self.assertEqual(
				lead_processing.update_processing_status(
					"LEAD-2026-00001", "PROCESSING", "Đang xử lý thủ công"
				),
				expected,
			)

		command.assert_called_once_with(
			lead="LEAD-2026-00001",
			status="PROCESSING",
			reason="Đang xử lý thủ công",
		)
