import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.audit import get_student_audit_logs


class TestStudentAuditApi(FrappeTestCase):
	def setUp(self):
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user(self._original_user)
		frappe.db.rollback()

	def test_student_audit_returns_creation_and_field_changes(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": "Audit API Student",
				"phone": "0912345678",
				"email": "audit-api-student@example.com",
			}
		).insert(ignore_permissions=True)

		student.student_name = "Updated Audit API Student"
		student.save(ignore_permissions=True, ignore_version=False)

		result = get_student_audit_logs(student.name)
		actions = [log["action"] for log in result["logs"]]
		updated = next(
			log
			for log in result["logs"]
			if log["action"] == "updated" and log["fieldname"] == "student_name"
		)

		self.assertGreaterEqual(result["total"], 2)
		self.assertIn("created", actions)
		self.assertEqual(updated["fieldname"], "student_name")
		self.assertEqual(updated["old_value"], "Audit API Student")
		self.assertEqual(updated["new_value"], "Updated Audit API Student")
		self.assertEqual(updated["owner"], "Administrator")
		self.assertEqual(
			updated["owner_full_name"], frappe.get_cached_value("User", "Administrator", "full_name")
		)

	def test_student_audit_returns_deleted_event_and_supports_pagination(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": "Deleted Audit API Student",
				"phone": "0912345679",
				"email": "deleted-audit-api-student@example.com",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Deleted Document",
				"deleted_doctype": "CRM Student",
				"deleted_name": student.name,
				"data": "{}",
			}
		).insert(ignore_permissions=True)

		result = get_student_audit_logs(student.name, start=0, page_length=1)
		all_logs = get_student_audit_logs(student.name, page_length=100)

		self.assertEqual(len(result["logs"]), 1)
		self.assertGreaterEqual(result["total"], 2)
		self.assertTrue(any(log["action"] == "deleted" for log in all_logs["logs"]))
		self.assertTrue(all_logs["read_only"])
