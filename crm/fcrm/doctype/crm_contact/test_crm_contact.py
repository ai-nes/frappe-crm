import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMContact(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		for name in frappe.db.get_all("CRM Contact", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Contact", name, force=True)
		for name in frappe.db.get_all("CRM Student", filters={"student_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for name in frappe.db.get_all("CRM Team", filters={"team_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Team", name, force=True)
		for name in frappe.db.get_all("CRM Staff", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Staff", name, force=True)
		for name in frappe.db.get_all(
			"CRM Department", filters={"department_name": ["like", "_Test%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Department", name, force=True)
		for name in frappe.db.get_all("User", filters={"first_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("User", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Campus", name, force=True)

	def _make_contact(self, name, phone, enrollment_status="Có triển vọng"):
		contact = frappe.get_doc({
			"doctype": "CRM Contact",
			"full_name": name,
			"phone": phone,
			"enrollment_status": enrollment_status,
		})
		contact.insert(ignore_permissions=True)
		return contact

	# ------------------------------------------------------- milestone-gated creation

	def test_non_milestone_status_does_not_create_student(self):
		contact = self._make_contact("_Test Non Milestone", "0911111111")
		self.assertFalse(contact.student)
		self.assertFalse(frappe.db.exists("CRM Student", {"phone": "0911111111"}))

	def test_transition_into_milestone_status_creates_linked_student(self):
		contact = self._make_contact("_Test Milestone Transition", "0911111112")
		self.assertFalse(contact.student)

		contact.enrollment_status = "Đã xác nhận"
		contact.save(ignore_permissions=True)
		contact.reload()

		self.assertTrue(contact.student)
		student = frappe.get_doc("CRM Student", contact.student)
		self.assertEqual(student.phone, "0911111112")

	def test_insert_directly_at_milestone_status_creates_linked_student(self):
		contact = self._make_contact("_Test Milestone Insert", "0911111113", enrollment_status="Đã nhập học")
		contact.reload()

		self.assertTrue(contact.student)
		self.assertTrue(frappe.db.exists("CRM Student", {"phone": "0911111113"}))

	def test_milestone_creation_does_not_refire_on_subsequent_saves(self):
		contact = self._make_contact("_Test Milestone Once", "0911111114", enrollment_status="Đã xác nhận")
		contact.reload()
		student_name = contact.student
		self.assertTrue(student_name)

		contact.full_name = "_Test Milestone Once Renamed"
		contact.save(ignore_permissions=True)
		contact.reload()

		self.assertEqual(contact.student, student_name)
		self.assertEqual(frappe.db.count("CRM Student", {"phone": "0911111114"}), 1)

	# --------------------------------------------------------------- owner derivation

	def test_owner_fields_derived_from_assigned_to(self):
		campus = self._make_campus("_Test Contact Owner Campus")
		department = self._make_department("_Test Contact Owner Dept", campus)
		team = self._make_team("_Test Contact Owner Team", campus)
		staff = self._make_staff("_Test Contact Owner Staff", campus, department, team)

		contact = self._make_contact("_Test Owner Derivation", "0911111115")
		contact.assigned_to = staff
		contact.save(ignore_permissions=True)
		contact.reload()

		self.assertEqual(contact.owner_staff, staff)
		self.assertEqual(contact.owning_team, team)

	# ---------------------------------------------------------------------- helpers

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_team(self, name, campus):
		if frappe.db.exists("CRM Team", name):
			frappe.delete_doc("CRM Team", name, force=True)
		team = frappe.get_doc({
			"doctype": "CRM Team",
			"team_name": name,
			"team_type": "Sales",
			"campus": campus,
			"is_active": 1,
		})
		team.insert(ignore_permissions=True)
		return team.name

	def _make_department(self, name, campus):
		if not frappe.db.exists("CRM Department", name):
			frappe.get_doc({
				"doctype": "CRM Department",
				"department_name": name,
				"campus": campus,
			}).insert(ignore_permissions=True)
		return name

	def _make_staff(self, name, campus, department, team):
		email = f"{frappe.scrub(name)}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": name,
			"send_welcome_email": 0,
		})
		user.insert(ignore_permissions=True)

		if frappe.db.exists("CRM Staff", name):
			frappe.delete_doc("CRM Staff", name, force=True)
		staff = frappe.get_doc({
			"doctype": "CRM Staff",
			"full_name": name,
			"user": email,
			"department": department,
			"campus": campus,
		})
		staff.append("team_memberships", {"team": team, "function": "Sale", "term": "", "is_primary": 1})
		staff.insert(ignore_permissions=True)
		return staff.name
