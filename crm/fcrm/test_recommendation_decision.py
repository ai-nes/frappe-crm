"""Behaviour tests for the append-only Sales Decision command on a Recommendation.

Covers the accepting-only Task creation rule, the parameter-delta allowlist and
its identity-change rejection, the one-Task-per-Recommendation boundary, the
distinction between an explicit DISMISS and passive expiry, idempotent replay,
and fail-closed authorization.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from crm.api.task import get_task, list_sales_tasks
from crm.fcrm.student_decision import StudentDecisionError, create_manual_action, decide_recommendation
from crm.fcrm.test_permissions import TestSharedScopingPermissions


class TestRecommendationDecision(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = TestSharedScopingPermissions._make_campus(self, "_Test RecDecision Campus")
		self._department = TestSharedScopingPermissions._get_or_create_department(
			self, "_Test RecDecision Dept", self._campus
		)
		self._sale_user, self._sale_staff = TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test RecDecision Sale", roles=["Sale"]
		)
		self._student = self._make_student("_Test RecDecision Student")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Student Decision Event", {"student": self._student.name})
		for name in frappe.db.get_all(
			"CRM Action Item", filters={"student": self._student.name}, pluck="name"
		):
			frappe.delete_doc("CRM Action Item", name, force=True)
		for name in frappe.db.get_all(
			"CRM Recommendation", filters={"target_id": self._student.name}, pluck="name"
		):
			frappe.delete_doc("CRM Recommendation", name, force=True)
		for name in frappe.db.get_all(
			"CRM NBA Evaluation", filters={"student": self._student.name}, pluck="name"
		):
			frappe.delete_doc("CRM NBA Evaluation", name, force=True)
		frappe.db.delete("CRM Student Command Receipt", {"target_student": self._student.name})
		frappe.delete_doc("CRM Student", self._student.name, force=True)
		frappe.delete_doc("CRM Staff", self._sale_staff, force=True)
		frappe.delete_doc("User", self._sale_user, force=True)
		frappe.delete_doc("CRM Department", self._department, force=True)
		frappe.delete_doc("CRM Campus", self._campus, force=True)

	def _make_student(self, name):
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc({"doctype": "CRM Student", "student_name": name, "phone": phone})
		previous = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous
		frappe.db.set_value(
			"CRM Student", student.name, "owner_staff", self._sale_staff, update_modified=False
		)
		return student

	def _make_evaluation(self):
		doc = frappe.get_doc(
			{
				"doctype": "CRM NBA Evaluation",
				"student": self._student.name,
				"trigger": "manual",
				"status": "queued",
				"engine_revision": "nba-engine-test",
				"evaluation_key": frappe.generate_hash(length=64),
			}
		).insert(ignore_permissions=True)
		return doc.name

	def _make_recommendation(self, *, action="CALL", expires_at=None, evaluation=None, rank=None):
		rec = frappe.get_doc(
			{
				"doctype": "CRM Recommendation",
				"recommendation_id": "REC-" + frappe.generate_hash(length=18),
				"target_type": "CRM Student",
				"target_id": self._student.name,
				"action": action,
				"purpose": "Call the family about the offer.",
				"reason": "Silent for nine days after a tuition question.",
				"priority": "high",
				"channel": "CALL",
				"recommended_at": now_datetime(),
				"expires_at": expires_at,
				"owner": self._sale_staff,
				"lifecycle_status": "proposed",
				"decision_status": "pending",
				"evaluation": evaluation,
				"rank": rank,
			}
		)
		rec.flags.ignore_links = True
		rec.insert(ignore_permissions=True)
		# ``owner`` is a custom field shadowing the framework owner column, so the
		# insert stamps the session user over it -- set the executor link directly.
		frappe.db.set_value("CRM Recommendation", rec.name, "owner", self._sale_staff, update_modified=False)
		rec.reload()
		return rec

	def _events(self, recommendation):
		return frappe.get_all(
			"CRM Student Decision Event",
			filters={"recommendation": recommendation},
			fields=["name", "decision_operation", "event_type", "manual_override", "action"],
		)

	def _tasks(self, recommendation):
		return frappe.get_all("CRM Action Item", filters={"recommendation": recommendation}, pluck="name")

	def test_accept_creates_one_event_and_one_task(self):
		rec = self._make_recommendation()
		result = decide_recommendation(
			rec.name,
			expected_revision=0,
			operation="ACCEPT",
			idempotency_key=f"acc-{rec.name}",
		)
		self.assertEqual(result["operation"], "ACCEPT")
		self.assertEqual(len(self._events(rec.name)), 1)
		tasks = self._tasks(rec.name)
		self.assertEqual(len(tasks), 1)
		task = frappe.get_doc("CRM Action Item", tasks[0])
		self.assertEqual(task.state, "accepted")
		self.assertEqual(task.objective, "Gọi điện")
		self.assertEqual(task.description, rec.reason)
		task_dto = get_task(result["action"])
		self.assertEqual(task_dto["title"], "Gọi điện")
		self.assertEqual(task_dto["description"], rec.reason)
		task_row = next(
			row for row in list_sales_tasks(page_length=100)["tasks"] if row["name"] == result["action"]
		)
		self.assertEqual(task_row["title"], "Gọi điện")
		self.assertEqual(task_row["description"], rec.reason)
		self.assertEqual(task.source_decision_event, result["event"])
		self.assertEqual(
			task.action_definition_digest, frappe.db.get_value("CRM Action", "CALL", "definition_digest")
		)
		rec.reload()
		self.assertEqual(rec.decision_status, "accepted")
		self.assertEqual(rec.decision_operation, "ACCEPT")
		self.assertEqual(rec.linked_task, tasks[0])
		self.assertEqual(rec.source_decision_event, result["event"])

	def test_non_parent_lead_action_can_be_accepted_without_a_contact(self):
		rec = self._make_recommendation(action="CALL")
		with patch("crm.fcrm.student_contact_conversion.contact_for_student", return_value=None):
			result = decide_recommendation(
				rec.name,
				expected_revision=0,
				operation="ACCEPT",
				idempotency_key=f"lead-no-contact-{rec.name}",
			)

		task = frappe.get_doc("CRM Action Item", result["action"])
		self.assertEqual(task.student, self._student.name)
		self.assertFalse(task.contact)

	def test_accept_with_changes_uses_human_values_and_leaves_recommendation_action_unchanged(self):
		rec = self._make_recommendation()
		human_due = add_to_date(now_datetime(), days=2)
		result = decide_recommendation(
			rec.name,
			expected_revision=0,
			operation="ACCEPT_WITH_CHANGES",
			delta={"due_at": human_due, "priority": "medium"},
			idempotency_key=f"awc-{rec.name}",
		)
		task = frappe.get_doc("CRM Action Item", result["action"])
		self.assertEqual(str(task.due_at), str(human_due))
		self.assertEqual(task.priority, "medium")
		rec.reload()
		self.assertEqual(rec.action, "CALL")
		self.assertEqual(rec.decision_operation, "ACCEPT_WITH_CHANGES")
		event = frappe.get_doc("CRM Student Decision Event", result["event"])
		self.assertEqual(event.decision_operation, "ACCEPT_WITH_CHANGES")

	def test_identity_change_in_delta_is_rejected(self):
		rec = self._make_recommendation()
		with self.assertRaises(StudentDecisionError) as ctx:
			decide_recommendation(
				rec.name,
				expected_revision=0,
				operation="ACCEPT_WITH_CHANGES",
				delta={"action": "EMAIL"},
				idempotency_key=f"idc-{rec.name}",
			)
		self.assertEqual(ctx.exception.code, "IDENTITY_CHANGE")
		self.assertEqual(self._tasks(rec.name), [])

	def test_accept_with_changes_requires_a_delta(self):
		rec = self._make_recommendation()
		with self.assertRaises(StudentDecisionError) as ctx:
			decide_recommendation(
				rec.name,
				expected_revision=0,
				operation="ACCEPT_WITH_CHANGES",
				idempotency_key=f"awc-empty-{rec.name}",
			)
		self.assertEqual(ctx.exception.code, "INVALID_INPUT")

	def test_reject_defer_dismiss_create_no_task(self):
		for operation, kwargs in (
			("REJECT", {"decision_reason": "Family asked us to stop."}),
			("DEFER", {"revisit_at": add_to_date(now_datetime(), days=5)}),
			("DISMISS", {"decision_reason": "Not relevant to this student."}),
		):
			rec = self._make_recommendation()
			result = decide_recommendation(
				rec.name,
				expected_revision=0,
				operation=operation,
				idempotency_key=f"{operation}-{rec.name}",
				**kwargs,
			)
			self.assertIsNone(result["action"], operation)
			self.assertEqual(self._tasks(rec.name), [], operation)
			self.assertEqual(len(self._events(rec.name)), 1, operation)
			rec.reload()
			self.assertEqual(rec.decision_operation, operation)

	def test_dismiss_writes_an_event_but_passive_expiry_does_not(self):
		dismissed = self._make_recommendation()
		decide_recommendation(
			dismissed.name,
			expected_revision=0,
			operation="DISMISS",
			decision_reason="Superseded by a walk-in.",
			idempotency_key=f"dis-{dismissed.name}",
		)
		self.assertEqual(len(self._events(dismissed.name)), 1)
		dismissed.reload()
		self.assertEqual(dismissed.decision_status, "dismissed")

		expired = self._make_recommendation(expires_at=add_to_date(now_datetime(), days=-1))
		with self.assertRaises(StudentDecisionError) as ctx:
			decide_recommendation(
				expired.name,
				expected_revision=0,
				operation="ACCEPT",
				idempotency_key=f"exp-{expired.name}",
			)
		self.assertEqual(ctx.exception.code, "ACTION_EXPIRED")
		self.assertEqual(self._events(expired.name), [])

	def test_second_task_for_one_recommendation_is_blocked_by_the_unique_boundary(self):
		rec = self._make_recommendation()
		decide_recommendation(
			rec.name,
			expected_revision=0,
			operation="ACCEPT",
			idempotency_key=f"first-{rec.name}",
		)
		with self.assertRaises(Exception):
			frappe.get_doc(
				{
					"doctype": "CRM Action Item",
					"recommendation": rec.name,
					"student": self._student.name,
					"current_slot": "CURRENT",
					"origin": "ai",
					"source_context_revision": 0,
					"disposition": "MONITOR",
					"objective": "duplicate",
					"policy_context_version": "x",
					"generation_idempotency_key": frappe.generate_hash(length=20),
					"producer_identity": "test",
					"payload_digest": frappe.generate_hash(length=32),
				}
			).insert(ignore_permissions=True)

	def test_stale_expected_modified_is_rejected(self):
		rec = self._make_recommendation()
		with self.assertRaises(StudentDecisionError) as ctx:
			decide_recommendation(
				rec.name,
				expected_revision=0,
				operation="ACCEPT",
				idempotency_key=f"stale-{rec.name}",
				expected_modified="2000-01-01 00:00:00",
			)
		self.assertEqual(ctx.exception.code, "STALE_REVISION")

	def test_stale_expected_revision_is_rejected_when_expected_modified_is_absent(self):
		"""The frontend sends only `expected_revision` (= `str(row.modified)` from
		the worklist DTO), never `expected_modified` -- the CAS guard must fall
		back to it or a stale Accept is never rejected through the real call
		path."""
		rec = self._make_recommendation()
		with self.assertRaises(StudentDecisionError) as ctx:
			decide_recommendation(
				rec.name,
				expected_revision="2000-01-01 00:00:00.000000",
				operation="ACCEPT",
				idempotency_key=f"stale-revision-{rec.name}",
			)
		self.assertEqual(ctx.exception.code, "STALE_REVISION")

	def test_current_expected_revision_alone_is_accepted(self):
		"""The live `str(doc.modified)` value, sent as `expected_revision` with no
		`expected_modified`, must pass the CAS guard -- the fallback is a real
		comparison, not a bypass."""
		rec = self._make_recommendation()
		result = decide_recommendation(
			rec.name,
			expected_revision=str(rec.modified),
			operation="ACCEPT",
			idempotency_key=f"fresh-revision-{rec.name}",
		)
		self.assertEqual(result["operation"], "ACCEPT")

	def test_same_idempotency_key_and_payload_replays_the_same_task(self):
		rec = self._make_recommendation()
		key = f"replay-{rec.name}"
		first = decide_recommendation(rec.name, expected_revision=0, operation="ACCEPT", idempotency_key=key)
		second = decide_recommendation(rec.name, expected_revision=0, operation="ACCEPT", idempotency_key=key)
		self.assertTrue(second.get("replayed"))
		self.assertEqual(first["action"], second["action"])
		self.assertEqual(len(self._tasks(rec.name)), 1)

	def test_same_key_different_payload_conflicts(self):
		rec = self._make_recommendation()
		key = f"conflict-{rec.name}"
		decide_recommendation(rec.name, expected_revision=0, operation="ACCEPT", idempotency_key=key)
		with self.assertRaises(StudentDecisionError) as ctx:
			decide_recommendation(
				rec.name,
				expected_revision=0,
				operation="REJECT",
				decision_reason="changed my mind",
				idempotency_key=key,
			)
		self.assertEqual(ctx.exception.code, "IDEMPOTENCY_KEY_REUSED")

	def test_unauthorized_actor_fails_closed(self):
		rec = self._make_recommendation()
		outsider, _ = TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test RecDecision Outsider", roles=["Marketing"]
		)
		frappe.set_user(outsider)
		try:
			with self.assertRaises(StudentDecisionError) as ctx:
				decide_recommendation(
					rec.name,
					expected_revision=0,
					operation="ACCEPT",
					idempotency_key=f"nope-{rec.name}",
				)
			self.assertIn(ctx.exception.code, {"FORBIDDEN", "OUT_OF_SCOPE"})
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("User", outsider, force=True)
		self.assertEqual(self._tasks(rec.name), [])

	def test_manual_task_with_a_different_action_records_override_telemetry(self):
		rec = self._make_recommendation(action="CALL")
		create_manual_action(
			student=self._student.name,
			action_type="EMAIL",
			objective="Send the family the corrected fee schedule.",
			idempotency_key=f"manual-{rec.name}",
			assignee_staff=self._sale_staff,
		)
		overrides = [e for e in self._events(rec.name) if e["manual_override"]]
		self.assertEqual(len(overrides), 1)
		self.assertFalse(overrides[0]["decision_operation"])
		rec.reload()
		self.assertEqual(rec.decision_status, "pending")

	def test_accepting_one_recommendation_dismisses_its_pending_evaluation_siblings(self):
		evaluation = self._make_evaluation()
		picked = self._make_recommendation(evaluation=evaluation, rank=1)
		sibling_a = self._make_recommendation(evaluation=evaluation, rank=2)
		sibling_b = self._make_recommendation(evaluation=evaluation, rank=3)
		independent = self._make_recommendation(evaluation=None, rank=None)

		decide_recommendation(
			picked.name,
			expected_revision=0,
			operation="ACCEPT",
			idempotency_key=f"pick-{picked.name}",
		)

		picked.reload()
		sibling_a.reload()
		sibling_b.reload()
		independent.reload()
		self.assertEqual(picked.decision_status, "accepted")
		self.assertEqual(sibling_a.decision_status, "dismissed_by_selection")
		self.assertEqual(sibling_a.lifecycle_status, "superseded")
		self.assertEqual(sibling_b.decision_status, "dismissed_by_selection")
		self.assertEqual(sibling_b.lifecycle_status, "superseded")
		# A recommendation with no evaluation link (or from a different
		# evaluation) is not a sibling and stays untouched.
		self.assertEqual(independent.decision_status, "pending")

		dismissed_events = [
			e for e in self._events(sibling_a.name) if e["event_type"] == "recommendation_decided"
		]
		self.assertEqual(len(dismissed_events), 1)

	def test_dismissed_siblings_can_no_longer_be_decided(self):
		evaluation = self._make_evaluation()
		picked = self._make_recommendation(evaluation=evaluation, rank=1)
		sibling = self._make_recommendation(evaluation=evaluation, rank=2)

		decide_recommendation(
			picked.name,
			expected_revision=0,
			operation="ACCEPT",
			idempotency_key=f"pick-{picked.name}",
		)

		with self.assertRaises(StudentDecisionError) as ctx:
			decide_recommendation(
				sibling.name,
				expected_revision=0,
				operation="ACCEPT",
				idempotency_key=f"late-{sibling.name}",
			)
		self.assertEqual(ctx.exception.code, "INVALID_STATE")
