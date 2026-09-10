# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMProvince(FrappeTestCase):
	def test_create_province(self):
		province = frappe.get_doc(
			{
				"doctype": "CRM Province",
				"province_name": "_Test Province",
				"province_code": "_TP",
				"city_type": "Province",
			}
		)
		province.insert(ignore_permissions=True)
		self.assertEqual(province.province_name, "_Test Province")
		province.delete()

	def test_cannot_delete_province_with_cluster(self):
		province = frappe.get_doc(
			{
				"doctype": "CRM Province",
				"province_name": "_Test Province With Cluster",
				"province_code": "_TPWC",
				"city_type": "Province",
			}
		).insert(ignore_permissions=True)
		cluster = frappe.get_doc(
			{
				"doctype": "CRM Cluster",
				"cluster_name": "_Test Province Cluster",
				"province": province.name,
			}
		).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			province.delete()

		cluster.delete()
		province.delete()
