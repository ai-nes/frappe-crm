import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.crm_lead.crm_lead import (
	convert_to_contact,
	create_from_contact,
)
from crm.fcrm.student_context import _admissions_context


class TestCRMLead(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def _make_student(self, name="_Test Convert Student"):
		if frappe.db.exists("CRM Lead", name):
			frappe.delete_doc("CRM Lead", name, force=True)
		student = frappe.get_doc({
			"doctype": "CRM Lead",
			"student_name": name,
			"phone": "0981000001",
			"email": "test.convert@example.com",
			"enrollment_status": "CONFIRMED",
		})
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = False
		return student

	def tearDown(self):
		for name in frappe.db.get_all("CRM Lead", filters={"student_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Lead", name, force=True)
		for name in frappe.db.get_all("CRM Student", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for name in frappe.db.get_all("Contact", filters={"first_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("Contact", name, force=True)
		for name in frappe.db.get_all("CRM Staff", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Staff", name, force=True)
		for name in frappe.db.get_all("CRM Team", filters={"team_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Team", name, force=True)
		for name in frappe.db.get_all(
			"CRM Department", filters={"department_name": ["like", "_Test%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Department", name, force=True)
		for name in frappe.db.get_all("User", filters={"first_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("User", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Campus", name, force=True)

	def test_legacy_convert_endpoint_requires_phase8_command_contract(self):
		student = self._make_student()
		with self.assertRaises(frappe.ValidationError):
			convert_to_contact(student.name)
		student.reload()
		self.assertEqual(student.enrollment_status, "CONFIRMED")

	def test_direct_lead_creation_is_independent(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "_Test Direct Student",
				"phone": "0981000099",
				"enrollment_status": "NEW",
			}
		)

		student.insert(ignore_permissions=True)

		self.assertTrue(student.name)
		self.assertEqual(student.lifecycle_stage, "Lead")
		self.assertFalse(frappe.db.exists("CRM Student", {"phone": "0981000099"}))

	def test_lead_code_is_stable_and_separate_from_student_id(self):
		lead = self._make_student_with_status("_Test Lead Code", "0981000088", "NEW")

		self.assertRegex(lead.lead_code, r"^LD-\d{4}-\d{5,}$")
		self.assertEqual(lead.lead_code, lead.name.replace("ENR-", "LD-", 1))

		lead_name = lead.name
		lead_code = lead.lead_code
		lead.student_name = "_Test Lead Code Updated"
		lead.save(ignore_permissions=True)
		lead.reload()

		self.assertEqual(lead.name, lead_name)
		self.assertEqual(lead.lead_code, lead_code)

		lead.lead_code = "LD-2026-99999"
		with self.assertRaises(frappe.ValidationError):
			lead.save(ignore_permissions=True)

	def test_current_grade_change_advances_student_context_revision(self):
		if not frappe.get_meta("CRM Lead").has_field("current_grade"):
			self.skipTest("CRM Student schema has not been migrated with current_grade")
		student = self._make_student("_Test Grade Context Student")
		initial_revision = int(student.student_context_revision or 0)

		student.current_grade = "11"
		student.save(ignore_permissions=True)
		student.reload()

		self.assertGreater(student.student_context_revision, initial_revision)

	def test_current_grade_is_optional_and_context_visible(self):
		if not frappe.get_meta("CRM Lead").has_field("current_grade"):
			self.skipTest("CRM Student schema has not been migrated with current_grade")
		student = self._make_student("_Test Grade Optional Student")
		self.assertFalse(student.current_grade)

		student.current_grade = "11"
		student.save(ignore_permissions=True)
		context = _admissions_context(student.name, student, {})
		self.assertEqual(context["current_grade"], "11")

		invalid = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "_Test Invalid Grade Student",
				"phone": "0981000022",
				"current_grade": "13",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			invalid.insert(ignore_permissions=True)

	def test_study_stage_must_match_current_grade(self):
		student = self._make_student("_Test Study Stage Student")
		student.current_grade = "12"
		student.study_stage = "grade_12_h1"
		student.save(ignore_permissions=True)
		self.assertEqual(student.study_stage, "grade_12_h1")

		student.study_stage = "grade_11"
		with self.assertRaises(frappe.ValidationError):
			student.save(ignore_permissions=True)

	def test_direct_student_creation_is_independent(self):
		# Test the production path: a Student may be created without an intake
		# Lead and must not synthesize one.
		previous_in_test = getattr(frappe.flags, "in_test", False)
		frappe.flags.in_test = False
		try:
			student = frappe.get_doc(
				{
					"doctype": "CRM Student",
					"full_name": "_Test Direct Student",
					"phone": "0902222333",
				}
			).insert(ignore_permissions=True)
		finally:
			frappe.flags.in_test = previous_in_test

		self.assertFalse(student.student)
		self.assertFalse(frappe.db.exists("CRM Lead", {"phone": "0902222333"}))

	def test_create_from_contact_is_retired(self):
		contact = frappe.get_doc({
			"doctype": "Contact",
			"first_name": "_Test",
			"last_name": "Source Contact",
			"email_id": "test.source@example.com",
			"phone": "0912345678",
		})
		contact.insert(ignore_permissions=True)

		with self.assertRaises(frappe.PermissionError):
			create_from_contact(contact.name)

	# ---------------------------------------------------------------- lifecycle stage

	def test_forward_progression_does_not_require_reason_or_role(self):
		student = self._make_student_with_status("_Test Student Forward", "0941000001", "NEW")
		self.assertEqual(student.lifecycle_stage, "Lead")

		student.enrollment_status = "PROSPECT"
		previous_flag = getattr(frappe.flags, "student_lifecycle_service", False)
		frappe.flags.student_lifecycle_service = True
		try:
			student.save(ignore_permissions=True)  # must not raise
		finally:
			frappe.flags.student_lifecycle_service = previous_flag
		student.reload()
		self.assertEqual(student.lifecycle_stage, "MQL")

	def test_reopen_from_lost_without_role_or_reason_is_blocked(self):
		student = self._make_student_with_status("_Test Student Reopen No Role", "0941000002", "REFUSED")
		self.assertEqual(student.lifecycle_stage, "Lost")

		user, _staff = self._make_user_and_staff("_Test Student Reopen No Role User", roles=["Sale"])
		frappe.set_user(user)
		try:
			student.enrollment_status = "PROSPECT"
			with self.assertRaises(frappe.PermissionError):
				student.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_reopen_from_lost_with_role_but_no_reason_is_blocked(self):
		student = self._make_student_with_status("_Test Student Reopen No Reason", "0941000003", "REFUSED")

		user, _staff = self._make_user_and_staff("_Test Student Reopen No Reason User", roles=["Lead Sale"])
		frappe.set_user(user)
		try:
			student.enrollment_status = "PROSPECT"
			student.status_change_reason = ""
			with self.assertRaises(frappe.ValidationError):
				student.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_reopen_from_lost_with_role_and_reason_succeeds(self):
		student = self._make_student_with_status("_Test Student Reopen Success", "0941000004", "REFUSED")

		user, _staff = self._make_user_and_staff("_Test Student Reopen Success User", roles=["Lead Sale"])
		frappe.set_user(user)
		try:
			student.enrollment_status = "PROSPECT"
			student.status_change_reason = "Phụ huynh xác nhận vẫn quan tâm."
			previous_flag = getattr(frappe.flags, "student_lifecycle_service", False)
			frappe.flags.student_lifecycle_service = True
			try:
				student.save(ignore_permissions=True)
			finally:
				frappe.flags.student_lifecycle_service = previous_flag
		finally:
			frappe.set_user("Administrator")

		student.reload()
		self.assertEqual(student.enrollment_status, "PROSPECT")
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
		frappe.flags.student_ownership_service = True
		try:
			student.save(ignore_permissions=True)
		finally:
			frappe.flags.student_ownership_service = False
		student.reload()
		self.assertEqual(len(student.assignment_log), 1)
		self.assertFalse(student.assignment_log[0].from_staff)
		self.assertEqual(student.assignment_log[0].to_staff, staff_a)

		student.assigned_to = staff_b
		frappe.flags.student_ownership_service = True
		try:
			student.save(ignore_permissions=True)
		finally:
			frappe.flags.student_ownership_service = False
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
		if frappe.db.exists("CRM Lead", name):
			frappe.delete_doc("CRM Lead", name, force=True)
		student = frappe.get_doc({
			"doctype": "CRM Lead",
			"student_name": name,
			"phone": phone,
			"enrollment_status": enrollment_status,
		})
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = False
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

		campus = self._make_campus(f"_Test Campus {prefix}")
		department = self._make_department(f"_Test Dept {prefix}", campus)

		staff_name = f"_Test Staff {prefix}"
		if frappe.db.exists("CRM Staff", staff_name):
			frappe.delete_doc("CRM Staff", staff_name, force=True)
		staff = frappe.get_doc({
			"doctype": "CRM Staff",
			"full_name": staff_name,
			"user": email,
			"department": department,
			"campus": campus,
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
