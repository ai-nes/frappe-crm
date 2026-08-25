import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.user import set_canonical_crm_profile


class TestUserRoleContract(FrappeTestCase):
	def setUp(self):
		self.email = "_test_role_contract@example.com"
		if frappe.db.exists("User", self.email):
			frappe.delete_doc("User", self.email, force=True)
		self.user = frappe.get_doc(
			{
				"doctype": "User",
				"email": self.email,
				"first_name": "Role Contract",
				"send_welcome_email": 0,
				"roles": [{"role": "Sale"}],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		if frappe.db.exists("User", self.email):
			frappe.delete_doc("User", self.email, force=True)

	def test_canonical_assignment_replaces_business_aliases(self):
		set_canonical_crm_profile(self.user, "Marketing")
		self.user.save(ignore_permissions=True)
		self.user.reload()

		roles = {row.role for row in self.user.roles}
		self.assertIn("Marketing", roles)
		self.assertNotIn("Sale", roles)
		self.assertNotIn("Sales Manager", roles)
		self.assertNotIn("Sales User", roles)

	def test_raw_alias_and_data_steward_cannot_be_selected(self):
		with self.assertRaises(frappe.ValidationError):
			set_canonical_crm_profile(self.user, "Sales User")
		with self.assertRaises(frappe.ValidationError):
			set_canonical_crm_profile(self.user, "CRM Data Steward")
