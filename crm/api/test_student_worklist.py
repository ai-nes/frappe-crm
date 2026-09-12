"""Focused contract tests for the session-scoped worklist helpers."""

import json
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import call, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.student_worklist import (
	_decode_cursor,
	_encode_cursor,
	_fetch_recommendation_page,
	_parse_page_size,
	_recommendation_dto,
	_recommendation_sort_key,
	_serialize_nba,
	get_next_best_action_for_student,
	list_actions_for_record,
	list_student_worklist,
)
from crm.fcrm.test_permissions import TestSharedScopingPermissions


@contextmanager
def _as_user(user):
	previous_user = getattr(getattr(frappe, "session", None), "user", "Guest")
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(previous_user)


class TestStudentWorklist(FrappeTestCase):
	def test_sort_key_is_rank_then_timing_creation_and_id(self):
		"""`_recommendation_sort_key` must read `rank`/`recommended_at` -- the same
		columns the SQL ORDER BY/keyset predicate in `_fetch_recommendation_page`
		uses -- with matching defaults, or pagination desyncs across pages."""
		high = frappe._dict(rank=1, recommended_at=None, creation="2026-01-02", name="REC-2")
		medium = frappe._dict(rank=2, recommended_at="2025-01-01", creation="2026-01-01", name="REC-1")
		earlier = frappe._dict(rank=1, recommended_at="2026-01-01", creation="2026-01-03", name="REC-3")

		self.assertEqual(
			[row.name for row in sorted([high, medium, earlier], key=_recommendation_sort_key)],
			["REC-3", "REC-2", "REC-1"],
		)
		self.assertEqual(_recommendation_sort_key(high)[1], "9999-12-31 23:59:59.999999")

	def test_sort_key_defaults_missing_rank_to_the_sql_column_default(self):
		"""The SQL column's own default is 999 -- they must agree or a row missing
		its rank sorts inconsistently between the cursor and the next query."""
		row = frappe._dict(rank=None, recommended_at=None, creation="2026-01-01", name="REC-1")
		self.assertEqual(_recommendation_sort_key(row)[0], 999)

	def test_recommendation_dto_surfaces_ai_payload_verbatim_and_cas_field(self):
		row = frappe._dict(
			name="REC-1",
			student="STU-1",
			student_name="Nguyen Van A",
			rank=1,
			priority="high",
			channel="CALL",
			reason="Follow up on interest",
			action="ACT-CALL",
			recommendation_key="k1",
			ai_payload='{"action_ref": {"action_id": "ACT-CALL"}}',
			explanation='{"summary": "Student has been silent after asking about tuition."}',
			evaluation="NBAEVAL-1",
			recommended_at="2026-01-01 10:00:00",
			modified="2026-01-01 10:05:00",
			creation="2026-01-01 09:00:00",
		)

		dto = _recommendation_dto(row, {"NBAEVAL-1": {"disposition": "RECOMMEND", "status": "completed"}})

		self.assertEqual(dto["id"], "REC-1")
		self.assertEqual(dto["rank"], 1)
		self.assertEqual(dto["studentId"], "STU-1")
		self.assertEqual(dto["aiPayload"], {"action_ref": {"action_id": "ACT-CALL"}})
		self.assertEqual(dto["explanation"], {"summary": "Student has been silent after asking about tuition."})
		self.assertEqual(
			dto["evaluation"], {"id": "NBAEVAL-1", "disposition": "RECOMMEND", "status": "completed"}
		)
		self.assertEqual(dto["expected_revision"], "2026-01-01 10:05:00")
		self.assertIn("dismissed", dto["permitted_decisions"])

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
			self.assertEqual(_fetch_recommendation_page("Administrator", None, 1), [])

	def test_record_actions_are_filtered_by_canonical_student(self):
		action = frappe._dict(
			name="ACT-1",
			student="STU-1",
			action="CALL",
			action_type="CALL",
			objective="Call the student",
			state="pending",
			execution_status="planned",
			priority="medium",
			due_at=None,
			action_owner=None,
			origin="manual",
			action_revision=1,
		)
		with (
			_as_user("staff@example.com"),
			patch.object(frappe, "has_permission"),
			patch("crm.api.student_worklist.canonical_student", return_value="STU-1"),
			patch("crm.api.student_worklist._ensure_visible_student") as ensure_visible,
			patch("frappe.get_list", return_value=[action]) as get_list,
		):
			result = list_actions_for_record("CRM Student", "STU-1")

		ensure_visible.assert_called_once_with("STU-1")
		self.assertEqual(get_list.call_args.args[0], "CRM Action Item")
		self.assertEqual(get_list.call_args.kwargs["filters"], {"student": "STU-1"})
		self.assertEqual(result["items"][0]["student"], "STU-1")


class TestStudentWorklistRealNonSystemManagerSession(FrappeTestCase):
	"""``CRM NBA Evaluation`` grants doctype ``read`` to System Manager only, so
	a real Sale-role session has no permission on it at all. The worklist's
	evaluation-disposition enrichment must not turn that into a hard failure
	for a page that actually has data -- reproduced end-to-end against a real
	DB session and role, not mocked `frappe.db.sql`/`DatabaseQuery`."""

	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = TestSharedScopingPermissions._make_campus(self, "_Test Worklist Perm Campus")
		self._department = TestSharedScopingPermissions._get_or_create_department(
			self, "_Test Worklist Perm Dept", self._campus
		)
		self._sale_user, self._sale_staff = TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test Worklist Perm Sale", roles=["Sale"]
		)
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc(
			{"doctype": "CRM Student", "full_name": "_Test Worklist Perm Student", "phone": phone}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"CRM Student", student.name, "owner_staff", self._sale_staff, update_modified=False
		)
		self._student = student

		self._evaluation = frappe.get_doc(
			{
				"doctype": "CRM NBA Evaluation",
				"student": self._student.name,
				"trigger": "automatic",
				"status": "completed",
				"disposition": "RECOMMEND",
				"engine_revision": "nba-engine-test",
				"evaluation_key": frappe.generate_hash(length=64),
				"run_generation": 1,
			}
		).insert(ignore_permissions=True)

		self._recommendation = frappe.get_doc(
			{
				"doctype": "CRM Recommendation",
				"recommendation_id": "REC-" + frappe.generate_hash(length=18),
				"target_type": "CRM Student",
				"target_id": self._student.name,
				"action": "CALL",
				"reason": "Silent for nine days after a tuition question.",
				"priority": "high",
				"channel": "CALL",
				"recommended_at": frappe.utils.now_datetime(),
				"evaluation": self._evaluation.name,
				"recommendation_key": "k1",
				"rank": 1,
				"decision_status": "pending",
			}
		)
		self._recommendation.flags.ignore_links = True
		self._recommendation.insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("CRM Recommendation", self._recommendation.name, force=True)
		frappe.delete_doc("CRM NBA Evaluation", self._evaluation.name, force=True)
		frappe.delete_doc("CRM Staff", self._sale_staff, force=True)
		frappe.delete_doc("User", self._sale_user, force=True)
		frappe.delete_doc("CRM Student", self._student.name, force=True)
		frappe.delete_doc("CRM Department", self._department, force=True)
		frappe.delete_doc("CRM Campus", self._campus, force=True)

	def test_sale_session_lists_the_worklist_without_a_permission_error(self):
		with _as_user(self._sale_user):
			result = list_student_worklist()

		names = [item["id"] for item in result["items"]]
		self.assertIn(self._recommendation.name, names)
		row = next(item for item in result["items"] if item["id"] == self._recommendation.name)
		# The evaluation enrichment degrades safely rather than raising: the
		# Sale session has no doctype permission on `CRM NBA Evaluation` at
		# all, yet the disposition/status still project through.
		self.assertEqual(row["evaluation"]["disposition"], "RECOMMEND")
		self.assertEqual(row["evaluation"]["status"], "completed")

	def test_empty_page_for_a_visible_student_explains_why_without_rule_codes(self):
		"""No pending recommendation left for this Student, but the latest
		evaluation carries a rule-engine WAIT decision -- the empty page must
		surface that business reason in plain Vietnamese, and must never leak
		the raw `matched_rule_ids` codes into the response."""
		frappe.db.set_value(
			"CRM Recommendation", self._recommendation.name, "decision_status", "accepted", update_modified=False
		)
		wait_evaluation = frappe.get_doc(
			{
				"doctype": "CRM NBA Evaluation",
				"student": self._student.name,
				"trigger": "manual",
				"status": "completed",
				"disposition": "WAIT",
				"engine_revision": "nba-engine-test",
				"evaluation_key": frappe.generate_hash(length=64),
				"run_generation": 1,
				"rule_decision": json.dumps(
					{
						"business_reason": "He thong ap dung quy tac Already Enrolled.",
						"matched_rule_ids": ["STU-003"],
					}
				),
			}
		).insert(ignore_permissions=True)
		try:
			with _as_user(self._sale_user):
				result = list_student_worklist(student_id=self._student.name)
			self.assertEqual(result["items"], [])
			self.assertEqual(result["empty_reason"], "He thong ap dung quy tac Already Enrolled.")
			self.assertNotIn("STU-003", json.dumps(result))
		finally:
			frappe.delete_doc("CRM NBA Evaluation", wait_evaluation.name, force=True)

	def test_empty_page_for_a_student_never_evaluated_says_so(self):
		phone = "0" + "".join(str((int(c, 16) + 2) % 10) for c in frappe.generate_hash(length=9))
		never_evaluated = frappe.get_doc(
			{"doctype": "CRM Student", "full_name": "_Test Worklist Never Evaluated", "phone": phone}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"CRM Student", never_evaluated.name, "owner_staff", self._sale_staff, update_modified=False
		)
		try:
			with _as_user(self._sale_user):
				result = list_student_worklist(student_id=never_evaluated.name)
			self.assertEqual(result["items"], [])
			self.assertEqual(result["empty_reason"], "Học sinh này chưa được hệ thống AI đánh giá lần nào.")
		finally:
			frappe.delete_doc("CRM Student", never_evaluated.name, force=True)


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
				call("CRM Action Item", "read", user="staff@example.com", throw=True),
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
