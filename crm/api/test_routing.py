# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Compatibility tests for the retired campus-only routing surface.

New assignment is explicit and batch-driven; these tests ensure old callers do
not silently mutate a Lead or Student anymore.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.routing import pick_round_robin_staff, pick_team_for_campus, route_new_lead


class TestRouting(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		for name in frappe.db.get_all("CRM Student", filters={"full_name": ["like", "_Test Routing%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for name in frappe.db.get_all("CRM Staff", filters={"full_name": ["like", "_Test Routing%"]}, pluck="name"):
			frappe.delete_doc("CRM Staff", name, force=True)
		for name in frappe.db.get_all("User", filters={"first_name": ["like", "_Test Routing%"]}, pluck="name"):
			frappe.delete_doc("User", name, force=True)
		for name in frappe.db.get_all("CRM Team", filters={"team_name": ["like", "_Test Routing%"]}, pluck="name"):
			frappe.delete_doc("CRM Team", name, force=True)
		for name in frappe.db.get_all(
			"CRM Department", filters={"department_name": ["like", "_Test Routing%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Department", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test Routing%"]}, pluck="name"):
			frappe.delete_doc("CRM Campus", name, force=True)

	# --------------------------------------------------------------- helpers

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_department(self, name, campus):
		if not frappe.db.exists("CRM Department", name):
			frappe.get_doc(
				{"doctype": "CRM Department", "department_name": name, "campus": campus}
			).insert(ignore_permissions=True)
		return name

	def _make_team(self, name, campus, is_active=1):
		if frappe.db.exists("CRM Team", name):
			frappe.delete_doc("CRM Team", name, force=True)
		team = frappe.get_doc(
			{
				"doctype": "CRM Team",
				"team_name": name,
				"team_type": "Sales",
				"campus": campus,
				"is_active": is_active,
			}
		)
		team.insert(ignore_permissions=True)
		return team.name

	def _make_staff(self, name, campus, department, team, is_active=1, last_routed_at=None):
		email = f"{frappe.scrub(name)}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		)
		user.insert(ignore_permissions=True)

		if frappe.db.exists("CRM Staff", name):
			frappe.delete_doc("CRM Staff", name, force=True)
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": name,
				"user": email,
				"department": department,
				"campus": campus,
				"is_active": is_active,
			}
		)
		staff.append("team_memberships", {"team": team, "function": "Sale", "term": "", "is_primary": 1})
		staff.insert(ignore_permissions=True)
		if last_routed_at is not None:
			frappe.db.set_value("CRM Staff", staff.name, "last_routed_at", last_routed_at, update_modified=False)
		return staff.name

	def _make_contact(self, name, phone, branch):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": name,
				"phone": phone,
				"branch": branch,
			}
		)
		contact.insert(ignore_permissions=True)
		return contact

	# ---------------------------------------------------- pick_team_for_campus

	def test_pick_team_for_campus_returns_none_when_no_campus(self):
		self.assertIsNone(pick_team_for_campus(None))

	def test_pick_team_for_campus_ignores_inactive_teams(self):
		campus = self._make_campus("_Test Routing Inactive Campus")
		self._make_team("_Test Routing Inactive Team", campus, is_active=0)
		self.assertIsNone(pick_team_for_campus(campus))

	def test_pick_team_for_campus_picks_oldest_when_multiple(self):
		campus = self._make_campus("_Test Routing Multi Team Campus")
		first = self._make_team("_Test Routing Team A", campus)
		self._make_team("_Test Routing Team B", campus)
		self.assertEqual(pick_team_for_campus(campus), first)

	# -------------------------------------------------- scenario: no available staff

	def test_no_available_staff_leaves_contact_unassigned_and_still_creates(self):
		campus = self._make_campus("_Test Routing No Staff Campus")
		self._make_team("_Test Routing No Staff Team", campus)
		# Team exists and is active, but has zero active staff.

		contact = self._make_contact("_Test Routing No Staff Contact", "0921111101", campus)

		self.assertFalse(contact.assigned_to)
		self.assertTrue(frappe.db.exists("CRM Student", contact.name))

	def test_no_active_staff_because_all_inactive_leaves_contact_unassigned(self):
		campus = self._make_campus("_Test Routing All Inactive Campus")
		team = self._make_team("_Test Routing All Inactive Team", campus)
		department = self._make_department("_Test Routing All Inactive Dept", campus)
		self._make_staff("_Test Routing Inactive Staff", campus, department, team, is_active=0)

		self.assertIsNone(pick_round_robin_staff(team))

		contact = self._make_contact("_Test Routing All Inactive Contact", "0921111102", campus)
		self.assertFalse(contact.assigned_to)

	# ------------------------------------------------------------------- routing

	def test_route_new_lead_does_not_assign_implicitly(self):
		campus = self._make_campus("_Test Routing Match Campus")
		team = self._make_team("_Test Routing Match Team", campus)
		department = self._make_department("_Test Routing Match Dept", campus)
		self._make_staff("_Test Routing Match Staff", campus, department, team)

		contact = self._make_contact("_Test Routing Match Contact", "0921111103", campus)
		contact.reload()

		self.assertFalse(contact.assigned_to)
		self.assertEqual(route_new_lead(contact)["reason"], "BATCH_REQUIRED")

	def test_route_new_lead_noop_when_already_assigned(self):
		campus = self._make_campus("_Test Routing Preassigned Campus")
		team = self._make_team("_Test Routing Preassigned Team", campus)
		department = self._make_department("_Test Routing Preassigned Dept", campus)
		staff = self._make_staff("_Test Routing Preassigned Staff", campus, department, team)

		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "_Test Routing Preassigned Contact",
				"phone": "0921111104",
				"branch": campus,
				"assigned_to": staff,
			}
		)
		route_new_lead(contact)
		# Already had an assigned_to before route_new_lead ran (simulated
		# manual assignment) — must be left untouched, not re-routed.
		self.assertEqual(contact.assigned_to, staff)
		self.assertFalse(contact.flags.auto_routed)

	def test_route_new_lead_noop_when_no_branch(self):
		contact = frappe.get_doc(
			{"doctype": "CRM Student", "full_name": "_Test Routing No Branch Contact", "phone": "0921111105"}
		)
		route_new_lead(contact)
		self.assertFalse(contact.assigned_to)

	# ---------------------------------------------------- scenario: round robin

	def test_round_robin_helpers_are_not_used_by_new_record_creation(self):
		campus = self._make_campus("_Test Routing RR Campus")
		team = self._make_team("_Test Routing RR Team", campus)
		department = self._make_department("_Test Routing RR Dept", campus)
		# staff_a was routed longer ago than staff_b, so the first new lead
		# should go to staff_a.
		staff_a = self._make_staff(
			"_Test Routing RR Staff A", campus, department, team, last_routed_at="2020-01-01 00:00:00"
		)
		self._make_staff(
			"_Test Routing RR Staff B", campus, department, team, last_routed_at="2024-01-01 00:00:00"
		)

		contact_1 = self._make_contact("_Test Routing RR Contact 1", "0921111106", campus)
		contact_2 = self._make_contact("_Test Routing RR Contact 2", "0921111107", campus)
		contact_1.reload()
		contact_2.reload()
		self.assertFalse(contact_1.assigned_to)
		self.assertFalse(contact_2.assigned_to)
		self.assertEqual(pick_round_robin_staff(team), staff_a)

	def test_record_creation_does_not_touch_legacy_route_timestamp(self):
		campus = self._make_campus("_Test Routing Mark Campus")
		team = self._make_team("_Test Routing Mark Team", campus)
		department = self._make_department("_Test Routing Mark Dept", campus)
		staff = self._make_staff("_Test Routing Mark Staff", campus, department, team)

		before = frappe.db.get_value("CRM Staff", staff, "last_routed_at")
		self.assertFalse(before)

		self._make_contact("_Test Routing Mark Contact", "0921111108", campus)

		after = frappe.db.get_value("CRM Staff", staff, "last_routed_at")
		self.assertEqual(after, before)
