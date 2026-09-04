# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today


class TestCRMStaff(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = self._make_campus("_Test Staff Campus")
		self._department = self._get_or_create_department("_Test Staff Dept")
		self._team_a = self._make_team("_Test Staff Team A")
		self._team_b = self._make_team("_Test Staff Team B")

	def tearDown(self):
		for name in frappe.db.get_all("CRM Staff", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Staff", name, force=True)
		for name in frappe.db.get_all("User", filters={"first_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("User", name, force=True)
		for name in frappe.db.get_all("CRM Team", filters={"team_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Team", name, force=True)
		for name in frappe.db.get_all(
			"CRM Department", filters={"department_name": ["like", "_Test%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Department", name, force=True)
		self._cleanup_campus(self._campus)

	def test_single_primary_membership_allowed(self):
		staff = self._make_staff("_Test Staff Single Primary")
		staff.append(
			"team_memberships",
			{
				"team": self._team_a,
				"function": "Sale",
				"term": "2026-1",
				"is_primary": 1,
			},
		)
		staff.save(ignore_permissions=True)
		staff.reload()
		self.assertEqual(len(staff.team_memberships), 1)

	def test_two_primary_memberships_same_context_rejected(self):
		staff = self._make_staff("_Test Staff Duplicate Primary")
		staff.append(
			"team_memberships",
			{
				"team": self._team_a,
				"function": "Sale",
				"term": "2026-1",
				"is_primary": 1,
			},
		)
		staff.append(
			"team_memberships",
			{
				"team": self._team_b,
				"function": "Sale",
				"term": "2026-1",
				"is_primary": 1,
			},
		)
		with self.assertRaises(frappe.ValidationError):
			staff.save(ignore_permissions=True)

	def test_two_primary_memberships_different_term_allowed(self):
		staff = self._make_staff("_Test Staff Different Term")
		staff.append(
			"team_memberships",
			{
				"team": self._team_a,
				"function": "Sale",
				"term": "2026-1",
				"is_primary": 1,
			},
		)
		staff.append(
			"team_memberships",
			{
				"team": self._team_b,
				"function": "Sale",
				"term": "2026-2",
				"is_primary": 1,
			},
		)
		staff.save(ignore_permissions=True)
		staff.reload()
		self.assertEqual(len(staff.team_memberships), 2)

	def test_two_primary_memberships_different_function_allowed(self):
		staff = self._make_staff("_Test Staff Different Function")
		staff.append(
			"team_memberships",
			{
				"team": self._team_a,
				"function": "Sale",
				"term": "2026-1",
				"is_primary": 1,
			},
		)
		staff.append(
			"team_memberships",
			{
				"team": self._team_b,
				"function": "Lead Sales",
				"term": "2026-1",
				"is_primary": 1,
			},
		)
		staff.save(ignore_permissions=True)
		staff.reload()
		self.assertEqual(len(staff.team_memberships), 2)

	def test_non_primary_duplicates_in_same_context_allowed(self):
		staff = self._make_staff("_Test Staff Non Primary Duplicates")
		staff.append(
			"team_memberships",
			{
				"team": self._team_a,
				"function": "Sale",
				"term": "2026-1",
				"is_primary": 0,
			},
		)
		staff.append(
			"team_memberships",
			{
				"team": self._team_b,
				"function": "Sale",
				"term": "2026-1",
				"is_primary": 0,
			},
		)
		staff.save(ignore_permissions=True)
		staff.reload()
		self.assertEqual(len(staff.team_memberships), 2)

	def test_overlapping_memberships_in_same_team_rejected(self):
		staff = self._make_staff("_Test Staff Same Team Memberships")
		staff.append(
			"team_memberships",
			{
				"team": self._team_a,
				"function": "Sale",
				"effective_from": today(),
			},
		)
		staff.append(
			"team_memberships",
			{
				"team": self._team_a,
				"function": "Lead Sales",
				"effective_from": add_days(today(), 1),
			}
		)
		with self.assertRaises(frappe.ValidationError):
			staff.save(ignore_permissions=True)

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

	def _make_team(self, name):
		if frappe.db.exists("CRM Team", name):
			frappe.delete_doc("CRM Team", name, force=True)
		team = frappe.get_doc(
			{
				"doctype": "CRM Team",
				"team_name": name,
				"team_type": "Sales",
				"campus": self._campus,
				"is_active": 1,
			}
		)
		team.insert(ignore_permissions=True)
		return team.name

	def _make_staff(self, name):
		if frappe.db.exists("CRM Staff", name):
			frappe.delete_doc("CRM Staff", name, force=True)

		email = f"{frappe.scrub(name)}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": name,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": name,
				"user": email,
				"department": self._department,
				"campus": self._campus,
			}
		)
		staff.insert(ignore_permissions=True)
		return staff
