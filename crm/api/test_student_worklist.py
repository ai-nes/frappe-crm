"""Focused contract tests for the session-scoped worklist helpers."""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.student_worklist import _decode_cursor, _encode_cursor, _parse_page_size, _sort_key


class TestStudentWorklist(FrappeTestCase):
	def test_sort_key_is_priority_then_timing_creation_and_id(self):
		high = frappe._dict(priority="high", recommended_timing=None, creation="2026-01-02", name="REC-2")
		medium = frappe._dict(priority="medium", recommended_timing="2025-01-01", creation="2026-01-01", name="REC-1")
		earlier = frappe._dict(priority="high", recommended_timing="2026-01-01", creation="2026-01-03", name="REC-3")

		self.assertEqual([row.name for row in sorted([high, medium, earlier], key=_sort_key)], ["REC-3", "REC-2", "REC-1"])
		self.assertEqual(_sort_key(high)[1], "9999-12-31 23:59:59.999999")

	def test_cursor_is_bound_to_principal_and_roles(self):
		cursor = _encode_cursor((0, "2026-01-01", "2026-01-01", "REC-1"), "user@example.com", ["Sale"])

		self.assertEqual(_decode_cursor(cursor, "user@example.com", ["Sale"]), [0, "2026-01-01", "2026-01-01", "REC-1"])
		self.assertRaises(frappe.PermissionError, _decode_cursor, cursor, "other@example.com", ["Sale"])

	def test_cursor_rejects_tampering_and_page_limits(self):
		cursor = _encode_cursor((0, "2026-01-01", "2026-01-01", "REC-1"), "user@example.com", ["Sale"])
		tampered = f"{cursor[:-1]}{'A' if cursor[-1] != 'A' else 'B'}"

		self.assertRaises(frappe.PermissionError, _decode_cursor, tampered, "user@example.com", ["Sale"])
		self.assertEqual(_parse_page_size("50"), 50)
		self.assertRaises(frappe.ValidationError, _parse_page_size, 51)
