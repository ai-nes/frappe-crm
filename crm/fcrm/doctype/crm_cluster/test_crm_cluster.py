# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMCluster(FrappeTestCase):
	def test_create_cluster_and_block_delete_with_zone(self):
		province = frappe.get_doc(
			{
				"doctype": "CRM Province",
				"province_name": "_Test Cluster Province",
				"province_code": "_TCP",
				"city_type": "Province",
			}
		).insert(ignore_permissions=True)

		cluster = frappe.get_doc(
			{"doctype": "CRM Cluster", "cluster_name": "_Test Cluster", "province": province.name}
		).insert(ignore_permissions=True)
		self.assertEqual(cluster.province, province.name)

		zone = frappe.get_doc(
			{"doctype": "CRM Zone", "zone_name": "_Test Cluster Zone", "cluster": cluster.name}
		).insert(ignore_permissions=True)

		self.assertRaises(frappe.ValidationError, cluster.delete)

		zone.delete()
		cluster.delete()
		province.delete()
