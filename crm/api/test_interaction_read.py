import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.interaction_read import (
	_date_bound,
	_decode_cursor,
	_encode_cursor,
	_family_interaction_types,
	_query_text,
)


class TestInteractionReadHelpers(FrappeTestCase):
	def test_cursor_round_trip(self):
		cursor = _encode_cursor({"name": "INTX-001", "interaction_datetime": "2026-09-06 09:30:00"})
		self.assertEqual(_decode_cursor(cursor), ("2026-09-06T09:30:00+00:00", "INTX-001"))

	def test_invalid_cursor_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			_decode_cursor("not-a-cursor")

	def test_family_filter_resolves_semantic_purpose_to_interaction_types(self):
		self.assertIn("MESSAGE", _family_interaction_types("conversation"))
		self.assertIn("PHONE_CALL", _family_interaction_types("Conversation"))

	def test_date_only_end_filter_includes_the_full_day(self):
		bound, operator = _date_bound("2026-09-06", "to_date", end=True)
		self.assertEqual(str(bound), "2026-09-07 00:00:00")
		self.assertEqual(operator, "<")

	def test_search_text_is_trimmed_and_bounded(self):
		self.assertEqual(_query_text("  webchat inbound  ", "search"), "webchat inbound")
		with self.assertRaises(frappe.ValidationError):
			_query_text("x" * 141, "search")
