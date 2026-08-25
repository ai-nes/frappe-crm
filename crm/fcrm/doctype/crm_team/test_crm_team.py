# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMTeam(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = self._make_campus("_Test Team Campus")

	def tearDown(self):
		for name in frappe.db.get_all(
			"CRM Team Membership", filters={"team": ["like", "_Test%"]}, pluck="parent"
		):
			if frappe.db.exists("CRM Staff", name):
				frappe.delete_doc("CRM Staff", name, force=True)
		for name in frappe.db.get_all("CRM Team", filters={"team_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Team", name, force=True)
		for name in frappe.db.get_all(
			"CRM Department", filters={"department_name": ["like", "_Test%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Department", name, force=True)
		self._cleanup_campus(self._campus)

	def test_create_team(self):
		team = self._make_team("_Test Team Alpha")
		self.assertEqual(team.team_name, "_Test Team Alpha")
		self.assertEqual(team.campus, self._campus)

	def test_cannot_delete_team_with_active_membership(self):
		team = self._make_team("_Test Team With Members")
		staff, user = self._make_staff("_Test Team Member Staff")

		staff.append(
			"team_memberships",
			{
				"team": team.name,
				"function": "Sale",
				"term": "",
				"is_primary": 1,
			},
		)
		staff.save(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			team.delete()

		self._cleanup_staff(staff.name, user)

	def test_can_delete_team_without_membership(self):
		team = self._make_team("_Test Team No Members")
		team.delete()
		self.assertFalse(frappe.db.exists("CRM Team", team.name))

	# ---------------------------------------------------------------- helpers

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _cleanup_campus(self, campus):
		if campus and frappe.db.exists("CRM Campus", campus):
			frappe.delete_doc("CRM Campus", campus, force=True)

	def _make_team(self, name, team_type="Sales"):
		if frappe.db.exists("CRM Team", name):
			frappe.delete_doc("CRM Team", name, force=True)
		team = frappe.get_doc(
			{
				"doctype": "CRM Team",
				"team_name": name,
				"team_type": team_type,
				"campus": self._campus,
				"is_active": 1,
			}
		)
		team.insert(ignore_permissions=True)
		return team

	def _make_staff(self, name, department=None):
		if frappe.db.exists("CRM Staff", name):
			frappe.delete_doc("CRM Staff", name, force=True)
		if not department:
			department = self._get_or_create_department("_Test Team Dept")

		email = f"{frappe.scrub(name)}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": name,
				"send_welcome_email": 0,
			}
		)
		user.insert(ignore_permissions=True)

		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": name,
				"user": email,
				"department": department,
				"campus": self._campus,
			}
		)
		staff.insert(ignore_permissions=True)
		return staff, email

	def _cleanup_staff(self, staff_name, user_email):
		if staff_name and frappe.db.exists("CRM Staff", staff_name):
			frappe.delete_doc("CRM Staff", staff_name, force=True)
		if user_email and frappe.db.exists("User", user_email):
			frappe.delete_doc("User", user_email, force=True)

	def _get_or_create_department(self, name):
		if not frappe.db.exists("CRM Department", name):
			frappe.get_doc(
				{
					"doctype": "CRM Department",
					"department_name": name,
					"campus": self._campus,
				}
			).insert(ignore_permissions=True)
		return name
