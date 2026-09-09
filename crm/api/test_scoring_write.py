# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Tests for the compare-and-swap score write command and
score_input_revision tracking."""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.scoring_write import append_score_if_current
from crm.services.score_revision import bump_score_input_revision


class TestScoringWrite(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._previous_conf = frappe.conf.get("crm_agents_service_user")
		frappe.conf.crm_agents_service_user = "Administrator"

	def tearDown(self):
		if self._previous_conf is None:
			frappe.conf.pop("crm_agents_service_user", None)
		else:
			frappe.conf.crm_agents_service_user = self._previous_conf
		self._delete_test_students()
		for name in frappe.db.get_all(
			"CRM Score Template", filters={"template_name": ["like", "_Test SW%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Score Template", name, force=True)

	def _delete_test_students(self):
		for student in frappe.db.get_all(
			"CRM Student", filters={"full_name": ["like", "_Test SW%"]}, pluck="name"
		):
			for history in frappe.db.get_all("CRM Score History", filters={"student": student}, pluck="name"):
				frappe.delete_doc("CRM Score History", history, force=True)
			frappe.delete_doc("CRM Student", student, force=True)

	def _make_student(self, name="_Test SW Student"):
		for student in frappe.db.get_all("CRM Student", filters={"full_name": name}, pluck="name"):
			for history in frappe.db.get_all("CRM Score History", filters={"student": student}, pluck="name"):
				frappe.delete_doc("CRM Score History", history, force=True)
			frappe.delete_doc("CRM Student", student, force=True)
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": name,
				"phone": "0981100001",
				"email": f"{name.lower().replace(' ', '.')}@example.com",
				"student_stage": "Qualified",
			}
		)
		student.insert(ignore_permissions=True)
		return student

	def _make_template(self, name="_Test SW Template"):
		doc = frappe.get_doc({"doctype": "CRM Score Template", "template_name": name, "status": "Inactive"})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _payload(self, student, template, **overrides):
		payload = {
			"student": student,
			"source_score_input_revision": 1,
			"policy_revision": 1,
			"policy_hash": "deadbeef",
			"score_template": template,
			"scoring_time": frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
			"fit_score": 50.0,
			"engagement_score": 30.0,
			"intent_score": 60.0,
			"time_decay_score": 1.0,
			"negative_score": 0.0,
			"final_score": 55.0,
			"score_change": 5.0,
			"details": [],
		}
		payload.update(overrides)
		return payload

	def test_first_write_applies_and_updates_student(self):
		student = self._make_student()
		template = self._make_template()
		source_revision = frappe.db.get_value("CRM Student", student.name, "score_input_revision")

		result = append_score_if_current(
			**self._payload(student.name, template, source_score_input_revision=source_revision)
		)

		self.assertTrue(result["applied"])
		self.assertFalse(result["stale"])
		self.assertFalse(result["duplicate"])
		student.reload()
		self.assertEqual(student.latest_score, 55.0)
		self.assertEqual(student.applied_score_input_revision, source_revision)
		self.assertEqual(student.applied_policy_revision, 1)

	def test_duplicate_tuple_returns_existing_history_without_new_write(self):
		student = self._make_student("_Test SW Student Dup")
		template = self._make_template("_Test SW Template Dup")
		payload = self._payload(student.name, template)

		first = append_score_if_current(**payload)
		second = append_score_if_current(**payload)

		self.assertTrue(second["duplicate"])
		self.assertEqual(second["history"], first["history"])
		self.assertEqual(frappe.db.count("CRM Score History", {"student": student.name}), 1)

	def test_stale_tuple_is_rejected_without_overwriting_current_score(self):
		student = self._make_student("_Test SW Student Stale")
		template = self._make_template("_Test SW Template Stale")

		append_score_if_current(
			**self._payload(student.name, template, source_score_input_revision=5, final_score=70.0)
		)
		stale_result = append_score_if_current(
			**self._payload(student.name, template, source_score_input_revision=3, final_score=10.0)
		)

		self.assertTrue(stale_result["stale"])
		self.assertEqual(stale_result["current_revision"], 5)
		self.assertEqual(stale_result["current_policy_revision"], 1)
		student.reload()
		self.assertEqual(student.latest_score, 70.0)
		self.assertEqual(student.applied_score_input_revision, 5)

	def test_higher_policy_revision_at_same_input_revision_is_accepted(self):
		student = self._make_student("_Test SW Student Policy")
		template = self._make_template("_Test SW Template Policy")

		append_score_if_current(
			**self._payload(
				student.name, template, source_score_input_revision=2, policy_revision=1, final_score=40.0
			)
		)
		result = append_score_if_current(
			**self._payload(
				student.name, template, source_score_input_revision=2, policy_revision=2, final_score=45.0
			)
		)

		self.assertTrue(result["applied"])
		student.reload()
		self.assertEqual(student.latest_score, 45.0)
		self.assertEqual(student.applied_policy_revision, 2)

	def test_bump_score_input_revision_is_monotonic_per_student(self):
		student = self._make_student("_Test SW Student Bump")
		# Student insert already bumped score_input_revision once (on_update
		# always bumps for a new row) -- explicit bumps continue from there.
		baseline = frappe.db.get_value("CRM Student", student.name, "score_input_revision")

		first = bump_score_input_revision(student.name, "test_reason", enqueue=False)
		second = bump_score_input_revision(student.name, "test_reason", enqueue=False)

		self.assertEqual(first["revision"], baseline + 1)
		self.assertEqual(second["revision"], baseline + 2)
