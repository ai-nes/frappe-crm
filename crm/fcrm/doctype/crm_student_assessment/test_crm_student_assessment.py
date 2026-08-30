import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_assessment import (
	confirm_student_assessment,
	get_student_assessment_context,
	record_student_assessment,
)


class TestCRMStudentAssessment(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def _student(self, suffix):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": f"_Test Assessment {suffix}",
				"phone": f"0987{suffix:06d}",
				"enrollment_status": "Mới",
			}
		)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = False
		self.addCleanup(lambda: frappe.delete_doc("CRM Student", student.name, force=True))
		return student

	def _values(self, barrier="Information"):
		return {
			"interest": "High",
			"fit": "Medium",
			"primary_barrier": barrier,
			"interest_confidence": 80,
			"fit_confidence": 70,
			"barrier_confidence": 60,
		}

	def test_system_assessment_requires_confirmation_and_projects_confirmed_revision(self):
		student = self._student(1)
		proposal = record_student_assessment(
			student.name,
			self._values(),
			source="system",
			reason="Repeated questions about programme and admissions steps.",
			evidence_references=["interaction:CRM Interaction:INT-1"],
		)
		self.assertEqual(proposal["status"], "proposed")
		student.reload()
		self.assertFalse(student.assessment_status)

		confirmed = confirm_student_assessment(proposal["name"], reason="Staff verified the interaction evidence.")
		self.assertEqual(confirmed["status"], "confirmed")
		student.reload()
		self.assertEqual(student.assessment_status, "confirmed")
		self.assertEqual(student.interest_level, "High")
		self.assertEqual(student.primary_barrier, "Information")

		context = get_student_assessment_context(student.name)
		self.assertEqual(context["current"]["name"], proposal["name"])
		self.assertEqual(context["current"]["confirmed_by"], "Administrator")

	def test_system_assessment_cannot_self_confirm(self):
		student = self._student(2)
		with self.assertRaises(frappe.ValidationError):
			record_student_assessment(
				student.name,
				self._values(),
				source="system",
				reason="Automated signal.",
				evidence_references=["interaction:CRM Interaction:INT-2"],
				confirm=True,
			)

	def test_new_confirmed_revision_supersedes_previous(self):
		student = self._student(3)
		first = record_student_assessment(
			student.name,
			self._values(),
			source="manual",
			reason="Initial staff assessment.",
			evidence_references=["interaction:CRM Interaction:INT-3"],
		)
		second = record_student_assessment(
			student.name,
			self._values("Family"),
			source="manual",
			reason="Parent concern was confirmed.",
			evidence_references=["interaction:CRM Interaction:INT-4"],
		)
		self.assertEqual(second["revision"], first["revision"] + 1)
		self.assertEqual(frappe.db.get_value("CRM Student Assessment", first["name"], "status"), "superseded")
		self.assertEqual(frappe.db.get_value("CRM Student", student.name, "primary_barrier"), "Family")
