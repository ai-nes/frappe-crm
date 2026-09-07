import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMTeamGroup(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._province = "_Test Group Province"
		self._province_code = "_TEST_GROUP_PROVINCE"
		self._group_a = "_Test Group A"
		self._group_b = "_Test Group B"
		for group in (self._group_a, self._group_b):
			if frappe.db.exists("CRM Team Group", group):
				frappe.delete_doc("CRM Team Group", group, force=True)
		if frappe.db.exists("CRM Province", self._province):
			frappe.delete_doc("CRM Province", self._province, force=True)

	def tearDown(self):
		for group in (self._group_a, self._group_b):
			if frappe.db.exists("CRM Team Group", group):
				frappe.delete_doc("CRM Team Group", group, force=True)
		if frappe.db.exists("CRM Province", self._province):
			frappe.delete_doc("CRM Province", self._province, force=True)

	def test_active_group_requires_province(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "CRM Team Group",
					"group_name": self._group_a,
					"is_active": 1,
				}
			).insert(ignore_permissions=True)

	def test_one_active_group_per_province(self):
		frappe.get_doc(
			{
				"doctype": "CRM Province",
				"province_name": self._province,
				"province_code": self._province_code,
				"city_type": "Province",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "CRM Team Group",
				"group_name": self._group_a,
				"province": self._province,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "CRM Team Group",
					"group_name": self._group_b,
					"province": self._province,
					"is_active": 1,
				}
			).insert(ignore_permissions=True)
