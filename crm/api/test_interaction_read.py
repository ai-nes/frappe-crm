import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.interaction_read import _decode_cursor, _encode_cursor


class TestInteractionReadHelpers(FrappeTestCase):
	def test_cursor_round_trip(self):
		cursor = _encode_cursor({"name": "INTX-001", "interaction_datetime": "2026-09-06 09:30:00"})
		self.assertEqual(_decode_cursor(cursor), ("2026-09-06T09:30:00+00:00", "INTX-001"))

	def test_invalid_cursor_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			_decode_cursor("not-a-cursor")
