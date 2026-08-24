import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMContact(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		test_contact_names = frappe.db.get_all(
			"CRM Contact", filters={"full_name": ["like", "_Test%"]}, pluck="name"
		)
		if test_contact_names:
			for name in frappe.db.get_all(
				"CRM Interaction", filters={"crm_contact": ["in", test_contact_names]}, pluck="name"
			):
				frappe.delete_doc("CRM Interaction", name, force=True)
		for name in test_contact_names:
			frappe.delete_doc("CRM Contact", name, force=True)
		for name in frappe.db.get_all("CRM Student", filters={"student_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
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

	def test_transition_into_milestone_status_does_not_create_student(self):
		contact = self._make_contact("_Test Milestone Transition", "0911111112")
		self.assertFalse(contact.student)

		contact.enrollment_status = "Đã xác nhận"
		contact.save(ignore_permissions=True)
		contact.reload()

		self.assertFalse(contact.student)
		self.assertFalse(frappe.db.exists("CRM Student", {"phone": "0911111112"}))

	def test_insert_directly_at_milestone_status_does_not_create_student(self):
		contact = self._make_contact("_Test Milestone Insert", "0911111113", enrollment_status="Đã nhập học")
		contact.reload()

		self.assertFalse(contact.student)
		self.assertFalse(frappe.db.exists("CRM Student", {"phone": "0911111113"}))

	def test_retired_milestone_writer_does_not_refire_on_subsequent_saves(self):
		contact = self._make_contact("_Test Milestone Once", "0911111114", enrollment_status="Đã xác nhận")
		contact.reload()
		student_name = contact.student
		self.assertFalse(student_name)

		contact.full_name = "_Test Milestone Once Renamed"
		contact.save(ignore_permissions=True)
		contact.reload()

		self.assertEqual(contact.student, student_name)
		self.assertEqual(frappe.db.count("CRM Student", {"phone": "0911111114"}), 0)

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

	# ---------------------------------------------------------------- lifecycle stage

	def test_forward_progression_does_not_require_reason_or_role(self):
		# Lead(Mới) -> MQL(Có triển vọng) is forward-only; no override role or
		# status_change_reason should be required.
		contact = self._make_contact("_Test Forward Progress", "0933000001", enrollment_status="Mới")
		self.assertEqual(contact.lifecycle_stage, "Lead")

		contact.enrollment_status = "Có triển vọng"
		contact.save(ignore_permissions=True)  # must not raise
		contact.reload()
		self.assertEqual(contact.lifecycle_stage, "MQL")

	def test_reopen_from_lost_without_role_or_reason_is_blocked(self):
		contact = self._make_contact("_Test Reopen No Role", "0933000002", enrollment_status="Từ chối")
		self.assertEqual(contact.lifecycle_stage, "Lost")

		user, _staff = self._make_user_and_staff("_Test Reopen No Role User", roles=["Sale"])
		frappe.set_user(user)
		try:
			contact.enrollment_status = "Có triển vọng"
			with self.assertRaises(frappe.PermissionError):
				contact.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_reopen_from_lost_with_role_but_no_reason_is_blocked(self):
		contact = self._make_contact("_Test Reopen No Reason", "0933000003", enrollment_status="Từ chối")

		user, _staff = self._make_user_and_staff("_Test Reopen No Reason User", roles=["Team Leader"])
		frappe.set_user(user)
		try:
			contact.enrollment_status = "Có triển vọng"
			contact.status_change_reason = ""
			with self.assertRaises(frappe.ValidationError):
				contact.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_reopen_from_lost_with_role_and_reason_succeeds(self):
		contact = self._make_contact("_Test Reopen Success", "0933000004", enrollment_status="Từ chối")

		user, _staff = self._make_user_and_staff("_Test Reopen Success User", roles=["Team Leader"])
		frappe.set_user(user)
		try:
			contact.enrollment_status = "Có triển vọng"
			contact.status_change_reason = "Khách hàng liên hệ lại, xác nhận vẫn quan tâm."
			contact.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

		contact.reload()
		self.assertEqual(contact.enrollment_status, "Có triển vọng")
		self.assertEqual(contact.lifecycle_stage, "MQL")

	def test_backward_move_within_main_track_is_gated_same_as_reopen(self):
		# Applicant(Đã xác nhận) -> MQL(Có triển vọng) is a backward move on
		# the main track (not a Lost reopen) and must be gated the same way.
		contact = self._make_contact("_Test Backward Move", "0933000005", enrollment_status="Đã xác nhận")
		self.assertEqual(contact.lifecycle_stage, "Applicant")

		contact.enrollment_status = "Có triển vọng"
		user, _staff = self._make_user_and_staff("_Test Backward Move User", roles=["Sale"])
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				contact.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	# --------------------------------------------------------------- assignment log

	def test_reassignment_appends_assignment_log_row(self):
		campus = self._make_campus("_Test Assign Log Campus")
		department = self._make_department("_Test Assign Log Dept", campus)
		team = self._make_team("_Test Assign Log Team", campus)
		staff_a = self._make_staff("_Test Assign Log Staff A", campus, department, team)
		staff_b = self._make_staff("_Test Assign Log Staff B", campus, department, team)

		contact = self._make_contact("_Test Reassignment", "0933000006")
		contact.assigned_to = staff_a
		contact.save(ignore_permissions=True)
		contact.reload()
		self.assertEqual(len(contact.assignment_log), 1)
		self.assertFalse(contact.assignment_log[0].from_staff)
		self.assertEqual(contact.assignment_log[0].to_staff, staff_a)

		contact.assigned_to = staff_b
		contact.save(ignore_permissions=True)
		contact.reload()

		self.assertEqual(len(contact.assignment_log), 2)
		row = contact.assignment_log[1]
		self.assertEqual(row.from_staff, staff_a)
		self.assertEqual(row.to_staff, staff_b)
		self.assertEqual(row.changed_by, "Administrator")

	def test_no_assignment_change_does_not_append_log_row(self):
		contact = self._make_contact("_Test No Reassignment", "0933000007")
		contact.full_name = "_Test No Reassignment Renamed"
		contact.save(ignore_permissions=True)
		contact.reload()
		self.assertEqual(len(contact.assignment_log), 0)

	# ------------------------------------------------------- CRM Interaction dispatch
	# (Phase 4: crm.fcrm.interaction_log.create_interaction_from_contact_update)

	def test_lifecycle_stage_change_creates_single_stage_changed_interaction(self):
		self._ensure_interaction_type("Stage Changed")

		contact = self._make_contact("_Test Stage Interaction", "0933100001", enrollment_status="Mới")
		self.assertEqual(contact.lifecycle_stage, "Lead")

		contact.enrollment_status = "Có triển vọng"
		contact.save(ignore_permissions=True)
		contact.reload()
		self.assertEqual(contact.lifecycle_stage, "MQL")

		interactions = self._stage_changed_interactions(contact.name)
		self.assertEqual(len(interactions), 1)

		# Duplicate guard: saving again with no further lifecycle_stage change
		# must not create a second Stage Changed interaction.
		contact.full_name = "_Test Stage Interaction Renamed"
		contact.save(ignore_permissions=True)
		contact.reload()
		self.assertEqual(len(self._stage_changed_interactions(contact.name)), 1)

	def test_assignment_change_creates_lead_assigned_then_lead_reassigned_interactions(self):
		self._ensure_interaction_type("Lead Assigned")
		self._ensure_interaction_type("Lead Reassigned")

		campus = self._make_campus("_Test Interaction Assign Campus")
		department = self._make_department("_Test Interaction Assign Dept", campus)
		team = self._make_team("_Test Interaction Assign Team", campus)
		staff_a = self._make_staff("_Test Interaction Assign Staff A", campus, department, team)
		staff_b = self._make_staff("_Test Interaction Assign Staff B", campus, department, team)

		contact = self._make_contact("_Test Assignment Interaction", "0933100002")

		contact.assigned_to = staff_a
		contact.save(ignore_permissions=True)
		contact.reload()
		self.assertEqual(self._interaction_count(contact.name, "Lead Assigned"), 1)
		self.assertEqual(self._interaction_count(contact.name, "Lead Reassigned"), 0)

		contact.assigned_to = staff_b
		contact.save(ignore_permissions=True)
		contact.reload()
		self.assertEqual(self._interaction_count(contact.name, "Lead Assigned"), 1)
		self.assertEqual(self._interaction_count(contact.name, "Lead Reassigned"), 1)

	# ---------------------------------------------------------------------- helpers

	def _ensure_interaction_type(self, name):
		# Same production CRM Interaction Type names the seed_crm_interaction_types
		# patch installs; not _Test-prefixed and intentionally left in place
		# across tests (create_interaction() no-ops if the type is missing).
		if not frappe.db.exists("CRM Interaction Type", name):
			frappe.get_doc({
				"doctype": "CRM Interaction Type",
				"interaction_type_name": name,
			}).insert(ignore_permissions=True)

	def _stage_changed_interactions(self, contact_name):
		return frappe.db.get_all(
			"CRM Interaction",
			filters={"crm_contact": contact_name, "interaction_type": "Stage Changed"},
			pluck="name",
		)

	def _interaction_count(self, contact_name, interaction_type):
		return frappe.db.count(
			"CRM Interaction", {"crm_contact": contact_name, "interaction_type": interaction_type}
		)

	def _make_user_and_staff(self, prefix, roles=None):
		campus = self._make_campus(f"{prefix} Campus")
		department = self._make_department(f"{prefix} Dept", campus)
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
			"department": department,
			"campus": campus,
		})
		staff.insert(ignore_permissions=True)
		return email, staff.name

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
