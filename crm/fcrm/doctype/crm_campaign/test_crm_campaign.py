# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMCampaign(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
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
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
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
		campus = self._make_campus("_Test Campaign Owner Campus")
		email, staff_name = self._make_staff_user("_Test Campaign Owner", campus)

		frappe.set_user(email)
		try:
			campaign = frappe.get_doc(
				{
					"doctype": "CRM Campaign",
					"title": "_Test Campaign Owner Default",
					"campus": campus,
				}
			)
			campaign.insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

		campaign.reload()
		self.assertEqual(campaign.owner_staff, staff_name)

	def test_owner_staff_not_overridden_when_explicitly_set(self):
		campus = self._make_campus("_Test Campaign Owner Explicit Campus")
		_email, staff_name = self._make_staff_user("_Test Campaign Owner Explicit", campus)
		_email2, staff_name_2 = self._make_staff_user("_Test Campaign Owner Explicit Other", campus)

		campaign = frappe.get_doc(
			{
				"doctype": "CRM Campaign",
				"title": "_Test Campaign Owner Explicit",
				"campus": campus,
				"owner_staff": staff_name_2,
			}
		)
		campaign.insert(ignore_permissions=True)
		campaign.reload()

		self.assertEqual(campaign.owner_staff, staff_name_2)
		self.assertNotEqual(campaign.owner_staff, staff_name)

	def test_owner_staff_left_blank_when_session_user_has_no_staff_record(self):
		campus = self._make_campus("_Test Campaign No Staff Campus")
		campaign = frappe.get_doc(
			{
				"doctype": "CRM Campaign",
				"title": "_Test Campaign No Staff",
				"campus": campus,
			}
		)
		# Administrator has no CRM Staff record in a clean test setup.
		campaign.insert(ignore_permissions=True)
		campaign.reload()
		self.assertFalse(campaign.owner_staff)

	def test_default_status_is_draft(self):
		campus = self._make_campus("_Test Campaign Status Campus")
		campaign = frappe.get_doc(
			{
				"doctype": "CRM Campaign",
				"title": "_Test Campaign Status",
				"campus": campus,
			}
		)
		campaign.insert(ignore_permissions=True)
		self.assertEqual(campaign.status, "DRAFT")

	def test_campaign_code_is_generated_and_immutable(self):
		campus = self._make_campus("_Test Campaign Code Campus")
		campaign = frappe.get_doc(
			{
				"doctype": "CRM Campaign",
				"title": "_Test Campaign Code",
				"campus": campus,
				"start_date": "2026-09-07",
			}
		)
		campaign.insert(ignore_permissions=True)

		self.assertRegex(campaign.stable_code, r"^CAM-2026-\d{5,}$")
		code = campaign.stable_code
		campaign.title = "_Test Campaign Code Renamed"
		campaign.save(ignore_permissions=True)
		campaign.reload()
		self.assertEqual(campaign.stable_code, code)

		campaign.stable_code = "CAM-2026-99999"
		with self.assertRaises(frappe.ValidationError):
			campaign.save(ignore_permissions=True)
