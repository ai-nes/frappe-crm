"""Focused contract tests for the session-scoped worklist helpers."""

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import call, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.student_worklist import (
	_decode_cursor,
	_encode_cursor,
	_fetch_page,
	_parse_page_size,
	_serialize_nba,
	_sort_key,
	get_next_best_action_for_student,
)


@contextmanager
def _as_user(user):
	previous_user = getattr(getattr(frappe, "session", None), "user", "Guest")
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(previous_user)


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


class TestStudentNextBestAction(FrappeTestCase):
	def test_serializer_returns_contract_fields_and_server_derived_flags(self):
		now = datetime(2026, 9, 3, 10, 0, 0)
		row = frappe._dict(
			name="ACT-2026-00128",
			student="STU-2026-00042",
			action_type="CALL",
			objective="Resolve the student's Tuition need.",
			state="pending",
			execution_status="planned",
			priority="medium",
			due_at="2026-09-03 16:00:00",
			action_owner=None,
			origin="ai",
			action_revision=1,
			phone="must-not-be-exposed",
			email="must-not-be-exposed@example.com",
		)

		result = _serialize_nba(row, now=now)

		self.assertEqual(result["name"], "ACT-2026-00128")
		self.assertEqual(result["student"], "STU-2026-00042")
		self.assertEqual(result["due_at"], "2026-09-03 16:00:00")
		self.assertTrue(result["is_today"])
		self.assertFalse(result["is_overdue"])
		self.assertNotIn("phone", result)
		self.assertNotIn("email", result)

	def test_endpoint_selects_one_active_action_with_permission_scoped_reads(self):
		action = frappe._dict(
			name="ACT-2026-00128",
			student="STU-2026-00042",
			action_type="CALL",
			objective="Resolve the student's Tuition need.",
			state="pending",
			execution_status="planned",
			priority="medium",
			due_at=None,
			action_owner=None,
			origin="ai",
			action_revision=1,
		)
		calls = []

		def fake_get_list(doctype, **kwargs):
			calls.append((doctype, kwargs))
			return [{"name": "STU-2026-00042"}] if doctype == "CRM Student" else [action]

		with (
			_as_user("staff@example.com"),
			patch("frappe.has_permission") as has_permission,
			patch("frappe.get_list", side_effect=fake_get_list),
		):
			result = get_next_best_action_for_student(" STU-2026-00042 ")

		has_permission.assert_has_calls(
			[
				call("CRM Student", "read", user="staff@example.com", throw=True),
				call("CRM Action", "read", user="staff@example.com", throw=True),
			]
		)
		self.assertEqual(result["student_id"], "STU-2026-00042")
		self.assertEqual(result["nba"]["name"], "ACT-2026-00128")
		self.assertEqual(result["policy_version"], "worklist-v1")
		self.assertEqual(calls[1][1]["order_by"], "creation desc, modified desc")
		self.assertEqual(set(calls[1][1]["filters"]["state"][1]), {"completed", "cancelled", "rejected", "superseded"})
		self.assertEqual(calls[1][1]["limit_page_length"], 1)

	def test_endpoint_returns_null_when_student_has_no_active_action(self):
		def fake_get_list(doctype, **kwargs):
			return [{"name": "STU-2026-00042"}] if doctype == "CRM Student" else []

		with (
			_as_user("staff@example.com"),
			patch("frappe.has_permission"),
			patch("frappe.get_list", side_effect=fake_get_list),
		):
			result = get_next_best_action_for_student("STU-2026-00042")

		self.assertIsNone(result["nba"])

	def test_endpoint_hides_missing_or_out_of_scope_student_as_not_found(self):
		with (
			_as_user("staff@example.com"),
			patch("frappe.has_permission"),
			patch("frappe.get_list", return_value=[]),
		):
			with self.assertRaises(frappe.DoesNotExistError):
				get_next_best_action_for_student("STU-2026-00042")

	def test_endpoint_rejects_guest_and_invalid_student_id(self):
		with _as_user("Guest"):
			with self.assertRaises(frappe.AuthenticationError):
				get_next_best_action_for_student("STU-2026-00042")

		with _as_user("staff@example.com"):
			with self.assertRaises(frappe.ValidationError):
				get_next_best_action_for_student("   ")
			with self.assertRaises(frappe.ValidationError):
				get_next_best_action_for_student()

	def test_endpoint_translates_doctype_permission_failure_to_forbidden(self):
		with (
			_as_user("staff@example.com"),
			patch("frappe.has_permission", side_effect=frappe.PermissionError),
		):
			with self.assertRaises(frappe.PermissionError):
				get_next_best_action_for_student("STU-2026-00042")
