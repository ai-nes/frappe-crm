"""Focused contract tests for the session-scoped worklist helpers."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.student_worklist import _decode_cursor, _encode_cursor, _fetch_page, _parse_page_size, _sort_key


class TestStudentWorklist(FrappeTestCase):
	def test_sort_key_is_priority_rank_then_timing_creation_and_id(self):
		"""`_sort_key` must read `worklist_priority_rank` -- the same column the
		SQL ORDER BY/keyset predicate in `_fetch_page` uses -- not recompute a
		rank from the raw `priority` string with its own default. A mismatched
		default previously desynced pagination (see `_sort_key`'s docstring)."""
		high = frappe._dict(worklist_priority_rank=0, revisit_at=None, creation="2026-01-02", name="REC-2")
		medium = frappe._dict(
			worklist_priority_rank=1, revisit_at="2025-01-01", creation="2026-01-01", name="REC-1"
		)
		earlier = frappe._dict(
			worklist_priority_rank=0, revisit_at="2026-01-01", creation="2026-01-03", name="REC-3"
		)

		self.assertEqual(
			[row.name for row in sorted([high, medium, earlier], key=_sort_key)], ["REC-3", "REC-2", "REC-1"]
		)
		self.assertEqual(_sort_key(high)[1], "9999-12-31 23:59:59.999999")

	def test_sort_key_defaults_missing_rank_to_the_sql_column_default(self):
		"""The SQL column's own default is 99 (see CRMStudentTask.validate), not
		some independently chosen sentinel -- they must agree or a row missing
		its rank sorts inconsistently between the cursor and the next query."""
		row = frappe._dict(worklist_priority_rank=None, revisit_at=None, creation="2026-01-01", name="REC-1")
		self.assertEqual(_sort_key(row)[0], 99)

	def test_cursor_is_bound_to_principal_and_roles(self):
		cursor = _encode_cursor((0, "2026-01-01", "2026-01-01", "REC-1"), "user@example.com", ["Sale"])

		self.assertEqual(
			_decode_cursor(cursor, "user@example.com", ["Sale"]), [0, "2026-01-01", "2026-01-01", "REC-1"]
		)
		self.assertRaises(frappe.PermissionError, _decode_cursor, cursor, "other@example.com", ["Sale"])

	def test_cursor_rejects_tampering_and_page_limits(self):
		cursor = _encode_cursor((0, "2026-01-01", "2026-01-01", "REC-1"), "user@example.com", ["Sale"])
		tampered = f"{cursor[:-1]}{'A' if cursor[-1] != 'A' else 'B'}"

		self.assertRaises(frappe.PermissionError, _decode_cursor, tampered, "user@example.com", ["Sale"])
		self.assertEqual(_parse_page_size("50"), 50)
		self.assertRaises(frappe.ValidationError, _parse_page_size, 51)

	def test_first_page_does_not_unpack_a_missing_cursor(self):
		with (
			patch("frappe.has_permission"),
			patch("frappe.model.db_query.DatabaseQuery") as query,
			patch("frappe.db.sql", return_value=[]),
		):
			query.return_value.build_match_conditions.return_value = None
			self.assertEqual(_fetch_page("Administrator", None, 1), [])
