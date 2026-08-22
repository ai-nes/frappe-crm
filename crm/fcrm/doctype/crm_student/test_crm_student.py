import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.crm_student.crm_student import (
	convert_to_contact,
	create_from_contact,
)


class TestCRMStudent(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def _make_student(self, name="_Test Convert Student"):
		if frappe.db.exists("CRM Student", name):
			frappe.delete_doc("CRM Student", name, force=True)
		student = frappe.get_doc({
			"doctype": "CRM Student",
			"student_name": name,
			"phone": "0901234567",
			"email": "test.convert@example.com",
			"enrollment_status": "Pending Confirmation",
		})
		student.insert(ignore_permissions=True)
		return student

	def tearDown(self):
		for name in frappe.db.get_all("CRM Student", filters={"student_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for name in frappe.db.get_all("CRM Contact", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Contact", name, force=True)
		for name in frappe.db.get_all("Contact", filters={"first_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("Contact", name, force=True)
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

	def test_convert_creates_crm_contact(self):
		student = self._make_student()
		contact_name = convert_to_contact(student.name)

		contact = frappe.get_doc("CRM Contact", contact_name)
		self.assertEqual(contact.full_name, student.student_name)
		self.assertEqual(contact.phone, student.phone)
		self.assertEqual(contact.email, student.email)
		self.assertEqual(contact.student, student.name)
		self.assertEqual(contact.stage, "Interested")

		student.reload()
		self.assertEqual(student.converted, 1)
		self.assertEqual(student.enrollment_status, "Converted")

	def test_convert_double_conversion_returns_existing_contact(self):
		student = self._make_student("_Test Double Convert Student")
		contact_name = convert_to_contact(student.name)

		self.assertEqual(convert_to_contact(student.name), contact_name)

	def test_student_phone_change_no_longer_syncs_to_linked_crm_contact(self):
		# Regression guard for Phase 2 (removal of the continuous two-way sync bug):
		# a Student field change must never silently overwrite its linked Contact.
		student = self._make_student("_Test Student Phone Sync")
		contact_name = convert_to_contact(student.name)
		original_contact_phone = frappe.db.get_value("CRM Contact", contact_name, "phone")

		student.phone = "0907654321"
		student.save(ignore_permissions=True)

		contact = frappe.get_doc("CRM Contact", contact_name)
		self.assertEqual(contact.phone, original_contact_phone)
		self.assertNotEqual(contact.phone, "0907654321")

	def test_crm_contact_phone_change_no_longer_syncs_to_student(self):
		# Regression guard, mirror of the above for the Contact -> Student direction.
		student = self._make_student("_Test Contact Phone Sync")
		contact_name = convert_to_contact(student.name)
		original_student_phone = student.phone

		contact = frappe.get_doc("CRM Contact", contact_name)
		contact.phone = "0902222333"
		contact.save(ignore_permissions=True)

		student.reload()
		self.assertEqual(student.phone, original_student_phone)
		self.assertNotEqual(student.phone, "0902222333")

	def test_create_from_contact_creates_crm_student(self):
		contact = frappe.get_doc({
			"doctype": "Contact",
			"first_name": "_Test",
			"last_name": "Source Contact",
			"email_id": "test.source@example.com",
			"phone": "0912345678",
		})
		contact.insert(ignore_permissions=True)

		student_name = create_from_contact(contact.name)
		student = frappe.get_doc("CRM Student", student_name)

		self.assertEqual(student.student_name, contact.full_name)
		self.assertEqual(student.phone, contact.phone)
		self.assertEqual(student.email, contact.email_id)

	# ---------------------------------------------------------------- lifecycle stage

	def test_forward_progression_does_not_require_reason_or_role(self):
		student = self._make_student_with_status("_Test Student Forward", "0941000001", "Mới")
		self.assertEqual(student.lifecycle_stage, "Lead")

		student.enrollment_status = "Có triển vọng"
		student.save(ignore_permissions=True)  # must not raise
		student.reload()
		self.assertEqual(student.lifecycle_stage, "MQL")

	def test_reopen_from_lost_without_role_or_reason_is_blocked(self):
		student = self._make_student_with_status("_Test Student Reopen No Role", "0941000002", "Từ chối")
		self.assertEqual(student.lifecycle_stage, "Lost")

		user, _staff = self._make_user_and_staff("_Test Student Reopen No Role User", roles=["Sale"])
		frappe.set_user(user)
		try:
			student.enrollment_status = "Có triển vọng"
			with self.assertRaises(frappe.PermissionError):
				student.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_reopen_from_lost_with_role_but_no_reason_is_blocked(self):
		student = self._make_student_with_status("_Test Student Reopen No Reason", "0941000003", "Từ chối")

		user, _staff = self._make_user_and_staff("_Test Student Reopen No Reason User", roles=["Team Leader"])
		frappe.set_user(user)
		try:
			student.enrollment_status = "Có triển vọng"
			student.status_change_reason = ""
			with self.assertRaises(frappe.ValidationError):
				student.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_reopen_from_lost_with_role_and_reason_succeeds(self):
		student = self._make_student_with_status("_Test Student Reopen Success", "0941000004", "Từ chối")

		user, _staff = self._make_user_and_staff("_Test Student Reopen Success User", roles=["Team Leader"])
		frappe.set_user(user)
		try:
			student.enrollment_status = "Có triển vọng"
			student.status_change_reason = "Phụ huynh xác nhận vẫn quan tâm."
			student.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

		student.reload()
		self.assertEqual(student.enrollment_status, "Có triển vọng")
		self.assertEqual(student.lifecycle_stage, "MQL")

	# --------------------------------------------------------------- assignment log

	def test_reassignment_appends_assignment_log_row(self):
		campus = self._make_campus("_Test Student Assign Log Campus")
		department = self._make_department("_Test Student Assign Log Dept", campus)
		team = self._make_team("_Test Student Assign Log Team", campus)
		staff_a = self._make_staff_member("_Test Student Assign Log Staff A", campus, department, team)
		staff_b = self._make_staff_member("_Test Student Assign Log Staff B", campus, department, team)

		student = self._make_student("_Test Student Reassignment")
		student.assigned_to = staff_a
		student.save(ignore_permissions=True)
		student.reload()
		self.assertEqual(len(student.assignment_log), 1)
		self.assertFalse(student.assignment_log[0].from_staff)
		self.assertEqual(student.assignment_log[0].to_staff, staff_a)

		student.assigned_to = staff_b
		student.save(ignore_permissions=True)
		student.reload()

		self.assertEqual(len(student.assignment_log), 2)
		row = student.assignment_log[1]
		self.assertEqual(row.from_staff, staff_a)
		self.assertEqual(row.to_staff, staff_b)
		self.assertEqual(row.changed_by, "Administrator")

	def test_no_assignment_change_does_not_append_log_row(self):
		student = self._make_student("_Test Student No Reassignment")
		student.student_name = "_Test Student No Reassignment Renamed"
		student.save(ignore_permissions=True)
		student.reload()
		self.assertEqual(len(student.assignment_log), 0)

	# ---------------------------------------------------------------------- helpers

	def _make_student_with_status(self, name, phone, enrollment_status):
		if frappe.db.exists("CRM Student", name):
			frappe.delete_doc("CRM Student", name, force=True)
		student = frappe.get_doc({
			"doctype": "CRM Student",
			"student_name": name,
			"phone": phone,
			"enrollment_status": enrollment_status,
		})
		student.insert(ignore_permissions=True)
		return student

	def _make_user_and_staff(self, prefix, roles=None):
		email = f"{frappe.scrub(prefix)}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": prefix,
			"send_welcome_email": 0,
			"roles": [{"role": role} for role in (roles or ["Sale"])],
		})
		user.insert(ignore_permissions=True)

		staff_name = f"_Test Staff {prefix}"
		if frappe.db.exists("CRM Staff", staff_name):
			frappe.delete_doc("CRM Staff", staff_name, force=True)
		staff = frappe.get_doc({
			"doctype": "CRM Staff",
			"full_name": staff_name,
			"user": email,
		})
		staff.insert(ignore_permissions=True)
		return email, staff.name

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_department(self, name, campus):
		if not frappe.db.exists("CRM Department", name):
			frappe.get_doc({
				"doctype": "CRM Department",
				"department_name": name,
				"campus": campus,
			}).insert(ignore_permissions=True)
		return name

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

	def _make_staff_member(self, name, campus, department, team):
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
