# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today


class TestCRMTeamZoneAssignment(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = self._make_campus("_Test TZA Campus")
		self._province = self._make_province("_Test TZA Province", "_TTZAP")
		self._cluster = self._make_cluster("_Test TZA Cluster", self._province)
		self._zone = self._make_zone("_Test TZA Zone", self._cluster)
		self._team_a = self._make_team("_Test TZA Team A")
		self._team_b = self._make_team("_Test TZA Team B")

	def tearDown(self):
		frappe.db.delete("CRM Team Zone Assignment", {"zone": self._zone})
		for name in frappe.db.get_all(
			"CRM Team Membership", filters={"team": ["in", [self._team_a, self._team_b]]}, pluck="parent"
		):
			if frappe.db.exists("CRM Staff", name):
				frappe.delete_doc("CRM Staff", name, force=True)
		for team in (self._team_a, self._team_b):
			if frappe.db.exists("CRM Team", team):
				frappe.delete_doc("CRM Team", team, force=True)
		frappe.delete_doc("CRM Zone", self._zone, force=True)
		frappe.delete_doc("CRM Cluster", self._cluster, force=True)
		frappe.delete_doc("CRM Province", self._province, force=True)
		frappe.delete_doc("CRM Campus", self._campus, force=True)

	def test_cannot_activate_without_active_member(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "CRM Team Zone Assignment",
					"team": self._team_a,
					"zone": self._zone,
					"status": "Active",
					"effective_from": today(),
				}
			).insert(ignore_permissions=True)

	def test_activating_new_team_retires_old_and_syncs_zone(self):
		self._add_active_member(self._team_a, "_Test TZA Staff A")
		self._add_active_member(self._team_b, "_Test TZA Staff B")

		row_a = frappe.get_doc(
			{
				"doctype": "CRM Team Zone Assignment",
				"team": self._team_a,
				"zone": self._zone,
				"status": "Active",
				"effective_from": today(),
			}
		).insert(ignore_permissions=True)

		zone = frappe.get_doc("CRM Zone", self._zone)
		self.assertEqual(zone.current_team, self._team_a)
		self.assertEqual(zone.assignment_status, "Assigned")

		frappe.get_doc(
			{
				"doctype": "CRM Team Zone Assignment",
				"team": self._team_b,
				"zone": self._zone,
				"status": "Active",
				"effective_from": add_days(today(), 1),
			}
		).insert(ignore_permissions=True)

		row_a.reload()
		self.assertEqual(row_a.status, "Retired")

		zone.reload()
		self.assertEqual(zone.current_team, self._team_b)

	def test_cannot_deactivate_team_with_active_zone(self):
		self._add_active_member(self._team_a, "_Test TZA Staff C")
		frappe.get_doc(
			{
				"doctype": "CRM Team Zone Assignment",
				"team": self._team_a,
				"zone": self._zone,
				"status": "Active",
				"effective_from": today(),
			}
		).insert(ignore_permissions=True)

		team = frappe.get_doc("CRM Team", self._team_a)
		team.is_active = 0
		with self.assertRaises(frappe.ValidationError):
			team.save(ignore_permissions=True)

	# ---------------------------------------------------------------- helpers

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		return frappe.get_doc({"doctype": "CRM Campus", "campus_name": name}).insert(ignore_permissions=True).name

	def _make_province(self, name, code):
		if frappe.db.exists("CRM Province", name):
			frappe.delete_doc("CRM Province", name, force=True)
		return frappe.get_doc(
			{"doctype": "CRM Province", "province_name": name, "province_code": code, "city_type": "Province"}
		).insert(ignore_permissions=True).name

	def _make_cluster(self, name, province):
		return frappe.get_doc(
			{"doctype": "CRM Cluster", "cluster_name": name, "province": province}
		).insert(ignore_permissions=True).name

	def _make_zone(self, name, cluster):
		return frappe.get_doc({"doctype": "CRM Zone", "zone_name": name, "cluster": cluster}).insert(
			ignore_permissions=True
		).name

	def _make_team(self, name):
		if frappe.db.exists("CRM Team", name):
			frappe.delete_doc("CRM Team", name, force=True)
		return frappe.get_doc(
			{
				"doctype": "CRM Team",
				"team_name": name,
				"team_type": "Sales",
				"campus": self._campus,
				"is_active": 1,
			}
		).insert(ignore_permissions=True).name

	def _add_active_member(self, team, staff_name):
		if frappe.db.exists("CRM Staff", staff_name):
			frappe.delete_doc("CRM Staff", staff_name, force=True)
		department_name = "_Test TZA Dept"
		if not frappe.db.exists("CRM Department", department_name):
			frappe.get_doc(
				{"doctype": "CRM Department", "department_name": department_name, "campus": self._campus}
			).insert(ignore_permissions=True)
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": staff_name,
				"department": department_name,
				"campus": self._campus,
				"is_active": 1,
			}
		)
		staff.append("team_memberships", {"team": team, "function": "Sale", "is_primary": 1})
		staff.insert(ignore_permissions=True)
		return staff.name
