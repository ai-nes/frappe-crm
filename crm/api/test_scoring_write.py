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
		if not frappe.db.has_column("CRM Student", "applied_score_template"):
			self.skipTest("CRM Student.applied_score_template requires bench migrate")
		self._previous_conf = frappe.conf.get("crm_agents_service_user")
		frappe.conf.crm_agents_service_user = "Administrator"
		self._previous_active_templates = frappe.db.get_all(
			"CRM Score Template", filters={"status": "Active"}, pluck="name"
		)
		for name in self._previous_active_templates:
			frappe.db.set_value("CRM Score Template", name, "status", "Inactive", update_modified=False)

	def tearDown(self):
		if self._previous_conf is None:
			frappe.conf.pop("crm_agents_service_user", None)
		else:
			frappe.conf.crm_agents_service_user = self._previous_conf
		for name in getattr(self, "_previous_active_templates", []):
			if frappe.db.exists("CRM Score Template", name):
				frappe.db.set_value("CRM Score Template", name, "status", "Active", update_modified=False)
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
				"enrollment_status": "CONFIRMED",
			}
		)
		student.insert(ignore_permissions=True)
		return student

	def _make_template(self, name="_Test SW Template"):
		doc = frappe.get_doc({"doctype": "CRM Score Template", "template_name": name, "status": "Inactive"})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_active_template(self, name="_Test SW Active Template"):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Score Template",
				"template_name": name,
				"status": "Active",
				"fit_weight": 0.4,
				"engagement_weight": 0.3,
				"intent_weight": 0.3,
			}
		)
		doc.insert(ignore_permissions=True)
		doc.reload()
		return doc

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

	def test_components_are_recomputed_and_response_echoes_authoritative_values(self):
		student = self._make_student("_Test SW Student Components")
		template = self._make_active_template("_Test SW Active Components")
		result = append_score_if_current(
			**self._payload(
				student.name,
				template.name,
				policy_revision=template.policy_revision,
				policy_hash=template.policy_hash,
				components={
					"fit": 50,
					"engagement": 30,
					"intent": 60,
					"negative": {"score": 0, "contributors": []},
				},
				expected_final_score=47,
				expected_time_decay_factor=1,
				expected_days_since=9999,
			)
		)
		self.assertTrue(result["applied"])
		self.assertEqual(result["final_score"], 47)
		self.assertEqual(result["score_change"], 47)
		self.assertEqual(result["time_decay_score"], 1)
		student.reload()
		self.assertEqual(student.latest_score, 47)
		self.assertEqual(student.applied_score_template, template.name)

	def test_component_validation_rejects_nan_and_positive_negative(self):
		student = self._make_student("_Test SW Student Validation")
		template = self._make_active_template("_Test SW Active Validation")
		base = self._payload(
			student.name,
			template.name,
			policy_revision=template.policy_revision,
			policy_hash=template.policy_hash,
			components={
				"fit": 50,
				"engagement": 30,
				"intent": 60,
				"negative": {"score": 0, "contributors": []},
			},
		)
		with self.assertRaises(frappe.ValidationError):
			append_score_if_current(**{**base, "components": {**base["components"], "fit": float("nan")}})
		with self.assertRaises(frappe.ValidationError):
			append_score_if_current(
				**{
					**base,
					"components": {**base["components"], "negative": {"score": 5, "contributors": []}},
				}
			)
		self.assertEqual(frappe.db.count("CRM Score History", {"student": student.name}), 0)

	def test_template_switch_rebaselines_even_when_tuple_is_not_newer(self):
		student = self._make_student("_Test SW Student Template Switch")
		first = self._make_active_template("_Test SW Active First")
		first_payload = self._payload(
			student.name,
			first.name,
			policy_revision=first.policy_revision,
			policy_hash=first.policy_hash,
			components={
				"fit": 10,
				"engagement": 10,
				"intent": 10,
				"negative": {"score": 0, "contributors": []},
			},
		)
		append_score_if_current(**first_payload)
		first.status = "Inactive"
		first.save(ignore_permissions=True)
		second = self._make_active_template("_Test SW Active Second")
		result = append_score_if_current(
			**self._payload(
				student.name,
				second.name,
				policy_revision=second.policy_revision,
				policy_hash=second.policy_hash,
				components={
					"fit": 90,
					"engagement": 90,
					"intent": 90,
					"negative": {"score": 0, "contributors": []},
				},
				source_score_input_revision=1,
			)
		)
		self.assertTrue(result["applied"])
		student.reload()
		self.assertEqual(student.applied_score_template, second.name)
		late_old_job = append_score_if_current(**first_payload)
		self.assertTrue(late_old_job["failed"])
		student.reload()
		self.assertEqual(student.applied_score_template, second.name)

	def test_null_template_stamp_rebaselines_an_old_tuple_after_migration(self):
		student = self._make_student("_Test SW Student Null Template")
		template = self._make_active_template("_Test SW Active Null Template")
		frappe.db.set_value(
			"CRM Student",
			student.name,
			{
				"applied_score_input_revision": 50,
				"applied_policy_revision": 50,
				"applied_score_template": None,
			},
			update_modified=False,
		)
		result = append_score_if_current(
			**self._payload(
				student.name,
				template.name,
				policy_revision=template.policy_revision,
				policy_hash=template.policy_hash,
				components={
					"fit": 40,
					"engagement": 40,
					"intent": 40,
					"negative": {"score": 0, "contributors": []},
				},
				source_score_input_revision=1,
			)
		)
		self.assertTrue(result["applied"])
		student.reload()
		self.assertEqual(student.applied_score_template, template.name)

	def test_bump_score_input_revision_is_monotonic_per_student(self):
		student = self._make_student("_Test SW Student Bump")
		# Student insert already bumped score_input_revision once (on_update
		# always bumps for a new row) -- explicit bumps continue from there.
		baseline = frappe.db.get_value("CRM Student", student.name, "score_input_revision")

		first = bump_score_input_revision(student.name, "test_reason", enqueue=False)
		second = bump_score_input_revision(student.name, "test_reason", enqueue=False)

		self.assertEqual(first["revision"], baseline + 1)
		self.assertEqual(second["revision"], baseline + 2)
