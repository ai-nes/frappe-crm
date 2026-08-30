import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMStudentGeographySnapshot(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_snapshot_is_command_only(self):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Student Geography Snapshot",
				"student": "__missing_student__",
				"captured_at": frappe.utils.now_datetime(),
				"province": "__missing_province__",
				"source": "test",
			}
		)
		doc.flags.ignore_links = True
		with self.assertRaises(frappe.PermissionError):
			doc.insert(ignore_permissions=True)
