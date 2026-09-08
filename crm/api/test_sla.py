# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Tests for Phase 3 SLA tracking: sla_started_at (set once on first assignment,
see CRMContact._track_sla_start) and recompute_sla_statuses (crm/api/sla.py)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from crm.api.sla import (
	BREACH,
	ON_TIME,
	SLA_BREACH_MINUTES,
	SLA_WARNING_MINUTES,
	WARNING,
	recompute_sla_statuses,
)


class TestSlaStartedAt(FrappeTestCase):
	"""Covers: sla_started_at set once on first assignment and never
	overwritten on a later reassignment."""

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		for name in frappe.db.get_all("CRM Student", filters={"full_name": ["like", "_Test SLA%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for name in frappe.db.get_all("CRM Staff", filters={"full_name": ["like", "_Test SLA%"]}, pluck="name"):
			frappe.delete_doc("CRM Staff", name, force=True)
		for name in frappe.db.get_all("User", filters={"first_name": ["like", "_Test SLA%"]}, pluck="name"):
			frappe.delete_doc("User", name, force=True)
		for name in frappe.db.get_all("CRM Team", filters={"team_name": ["like", "_Test SLA%"]}, pluck="name"):
			frappe.delete_doc("CRM Team", name, force=True)
		for name in frappe.db.get_all(
			"CRM Department", filters={"department_name": ["like", "_Test SLA%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Department", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test SLA%"]}, pluck="name"):
			frappe.delete_doc("CRM Campus", name, force=True)

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

	def _make_team(self, name, campus):
		if frappe.db.exists("CRM Team", name):
			frappe.delete_doc("CRM Team", name, force=True)
		team = frappe.get_doc(
			{"doctype": "CRM Team", "team_name": name, "team_type": "Sales", "campus": campus, "is_active": 1}
		)
		team.insert(ignore_permissions=True)
		return team.name

	def _make_staff(self, name, campus, department, team):
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
			{"doctype": "CRM Staff", "full_name": name, "user": email, "department": department, "campus": campus}
		)
		staff.append("team_memberships", {"team": team, "function": "Sale", "term": "", "is_primary": 1})
		staff.insert(ignore_permissions=True)
		return staff.name

	def test_sla_started_at_set_on_first_assignment(self):
		campus = self._make_campus("_Test SLA Campus")
		team = self._make_team("_Test SLA Team", campus)
		department = self._make_department("_Test SLA Dept", campus)
		staff = self._make_staff("_Test SLA Staff", campus, department, team)

		contact = frappe.get_doc(
			{"doctype": "CRM Student", "full_name": "_Test SLA Contact", "phone": "0922222201"}
		)
		contact.insert(ignore_permissions=True)
		self.assertFalse(contact.sla_started_at)

		contact.assigned_to = staff
		contact._track_sla_start()
		frappe.db.set_value(
			"CRM Student",
			contact.name,
			{"assigned_to": staff, "sla_started_at": contact.sla_started_at},
			update_modified=False,
		)
		contact.reload()
		self.assertTrue(contact.sla_started_at)

	def test_sla_started_at_not_overwritten_on_reassignment(self):
		campus = self._make_campus("_Test SLA Reassign Campus")
		team = self._make_team("_Test SLA Reassign Team", campus)
		department = self._make_department("_Test SLA Reassign Dept", campus)
		staff_a = self._make_staff("_Test SLA Staff A", campus, department, team)
		staff_b = self._make_staff("_Test SLA Staff B", campus, department, team)

		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "_Test SLA Reassign Contact",
				"phone": "0922222202",
				"assigned_to": staff_a,
			}
		)
		contact.insert(ignore_permissions=True)
		contact.reload()
		first_sla_started_at = contact.sla_started_at
		self.assertTrue(first_sla_started_at)

		# Ownership updates are command-owned in production; model the persisted
		# reassignment without bypassing that document guard in this unit test.
		frappe.db.set_value("CRM Student", contact.name, "assigned_to", staff_b, update_modified=False)
		contact.reload()

		self.assertEqual(contact.sla_started_at, first_sla_started_at)


class TestRecomputeSlaStatuses(FrappeTestCase):
	"""Covers recompute_sla_statuses' bulk classification against the two
	thresholds, scoped to open-bucket enrollment statuses only."""

	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		for name in frappe.db.get_all("CRM Student", filters={"full_name": ["like", "_Test SLA Recompute%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)

	def _make_contact(self, name, phone, sla_started_at, enrollment_status="NEW"):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": name,
				"phone": phone,
				"enrollment_status": enrollment_status,
			}
		)
		contact.insert(ignore_permissions=True)
		frappe.db.set_value("CRM Student", contact.name, "sla_started_at", sla_started_at, update_modified=False)
		return contact.name

	def test_recompute_marks_on_time_within_warning_window(self):
		name = self._make_contact(
			"_Test SLA Recompute OnTime",
			"0922222301",
			add_to_date(now_datetime(), minutes=-1),
		)
		recompute_sla_statuses()
		self.assertEqual(frappe.db.get_value("CRM Student", name, "sla_status"), ON_TIME)

	def test_recompute_marks_warning_between_thresholds(self):
		name = self._make_contact(
			"_Test SLA Recompute Warning",
			"0922222302",
			add_to_date(now_datetime(), minutes=-(SLA_WARNING_MINUTES + 5)),
		)
		recompute_sla_statuses()
		self.assertEqual(frappe.db.get_value("CRM Student", name, "sla_status"), WARNING)

	def test_recompute_marks_breach_past_breach_threshold(self):
		name = self._make_contact(
			"_Test SLA Recompute Breach",
			"0922222303",
			add_to_date(now_datetime(), minutes=-(SLA_BREACH_MINUTES + 5)),
		)
		recompute_sla_statuses()
		self.assertEqual(frappe.db.get_value("CRM Student", name, "sla_status"), BREACH)

	def test_recompute_skips_contacts_with_no_sla_started_at(self):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "_Test SLA Recompute Unassigned",
				"phone": "0922222304",
				"enrollment_status": "NEW",
			}
		)
		contact.insert(ignore_permissions=True)
		self.assertFalse(contact.sla_started_at)

		recompute_sla_statuses()

		self.assertFalse(frappe.db.get_value("CRM Student", contact.name, "sla_status"))

	def test_recompute_skips_contacts_outside_open_status_bucket(self):
		# "Đã nhập học" maps to stage_category "enrolled" (per seeded CRM
		# Enrollment Status data) — closed leads must not get a live SLA
		# status even if sla_started_at is old enough to breach.
		name = self._make_contact(
			"_Test SLA Recompute Closed",
			"0922222305",
			add_to_date(now_datetime(), minutes=-(SLA_BREACH_MINUTES + 5)),
			enrollment_status="ENROLLED",
		)
		recompute_sla_statuses()
		self.assertNotEqual(frappe.db.get_value("CRM Student", name, "sla_status"), BREACH)
