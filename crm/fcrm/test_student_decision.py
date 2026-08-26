"""Behavior tests for the V2-native decision command service (decide_student_task).

No test anywhere in this repo previously exercised decide_student_task or
decide_recommendation end-to-end -- this covers the accept/reject contract,
the CAS staleness fence, and the invariant that V2 decisions are audited only
via CRM Student Decision Event, never the legacy CRM Agent Event outbox.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from crm.fcrm.student_decision import StudentDecisionError, decide_student_task
from crm.fcrm.test_permissions import TestSharedScopingPermissions


class TestDecideStudentTask(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = TestSharedScopingPermissions._make_campus(self, "_Test Decision Campus")
		self._department = TestSharedScopingPermissions._get_or_create_department(
			self, "_Test Decision Dept", self._campus
		)
		self._sale_user, self._sale_staff = TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test Decision Sale", roles=["Sale"]
		)
		self._student = self._make_student("_Test Decision Student")

	def tearDown(self):
		frappe.set_user("Administrator")
		# CRM Student Decision Event is append-only (on_trash always throws) --
		# a raw delete is the only way to clean it up in a test.
		frappe.db.delete("CRM Student Decision Event", {"student": self._student.name})
		for name in frappe.db.get_all(
			"CRM Sales Action", filters={"student": self._student.name}, pluck="name"
		):
			frappe.delete_doc("CRM Sales Action", name, force=True)
		frappe.db.delete("CRM Student Command Receipt", {"target_student": self._student.name})
		for name in frappe.db.get_all(
			"CRM Student Task", filters={"student": self._student.name}, pluck="name"
		):
			frappe.delete_doc("CRM Student Task", name, force=True)
		frappe.delete_doc("CRM Student", self._student.name, force=True)
		frappe.delete_doc("CRM Staff", self._sale_staff, force=True)
		frappe.delete_doc("User", self._sale_user, force=True)
		frappe.delete_doc("CRM Department", self._department, force=True)
		frappe.delete_doc("CRM Campus", self._campus, force=True)

	def _make_student(self, name):
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc({"doctype": "CRM Student", "student_name": name, "phone": phone})
		previous_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_flag
		return student

	def _make_task(self, *, disposition="ACT", action_type="CALL"):
		task = frappe.get_doc(
			{
				"doctype": "CRM Student Task",
				"student": self._student.name,
				"source_context_revision": 1,
				"disposition": disposition,
				"action_type": action_type if disposition == "ACT" else None,
				"objective": "Follow up on application status.",
				"policy_version": "test-v1",
				"generation_idempotency_key": frappe.generate_hash(length=20),
				"producer_identity": "test-suite",
				"payload_digest": frappe.generate_hash(length=32),
			}
		)
		task.insert(ignore_permissions=True)
		return task

	def test_accept_creates_correlated_sales_action_and_decision_event(self):
		task = self._make_task()
		result = decide_student_task(
			task.name,
			expected_revision=0,
			status="accepted",
			idempotency_key=f"accept-{task.name}",
			due_at=now_datetime(),
			assignee_staff=self._sale_staff,
		)

		self.assertEqual(result["status"], "accepted")
		self.assertEqual(result["task"], task.name)
		self.assertTrue(result["sales_action"])

		task.reload()
		self.assertEqual(task.state, "ACCEPTED")
		self.assertEqual(task.decision_revision, 1)
		self.assertEqual(task.sales_action, result["sales_action"])

		action = frappe.get_doc("CRM Sales Action", result["sales_action"])
		self.assertEqual(action.student_task, task.name)
		self.assertEqual(action.action_type, "CALL")
		self.assertFalse(action.recommendation)

		event = frappe.get_doc("CRM Student Decision Event", result["event"])
		self.assertEqual(event.student_task, task.name)
		self.assertIsNone(event.recommendation)
		self.assertEqual(event.event_type, "task_decided")

	def test_accept_does_not_write_a_legacy_agent_event(self):
		task = self._make_task()
		before = set(frappe.db.get_all("CRM Agent Event", pluck="name"))

		decide_student_task(
			task.name,
			expected_revision=0,
			status="accepted",
			idempotency_key=f"accept-no-outbox-{task.name}",
			due_at=now_datetime(),
			assignee_staff=self._sale_staff,
		)

		after = set(frappe.db.get_all("CRM Agent Event", pluck="name"))
		self.assertEqual(after - before, set(), "V2 task decisions must never route through the legacy outbox")

	def test_stale_expected_revision_is_rejected(self):
		task = self._make_task()
		decide_student_task(
			task.name,
			expected_revision=0,
			status="accepted",
			idempotency_key=f"accept-first-{task.name}",
			due_at=now_datetime(),
			assignee_staff=self._sale_staff,
		)

		with self.assertRaises(StudentDecisionError) as ctx:
			decide_student_task(
				task.name,
				expected_revision=0,
				status="accepted",
				idempotency_key=f"accept-stale-{task.name}",
				due_at=now_datetime(),
				assignee_staff=self._sale_staff,
			)
		self.assertEqual(ctx.exception.code, "STALE_REVISION")

	def test_reject_requires_decision_reason(self):
		task = self._make_task()

		with self.assertRaises(StudentDecisionError) as ctx:
			decide_student_task(
				task.name,
				expected_revision=0,
				status="rejected",
				idempotency_key=f"reject-{task.name}",
			)
		self.assertEqual(ctx.exception.code, "INVALID_INPUT")

		result = decide_student_task(
			task.name,
			expected_revision=0,
			status="rejected",
			idempotency_key=f"reject-with-reason-{task.name}",
			decision_reason="Student is no longer reachable.",
		)
		self.assertEqual(result["status"], "rejected")
		task.reload()
		self.assertEqual(task.state, "REJECTED")

	def test_replaying_the_same_idempotency_key_returns_the_original_result(self):
		task = self._make_task()
		key = f"accept-replay-{task.name}"
		due_at = now_datetime()
		first = decide_student_task(
			task.name,
			expected_revision=0,
			status="accepted",
			idempotency_key=key,
			due_at=due_at,
			assignee_staff=self._sale_staff,
		)

		second = decide_student_task(
			task.name,
			expected_revision=0,
			status="accepted",
			idempotency_key=key,
			due_at=due_at,
			assignee_staff=self._sale_staff,
		)
		self.assertTrue(second["replayed"])
		self.assertEqual(second["task"], first["task"])
		self.assertEqual(second["sales_action"], first["sales_action"])
