from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_privacy import open_privacy_request, resolve_privacy_request
from crm.fcrm.doctype.crm_contact_consent_event.crm_contact_consent_event import sync_student_privacy_projection
from crm.fcrm.student_context import _privacy_context


class TestCRMStudentPrivacyRequest(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def _student(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": "_Test Privacy Student",
				"phone": "0987000091",
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

	def test_privacy_request_is_command_only_and_resolvable(self):
		student = self._student()
		request = open_privacy_request(student.name, "access", details="Please provide a copy of the record.")
		self.assertEqual(request["status"], "open")
		resolved = resolve_privacy_request(request["name"], "completed", "Exported the permitted Student 360 record.")
		self.assertEqual(resolved["status"], "completed")
		self.assertEqual(resolved["resolved_by"], "Administrator")

	def test_invalid_privacy_request_type_is_rejected(self):
		student = self._student()
		with self.assertRaises(frappe.ValidationError):
			open_privacy_request(student.name, "share_with_ad_network")

	def test_privacy_resolution_audit_fields_are_immutable_outside_command(self):
		student = self._student()
		request = open_privacy_request(student.name, "access", details="Audit test")
		doc = frappe.get_doc("CRM Student Privacy Request", request["name"])
		doc.resolution = "tampered"
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)

	def test_terminal_privacy_request_cannot_be_reopened(self):
		student = self._student()
		request = open_privacy_request(student.name, "access", details="Terminal test")
		resolve_privacy_request(request["name"], "completed", "Completed with permitted export.")
		with self.assertRaises(frappe.PermissionError):
			resolve_privacy_request(request["name"], "in_progress", "")

	def test_consent_event_projects_student_privacy_status(self):
		student = self._student()
		event = frappe._dict(
			student=student.name,
			event_type="Opted Out",
			occurred_at=frappe.utils.now_datetime(),
			granted_at=None,
		)
		sync_student_privacy_projection(event)
		self.assertEqual(frappe.db.get_value("CRM Student", student.name, "privacy_status"), "opted_out")

	def test_privacy_context_reads_consent_and_retention_from_canonical_event(self):
		occurred_at = datetime(2026, 8, 30, 9, 0, 0)
		consent = frappe._dict(name="CONSENT-1", occurred_at=occurred_at, granted_at=None)
		with (
			patch(
				"crm.fcrm.student_context._exists",
				side_effect=lambda doctype: doctype == "CRM Contact Consent Event",
			),
			patch("crm.fcrm.student_context._can_read_record", return_value=True),
			patch("crm.fcrm.student_context.frappe.get_all", return_value=[consent]),
			patch.dict(frappe.conf, {"crm_student_privacy_retention_days": 30}, clear=False),
		):
			context = _privacy_context("STU-1", frappe._dict(privacy_status="granted"))

		self.assertEqual(context["consent_at"], str(occurred_at))
		self.assertIsNotNone(context["retention_until"])
