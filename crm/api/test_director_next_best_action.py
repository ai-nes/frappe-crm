from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_next_best_action as api


class TestDirectorNextBestAction(FrappeTestCase):
	AS_OF = datetime(2026, 8, 31, 10, 0, tzinfo=api.LOCAL_TIMEZONE)

	def test_admissions_director_can_read_but_not_write_interactions(self):
		user = "_test_director_nba_interaction@example.com"
		previous_user = frappe.session.user

		def delete_test_user():
			active_user = frappe.session.user
			frappe.set_user("Administrator")
			try:
				if frappe.db.exists("User", user):
					frappe.delete_doc("User", user, force=True)
			finally:
				frappe.set_user(active_user)

		delete_test_user()
		self.addCleanup(delete_test_user)
		frappe.set_user("Administrator")
		frappe.get_doc(
			{
				"doctype": "User",
				"email": user,
				"first_name": "_Test Director NBA Interaction",
				"send_welcome_email": 0,
				"roles": [{"role": "Admissions Director"}],
			}
		).insert(ignore_permissions=True)
		frappe.clear_cache(user=user)

		frappe.set_user(user)
		try:
			self.assertTrue(frappe.has_permission("CRM Interaction", "read"))
			self.assertFalse(frappe.has_permission("CRM Interaction", "create"))
			self.assertFalse(frappe.has_permission("CRM Interaction", "write"))
			self.assertFalse(frappe.has_permission("CRM Interaction", "delete"))
			frappe.get_list("CRM Interaction", fields=["name"], limit_page_length=1)
		finally:
			frappe.set_user(previous_user)

	def test_queue_counts_use_all_visible_actions_and_exclude_stale_rows(self):
		students = [
			{"name": "STU-1", "student_name": "Mai Thi An", "high_school": "SCH-1", "major": "M-1"},
			{"name": "STU-2", "student_name": "Tran Minh Binh", "high_school": "SCH-1", "major": "M-1"},
			{"name": "STU-3", "student_name": "Le Gia Han", "high_school": "SCH-1", "major": "M-1"},
		]
		recommendations = [
			{
				"name": "REC-TODAY",
				"student": "STU-1",
				"status": "new",
				"priority": "high",
				"recommended_action": "CALL",
				"recommended_timing": "2026-08-31 17:00:00+07:00",
			},
			{
				"name": "REC-SOON",
				"student": "STU-2",
				"status": "new",
				"priority": "medium",
				"recommended_action": "FOLLOW_UP",
				"recommended_timing": "2026-09-02 09:00:00+07:00",
			},
			{
				"name": "REC-DEFERRED",
				"student": "STU-3",
				"status": "deferred",
				"revisit_at": "2026-09-02 09:00:00+07:00",
				"recommended_action": "CALL",
				"recommended_timing": "2026-08-31 09:00:00+07:00",
			},
			{
				"name": "REC-EXPIRED",
				"student": "STU-3",
				"status": "new",
				"expires_at": "2026-08-31 09:59:00+07:00",
				"recommended_action": "CALL",
			},
		]

		queue = api._build_queue(
			recommendations,
			[],
			students,
			{},
			[],
			{"schools": {}, "majors": {}, "owners": {}, "interaction_types": {}},
			self.AS_OF,
			queue_filter="all",
			page=1,
			page_size=1,
		)

		self.assertEqual(queue["counts"], {"all": 2, "urgent": 1, "today": 1, "overdue": 0, "soon": 1})
		self.assertEqual([row["id"] for row in queue["actions"]], ["REC-TODAY"])
		self.assertTrue(queue["pagination"]["hasNext"])

	def test_defer_until_requires_timezone_and_stays_within_policy_window(self):
		with self.assertRaises(frappe.ValidationError):
			api._parse_defer_until("2026-09-02T09:00:00", self.AS_OF)

		parsed = api._parse_defer_until("2026-09-02T09:00:00+07:00", self.AS_OF)
		self.assertEqual(parsed.isoformat(), "2026-09-02T09:00:00+07:00")

		with self.assertRaises(frappe.ValidationError):
			api._parse_defer_until("2026-10-01T09:00:00+07:00", self.AS_OF)

	def test_endpoint_returns_single_documented_snapshot_envelope(self):
		student = {"name": "STU-1", "student_name": "Mai Thi An"}
		recommendation = {
			"name": "REC-1",
			"student": "STU-1",
			"status": "new",
			"priority": "high",
			"recommended_action": "CALL",
			"recommended_timing": "2026-08-31 17:00:00+07:00",
			"created_at": "2026-08-31 08:00:00+07:00",
			"policy_version": "action-policy-2026.08",
		}
		with (
			patch.object(api, "require_director_access", return_value={"user": "director@example.com"}),
			patch.object(api, "_resolve_funnel_admission_year", return_value="2026"),
			patch.object(
				api,
				"_normalize_funnel_scope",
				return_value={"id": "all", "label": "Toàn bộ cơ sở", "branch": None, "territory": None},
			),
			patch.object(api, "_authorize_scope"),
			patch.object(api, "_now", return_value=self.AS_OF),
			patch.object(api, "_table_exists", return_value=True),
			patch.object(api, "_load_students", return_value=[student]),
			patch.object(api, "_load_recommendations", return_value=[recommendation]),
			patch.object(api, "_load_actions", return_value=[]),
			patch.object(
				api, "_load_latest_assessments", return_value={"STU-1": {"model_version": "nba-2026.08"}}
			),
			patch.object(api, "_load_interactions", return_value=[]),
			patch.object(api, "_load_sla_attempts", return_value=[]),
			patch.object(
				api,
				"_load_lookups",
				return_value={"schools": {}, "majors": {}, "owners": {}, "interaction_types": {}},
			),
		):
			response = api.get_director_next_best_action(admissionYear="2026")

		self.assertEqual(set(response), {"meta", "queue", "sla", "outcomes", "controlPolicy"})
		self.assertEqual(response["meta"]["admissionYear"], 2026)
		self.assertEqual(response["meta"]["asOf"], "2026-08-31T10:00:00+07:00")
		self.assertEqual(response["meta"]["modelVersion"], "nba-2026.08")
		self.assertEqual(response["queue"]["actions"][0]["id"], "REC-1")
		self.assertEqual(response["controlPolicy"]["version"], api.POLICY_VERSION)

	def test_assign_adapter_delegates_to_canonical_decision_command(self):
		recommendation = _Recommendation(
			name="REC-1",
			recommended_timing="2026-09-01 17:00:00+07:00",
			expires_at="2026-09-30 17:00:00+07:00",
		)
		result = {"revision": 4, "event": "EVT-1", "replayed": False}
		with (
			patch.object(api, "require_director_access", return_value={"user": "director@example.com"}),
			patch.object(api, "_get_visible_recommendation", return_value=recommendation),
			patch.object(api, "_resolve_idempotency_key", return_value="cmd-1"),
			patch.object(api, "_resolve_assignee_staff", return_value="STAFF-1"),
			patch.object(api, "_check_expired"),
			patch.object(api, "_event_timestamp", return_value=self.AS_OF),
			patch.object(api, "decide_recommendation", return_value=result) as command,
		):
			response = api.apply_action_command(
				actionId="REC-1",
				command="assign",
				assigneeId="STAFF-1",
				expectedVersion=3,
				idempotencyKey="cmd-1",
			)

		command.assert_called_once_with(
			name="REC-1",
			expected_revision=3,
			status="accepted",
			idempotency_key="cmd-1",
			correlation_id="director-nba:cmd-1",
			decision_reason=None,
			due_at=api._coerce_datetime("2026-09-01 17:00:00+07:00"),
			assignee_staff="STAFF-1",
			revisit_at=None,
		)
		self.assertEqual(response["state"], "assigned")
		self.assertEqual(response["version"], 4)
		self.assertEqual(response["audit"]["eventId"], "EVT-1")


class _Recommendation(dict):
	@property
	def name(self):
		return self["name"]
