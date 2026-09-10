# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate


class TestCRMEvent(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.campus = self._make_campus("_Test Event Campus")
		self.campaign = self._make_campaign("_Test Event Campaign", self.campus)

	def tearDown(self):
		for name in frappe.db.get_all("CRM Event", filters={"title": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Event", name, force=True)
		for name in frappe.db.get_all("CRM Campaign", filters={"title": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Campaign", name, force=True)
		for name in frappe.db.get_all("CRM Staff", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Staff", name, force=True)
		for name in frappe.db.get_all("User", filters={"first_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("User", name, force=True)
		for name in frappe.db.get_all(
			"CRM Department", filters={"department_name": ["like", "_Test%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Department", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Campus", name, force=True)

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc(
			{"doctype": "CRM Campus", "campus_name": name, "campus_code": "TEST-EVENT"}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_campaign(self, title, campus):
		if frappe.db.exists("CRM Campaign", title):
			frappe.delete_doc("CRM Campaign", title, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campaign", "title": title, "campus": campus})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_department(self, name, campus):
		if not frappe.db.exists("CRM Department", name):
			frappe.get_doc(
				{"doctype": "CRM Department", "department_name": name, "campus": campus}
			).insert(ignore_permissions=True)
		return name

	def _make_staff_user(self, prefix, campus):
		department = self._make_department(f"_Test Dept {prefix}", campus)

		email = f"{frappe.scrub(prefix)}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": prefix,
				"send_welcome_email": 0,
			}
		)
		user.insert(ignore_permissions=True)

		staff_name = f"_Test Staff {prefix}"
		if frappe.db.exists("CRM Staff", staff_name):
			frappe.delete_doc("CRM Staff", staff_name, force=True)
		staff = frappe.get_doc(
			{
				"doctype": "CRM Staff",
				"full_name": staff_name,
				"user": email,
				"department": department,
				"campus": campus,
			}
		)
		staff.insert(ignore_permissions=True)
		return email, staff.name

	# ------------------------------------------------------------ before_insert

	def test_owner_staff_defaults_from_session_user(self):
		email, staff_name = self._make_staff_user("_Test Event Owner", self.campus)

		frappe.set_user(email)
		try:
			event = frappe.get_doc(
				{
					"doctype": "CRM Event",
					"title": "_Test Event Owner Default",
					"crm_campaign": self.campaign,
					"start_datetime": "2026-09-01 10:00:00",
				}
			)
			event.insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

		event.reload()
		self.assertEqual(event.owner_staff, staff_name)

	def test_start_datetime_falls_back_from_event_date_on_insert(self):
		event = frappe.get_doc(
			{
				"doctype": "CRM Event",
				"title": "_Test Event Date Fallback",
				"crm_campaign": self.campaign,
				"event_date": "2026-09-15",
			}
		)
		event.insert(ignore_permissions=True)
		event.reload()

		self.assertTrue(event.start_datetime)
		self.assertEqual(getdate(event.start_datetime), getdate("2026-09-15"))

	def test_start_datetime_required_when_no_event_date_fallback(self):
		event = frappe.get_doc(
			{
				"doctype": "CRM Event",
				"title": "_Test Event No Date",
				"crm_campaign": self.campaign,
			}
		)
		with self.assertRaises(frappe.MandatoryError):
			event.insert(ignore_permissions=True)

	def test_event_date_stays_synced_from_start_datetime_on_validate(self):
		event = frappe.get_doc(
			{
				"doctype": "CRM Event",
				"title": "_Test Event Sync",
				"crm_campaign": self.campaign,
				"start_datetime": "2026-10-01 09:00:00",
			}
		)
		event.insert(ignore_permissions=True)
		event.reload()
		self.assertEqual(getdate(event.event_date), getdate("2026-10-01"))

		event.start_datetime = "2026-10-05 09:00:00"
		event.save(ignore_permissions=True)
		event.reload()
		self.assertEqual(getdate(event.event_date), getdate("2026-10-05"))
