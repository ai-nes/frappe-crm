"""Contract tests for the audited AI insight write-back command."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.ai_insight import AIInsightError, ReadBackVerificationError, upsert_ai_insight
from crm.services.student_context import bump_student_context_revision


class TestAIInsightAPI(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._previous_service_user = frappe.conf.get("crm_agents_service_user")
		frappe.conf.crm_agents_service_user = "Administrator"

	def tearDown(self):
		if self._previous_service_user is None:
			frappe.conf.pop("crm_agents_service_user", None)
		else:
			frappe.conf.crm_agents_service_user = self._previous_service_user
		students = frappe.db.get_all(
			"CRM Lead", filters={"student_name": ["like", "_Test AI Insight%"]}, pluck="name"
		)
		for insight in frappe.db.get_all(
			"CRM AI Lead Insight", filters={"student": ["in", students or ["__none__"]]}, pluck="name"
		):
			frappe.delete_doc("CRM AI Lead Insight", insight, force=True)
		for receipt in frappe.db.get_all(
			"CRM Student Command Receipt",
			filters={"target_student": ["in", students or ["__none__"]]},
			pluck="name",
		):
			frappe.db.delete("CRM Student Command Receipt", {"name": receipt})
		for contact in frappe.db.get_all(
			"CRM Student", filters={"student": ["in", students or ["__none__"]]}, pluck="name"
		):
			frappe.delete_doc("CRM Student", contact, force=True)
		for student in students:
			frappe.delete_doc("CRM Lead", student, force=True)

	def _make_pair(self, suffix="Base"):
		student = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": f"_Test AI Insight {suffix}",
				"phone": "0981123456",
				"email": f"ai-insight-{suffix.lower()}@example.com",
				"enrollment_status": "PROSPECT",
			}
		)
		previous_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_flag

		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": f"_Test AI Insight Contact {suffix}",
				"phone": "0981123457",
				"student": student.name,
				"enrollment_status": "PROSPECT",
			}
		)
		previous_flag = getattr(frappe.flags, "contact_migration_service", False)
		frappe.flags.contact_migration_service = True
		try:
			contact.insert(ignore_permissions=True)
		finally:
			frappe.flags.contact_migration_service = previous_flag
		student.reload()
		return student, contact

	def _payload(self, student, key="generation-1", **values):
		payload = {
			"student": student.name,
			"expected_context_revision": int(
				frappe.db.get_value("CRM Lead", student.name, "student_context_revision") or 0
			),
			"generation_idempotency_key": key,
			"idempotency_key": key,
			"producer_identity": "crm-agents:test",
			"ai_policy_version": "test-policy-v1",
			"ai_score": 72.5,
			"ai_score_reason": "Strong program fit.",
			"ai_next_action": "Call the student",
			"ai_summary": "The student is comparing two programs.",
			"ai_detected_interests": [{"dimension_code": "PROGRAM_COMPETITOR", "label": "Program comparison"}],
			"ai_risk_flags": [{"label": "Needs financial information", "severity": "Medium"}],
		}
		payload.update(values)
		return payload

	def test_write_is_idempotent_and_replaces_child_items(self):
		student, contact = self._make_pair()
		payload = self._payload(student)

		first = upsert_ai_insight(**payload)
		second = upsert_ai_insight(**payload)

		self.assertTrue(first["applied"])
		self.assertFalse(first["duplicate"])
		self.assertFalse(first["stale"])
		self.assertEqual(second["applied"], False)
		self.assertTrue(second["duplicate"])
		self.assertEqual(second["current_revision"], payload["expected_context_revision"])
		self.assertEqual(frappe.db.count("CRM AI Lead Insight", {"student": student.name}), 1)

		insight = frappe.get_doc("CRM AI Lead Insight", first["insight"])
		self.assertEqual(insight.student, student.name)
		self.assertEqual(insight.contact, contact.name)
		self.assertEqual(insight.ai_score, 72.5)
		self.assertEqual(insight.ai_summary, payload["ai_summary"])
		self.assertEqual([row.item_kind for row in insight.items], ["interest", "risk"])
		self.assertEqual(
			frappe.db.get_value("CRM Student Command Receipt", first["receipt"], "command_kind"),
			"ai_insight",
		)

		updated = self._payload(
			student,
			key="generation-2",
			ai_summary="The student now prefers the local campus.",
			ai_detected_interests=["CAREER"],
			ai_risk_flags=[],
		)
		third = upsert_ai_insight(**updated)
		self.assertTrue(third["applied"])
		self.assertEqual(third["insight"], first["insight"])
		insight.reload()
		self.assertEqual(len(insight.items), 1)
		self.assertEqual(insight.items[0].item_kind, "interest")
		self.assertEqual(insight.items[0].dimension_code, "CAREER")

	def test_stale_revision_is_a_settled_non_write(self):
		student, _contact = self._make_pair("Stale")
		baseline = int(student.get("student_context_revision") or 0)
		bump_student_context_revision(student.name, "test_ai_insight_stale", enqueue=False)

		result = upsert_ai_insight(**self._payload(student, key="stale-generation", expected_context_revision=baseline))

		self.assertFalse(result["applied"])
		self.assertFalse(result["duplicate"])
		self.assertTrue(result["stale"])
		self.assertEqual(result["current_revision"], baseline + 1)
		self.assertIsNone(result["insight"])
		self.assertEqual(frappe.db.count("CRM AI Lead Insight", {"student": student.name}), 0)

	def test_fields_outside_contract_are_rejected(self):
		with self.assertRaises(AIInsightError) as context:
			upsert_ai_insight(
				student="STU-1",
				expected_context_revision=0,
				generation_idempotency_key="invalid-field",
				producer_identity="crm-agents:test",
				ai_policy_version="test-policy-v1",
				contact="CRM-CONT-1",
			)
		self.assertEqual(context.exception.code, "INVALID_FIELD")

	def test_readback_failure_is_terminal_and_does_not_leave_an_insight(self):
		student, _contact = self._make_pair("Readback")
		with patch(
			"crm.api.ai_insight._verify_readback",
			side_effect=ReadBackVerificationError("READ_BACK_VERIFICATION_FAILED", "forced test failure"),
		):
			result = upsert_ai_insight(**self._payload(student, key="readback-generation"))

		self.assertFalse(result["applied"])
		self.assertFalse(result["duplicate"])
		self.assertFalse(result["stale"])
		self.assertEqual(result["error_code"], "READ_BACK_VERIFICATION_FAILED")
		self.assertEqual(frappe.db.count("CRM AI Lead Insight", {"student": student.name}), 0)

	def test_unexpected_failure_settles_receipt_before_propagating(self):
		student, _contact = self._make_pair("Unexpected")
		key = "unexpected-generation"
		with patch(
			"crm.api.ai_insight._verify_readback",
			side_effect=RuntimeError("forced unexpected failure"),
		):
			with self.assertRaises(RuntimeError):
				upsert_ai_insight(**self._payload(student, key=key))

		receipt = frappe.db.get_value(
			"CRM Student Command Receipt",
			{"correlation_token": key},
			["outcome", "error_code"],
			as_dict=True,
		)
		self.assertEqual(receipt.outcome, "failed")
		self.assertEqual(receipt.error_code, "INTERNAL_ERROR")

	def test_service_identity_is_required(self):
		previous_user = frappe.session.user
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				upsert_ai_insight(**self._payload(frappe._dict(name="STU-1", student_context_revision=0)))
		finally:
			frappe.set_user(previous_user)
