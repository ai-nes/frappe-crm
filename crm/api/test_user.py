import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.user import list_user_role_logs, remove_crm_roles_from_user, update_user_role


class TestUserRoleLog(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.email = "_test_role_log_user@example.com"
		if frappe.db.exists("User", self.email):
			frappe.delete_doc("User", self.email, force=True)
		self.user = frappe.get_doc(
			{
				"doctype": "User",
				"email": self.email,
				"first_name": "Role Log",
				"send_welcome_email": 0,
				"roles": [{"role": "Sale"}],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("CRM User Role Log", {"user": self.email})
		if frappe.db.exists("User", self.email):
			frappe.delete_doc("User", self.email, force=True)

	def test_role_change_writes_one_log_row(self):
		update_user_role(self.email, "Marketing")

		logs = frappe.get_all(
			"CRM User Role Log",
			filters={"user": self.email},
			fields=["action", "previous_role", "new_role", "owner"],
		)
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].action, "role_changed")
		self.assertEqual(logs[0].previous_role, "Sale")
		self.assertEqual(logs[0].new_role, "Marketing")
		self.assertEqual(logs[0].owner, "Administrator")

	def test_removal_writes_one_log_row_with_null_new_role(self):
		remove_crm_roles_from_user(self.email)

		logs = frappe.get_all(
			"CRM User Role Log",
			filters={"user": self.email},
			fields=["action", "previous_role", "new_role"],
		)
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].action, "removed")
		self.assertEqual(logs[0].previous_role, "Sale")
		self.assertIsNone(logs[0].new_role)

	def test_list_user_role_logs_filters_by_user(self):
		update_user_role(self.email, "Marketing")

		result = list_user_role_logs(user=self.email)
		self.assertEqual(result["total"], 1)
		self.assertEqual(len(result["logs"]), 1)
		self.assertEqual(result["logs"][0]["user"], self.email)

	def test_list_user_role_logs_is_gated_to_role_managers(self):
		frappe.set_user(self.email)
		with self.assertRaises(frappe.PermissionError):
			list_user_role_logs()
		frappe.set_user("Administrator")
