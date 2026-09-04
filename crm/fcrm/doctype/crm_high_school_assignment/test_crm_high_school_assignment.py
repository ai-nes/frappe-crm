# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today


class TestCRMHighSchoolAssignment(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = self._make_campus("_Test HSA Campus")
		self._province = self._make_province("_Test HSA Province", "_THSAP")
		self._cluster = self._make_cluster("_Test HSA Cluster", self._province)
		self._zone = self._make_zone("_Test HSA Zone", self._cluster)
		self._ward = self._make_ward("_Test HSA Ward", self._zone)
		self._school = self._make_school("_Test HSA School", self._ward)
		self._team = self._make_team("_Test HSA Team")
		self._other_team = self._make_team("_Test HSA Team Other")
		self._staff = self._add_active_member(self._team, "_Test HSA Staff")

	def tearDown(self):
		frappe.db.delete("CRM High School Assignment", {"high_school": self._school})
		frappe.db.delete("CRM Team Zone Assignment", {"zone": self._zone})
		frappe.delete_doc("CRM High School", self._school, force=True)
		frappe.delete_doc("CRM Ward", self._ward, force=True)
		for name in frappe.db.get_all(
			"CRM Team Membership", filters={"team": ["in", [self._team, self._other_team]]}, pluck="parent"
		):
			if frappe.db.exists("CRM Staff", name):
				frappe.delete_doc("CRM Staff", name, force=True)
		for team in (self._team, self._other_team):
			frappe.delete_doc("CRM Team", team, force=True)
		frappe.delete_doc("CRM Zone", self._zone, force=True)
		frappe.delete_doc("CRM Cluster", self._cluster, force=True)
		frappe.delete_doc("CRM Province", self._province, force=True)
		frappe.delete_doc("CRM Campus", self._campus, force=True)

	def test_rejects_assignment_outside_team_zone_scope(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "CRM High School Assignment",
					"staff": self._staff,
					"team": self._team,
					"high_school": self._school,
				}
			).insert(ignore_permissions=True)

	def test_allows_assignment_once_team_owns_zone_and_flags_on_reassignment(self):
		self._activate_zone(self._team)

		assignment = frappe.get_doc(
			{
				"doctype": "CRM High School Assignment",
				"staff": self._staff,
				"team": self._team,
				"high_school": self._school,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(assignment.zone, self._zone)
		self.assertEqual(assignment.needs_review, 0)

		self._add_active_member(self._other_team, "_Test HSA Staff Other")
		self._activate_zone(self._other_team, effective_from=add_days(today(), 1))

		assignment.reload()
		self.assertEqual(assignment.needs_review, 1)
		self.assertEqual(assignment.status, "Active")

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
		return frappe.get_doc({"doctype": "CRM Cluster", "cluster_name": name, "province": province}).insert(
			ignore_permissions=True
		).name

	def _make_zone(self, name, cluster):
		return frappe.get_doc({"doctype": "CRM Zone", "zone_name": name, "cluster": cluster}).insert(
			ignore_permissions=True
		).name

	def _make_ward(self, name, zone):
		return frappe.get_doc(
			{"doctype": "CRM Ward", "ward_code": "_THSAW", "ward_name": name, "zone": zone, "ward_type": "Ward"}
		).insert(ignore_permissions=True).name

	def _make_school(self, name, ward):
		return frappe.get_doc(
			{
				"doctype": "CRM High School",
				"school_name": name,
				"school_code": "_THSA",
				"ward": ward,
				"is_active": 1,
			}
		).insert(ignore_permissions=True).name

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
		department_name = "_Test HSA Dept"
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

	def _activate_zone(self, team, effective_from=None):
		frappe.get_doc(
			{
				"doctype": "CRM Team Zone Assignment",
				"team": team,
				"zone": self._zone,
				"status": "Active",
				"effective_from": effective_from or today(),
			}
		).insert(ignore_permissions=True)
