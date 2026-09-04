# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMZone(FrappeTestCase):
	def test_create_zone_and_block_delete_with_ward(self):
		province = frappe.get_doc(
			{
				"doctype": "CRM Province",
				"province_name": "_Test Zone Province",
				"province_code": "_TZP",
				"city_type": "Province",
			}
		).insert(ignore_permissions=True)
		cluster = frappe.get_doc(
			{"doctype": "CRM Cluster", "cluster_name": "_Test Zone Cluster", "province": province.name}
		).insert(ignore_permissions=True)
		zone = frappe.get_doc(
			{"doctype": "CRM Zone", "zone_name": "_Test Zone", "cluster": cluster.name}
		).insert(ignore_permissions=True)
		self.assertEqual(zone.assignment_status, "Unassigned")

		ward = frappe.get_doc(
			{
				"doctype": "CRM Ward",
				"ward_code": "_TZW",
				"ward_name": "_Test Zone Ward",
				"zone": zone.name,
				"ward_type": "Ward",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(ward.province, province.name)

		self.assertRaises(frappe.ValidationError, zone.delete)

		ward.delete()
		zone.delete()
		cluster.delete()
		province.delete()
