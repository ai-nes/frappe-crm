# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Tests for the shared row-level scoping logic in crm/fcrm/permissions.py, exercised
through both CRM Contact.get_permission_query_conditions and
CRM Student.get_permission_query_conditions (see business-rules-data-scope.md for the
locked precedence matrix: Team Leader > Counseller/Promoter-PR > Sale/CTV-Sale > deny).
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.crm_contact.crm_contact import (
	get_permission_query_conditions as contact_conditions,
)
from crm.fcrm.doctype.crm_student.crm_student import (
	get_permission_query_conditions as student_conditions,
)
from crm.fcrm.permissions import get_permission_query_conditions as shared_conditions


class TestSharedScopingPermissions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = self._make_campus("_Test Scope Campus")
		self._other_campus = self._make_campus("_Test Scope Other Campus")
		self._department = self._get_or_create_department("_Test Scope Dept", self._campus)
		self._team = self._make_team("_Test Scope Team", self._campus)

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
		self._cleanup_campus(self._other_campus)

	# --------------------------------------------------------------- full visibility

	def test_full_visibility_role_returns_none(self):
		user, _staff = self._make_user_and_staff("_Test Scope Admin", roles=["System Manager"])
		self.assertIsNone(shared_conditions("CRM Contact", user=user))
		self.assertIsNone(shared_conditions("CRM Student", user=user))

	def test_admissions_director_has_full_visibility(self):
		user, _staff = self._make_user_and_staff("_Test Scope Director", roles=["Admissions Director"])
		self.assertIsNone(shared_conditions("CRM Contact", user=user))

	# --------------------------------------------------------------------- no staff

	def test_user_without_crm_staff_denied(self):
		# A user with a CRM role but no linked CRM Staff record has no scope to apply.
		if frappe.db.exists("User", "_test_no_staff_scope@example.com"):
			frappe.delete_doc("User", "_test_no_staff_scope@example.com", force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "_test_no_staff_scope@example.com",
				"first_name": "_Test",
				"send_welcome_email": 0,
				"roles": [{"role": "Sale"}],
			}
		)
		user.insert(ignore_permissions=True)
		try:
			self.assertEqual(shared_conditions("CRM Contact", user=user.name), "1=0")
		finally:
			frappe.delete_doc("User", user.name, force=True)

	# ------------------------------------------------------------------- role precedence

	def test_team_leader_condition_scopes_to_team_and_campus_pool(self):
		user, staff = self._make_user_and_staff(
			"_Test Scope Leader", roles=["Team Leader"], team=self._team, function="Team Leader"
		)
		condition = shared_conditions("CRM Contact", user=user)
		self.assertIsNotNone(condition)
		self.assertIn("assigned_to", condition)
		self.assertIn(staff, condition)

	def test_team_leader_with_no_team_denied(self):
		user, _staff = self._make_user_and_staff("_Test Scope Leader No Team", roles=["Team Leader"])
		self.assertEqual(shared_conditions("CRM Contact", user=user), "1=0")

	def test_team_leader_pool_excludes_campus_shared_with_other_team(self):
		# self._team is the leader's own team, on self._campus. Adding a second,
		# unrelated team on the same campus must drop that campus from the
		# unassigned pool entirely (constraint 3: never leak a sibling team's
		# unassigned records via a shared campus).
		sibling_team = self._make_team("_Test Scope Sibling Team", self._campus)
		user, staff = self._make_user_and_staff(
			"_Test Scope Leader Shared Campus",
			roles=["Team Leader"],
			team=self._team,
			function="Team Leader",
		)
		condition = shared_conditions("CRM Contact", user=user)
		self.assertIsNotNone(condition)
		self.assertNotIn("branch", condition)
		self.assertIn(staff, condition)
		frappe.delete_doc("CRM Team", sibling_team, force=True)

	def test_team_leader_pool_includes_multiple_exclusive_campuses(self):
		# A leader who belongs to two teams on two different campuses that are
		# each exclusively theirs should get both campuses' unassigned pools.
		second_campus = self._make_campus("_Test Scope Second Campus")
		second_team = self._make_team("_Test Scope Second Team", second_campus)
		user, staff = self._make_user_and_staff(
			"_Test Scope Leader Two Teams",
			roles=["Team Leader"],
			team=self._team,
			function="Team Leader",
		)
		staff_doc = frappe.get_doc("CRM Staff", staff)
		staff_doc.append(
			"team_memberships",
			{"team": second_team, "function": "Team Leader", "term": "", "is_primary": 0},
		)
		staff_doc.save(ignore_permissions=True)

		condition = shared_conditions("CRM Contact", user=user)
		self.assertIsNotNone(condition)
		self.assertIn("branch in", condition)
		self.assertIn(frappe.db.escape(self._campus), condition)
		self.assertIn(frappe.db.escape(second_campus), condition)

		frappe.delete_doc("CRM Team", second_team, force=True)
		self._cleanup_campus(second_campus)

	def test_counseller_scoped_to_campus(self):
		user, staff = self._make_user_and_staff("_Test Scope Counseller", roles=["Counseller"])
		condition = shared_conditions("CRM Student", user=user)
		self.assertIsNotNone(condition)
		self.assertIn("assigned_to in", condition)
		self.assertIn(staff, condition)

	def test_promoter_pr_scoped_to_campus_same_as_counseller(self):
		user, staff = self._make_user_and_staff("_Test Scope Promoter", roles=["Promoter-PR"])
		condition = shared_conditions("CRM Contact", user=user)
		self.assertIn(staff, condition)

	def test_sale_scoped_to_own_assigned_only(self):
		user, staff = self._make_user_and_staff("_Test Scope Sale", roles=["Sale"])
		condition = shared_conditions("CRM Contact", user=user)
		self.assertEqual(condition, f"`tabCRM Contact`.assigned_to = {frappe.db.escape(staff)}")

	def test_ctv_sale_scoped_to_own_assigned_only(self):
		user, staff = self._make_user_and_staff("_Test Scope CTV Sale", roles=["CTV-Sale"])
		condition = shared_conditions("CRM Student", user=user)
		self.assertEqual(condition, f"`tabCRM Student`.assigned_to = {frappe.db.escape(staff)}")

	def test_role_precedence_team_leader_wins_over_sale(self):
		# A staff member holding both Team Leader and Sale roles must get the broader
		# Team Leader scope, not the narrower Sale (own-assigned-only) scope.
		user, staff = self._make_user_and_staff(
			"_Test Scope Precedence",
			roles=["Team Leader", "Sale"],
			team=self._team,
			function="Team Leader",
		)
		condition = shared_conditions("CRM Contact", user=user)
		self.assertNotEqual(condition, f"`tabCRM Contact`.assigned_to = {frappe.db.escape(staff)}")

	def test_unrecognized_role_denied(self):
		user, _staff = self._make_user_and_staff("_Test Scope Unknown Role", roles=["Marketing Operator"])
		self.assertEqual(shared_conditions("CRM Contact", user=user), "1=0")

	# ----------------------------------------------------- doctype delegation wiring

	def test_crm_contact_delegates_to_shared_module(self):
		user, _staff = self._make_user_and_staff("_Test Scope Delegate Contact", roles=["Sale"])
		self.assertEqual(contact_conditions(user=user), shared_conditions("CRM Contact", user=user))

	def test_crm_student_delegates_to_shared_module(self):
		user, _staff = self._make_user_and_staff("_Test Scope Delegate Student", roles=["Sale"])
		self.assertEqual(student_conditions(user=user), shared_conditions("CRM Student", user=user))

	# ---------------------------------------------------------------------- helpers

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _cleanup_campus(self, campus):
		if campus and frappe.db.exists("CRM Campus", campus):
			frappe.delete_doc("CRM Campus", campus, force=True)

	def _get_or_create_department(self, name, campus):
		if not frappe.db.exists("CRM Department", name):
			frappe.get_doc(
				{
					"doctype": "CRM Department",
					"department_name": name,
					"campus": campus,
				}
			).insert(ignore_permissions=True)
		return name

	def _make_team(self, name, campus):
		if frappe.db.exists("CRM Team", name):
			frappe.delete_doc("CRM Team", name, force=True)
		team = frappe.get_doc(
			{
				"doctype": "CRM Team",
				"team_name": name,
				"team_type": "Sales",
				"campus": campus,
				"is_active": 1,
			}
		)
		team.insert(ignore_permissions=True)
		return team.name

	def _make_user_and_staff(self, prefix, roles=None, team=None, function=None):
		email = f"{frappe.scrub(prefix)}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": prefix,
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in (roles or ["Sale"])],
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
				"department": self._department,
				"campus": self._campus,
			}
		)
		if team:
			staff.append(
				"team_memberships",
				{
					"team": team,
					"function": function or "Sale",
					"term": "",
					"is_primary": 1,
				},
			)
		staff.insert(ignore_permissions=True)
		return email, staff.name
