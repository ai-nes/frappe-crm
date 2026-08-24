# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Tests for the shared row-level scoping logic in crm/fcrm/permissions.py, exercised
through both CRM Contact.get_permission_query_conditions and
CRM Student.get_permission_query_conditions (see business-rules-data-scope.md for the
locked precedence matrix: Lead Sales > Sale/Marketing > Sale/Sale > deny).
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.capability import get_ai_student, list_ai_students
from crm.fcrm.doctype.crm_contact.crm_contact import (
	get_permission_query_conditions as contact_conditions,
)
from crm.fcrm.doctype.crm_student.crm_student import (
	get_permission_query_conditions as student_conditions,
)
from crm.fcrm.permissions import (
	get_permission_query_conditions as shared_conditions,
)
from crm.fcrm.permissions import (
	has_permission as shared_has_permission,
)


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

	def test_team_leader_condition_scopes_to_team_and_unassigned_pool(self):
		user, staff = self._make_user_and_staff(
			"_Test Scope Leader", roles=["Lead Sales"], team=self._team, function="Lead Sales"
		)
		condition = shared_conditions("CRM Contact", user=user)
		self.assertIsNotNone(condition)
		self.assertIn("owner_staff", condition)
		self.assertIn("owning_team", condition)
		self.assertIn(staff, condition)
		self.assertIn(self._team, condition)

	def test_team_leader_unassigned_pool_matches_real_unassigned_contact(self):
		# Regression test for the bug where owning_team was only ever derived
		# alongside owner_staff, leaving every unassigned record's owning_team null
		# and the "unassigned pool" clause permanently unreachable. Creates a
		# genuinely unassigned CRM Contact as the leader and asserts it is actually
		# returned by a query using the generated condition — not just that the
		# condition string mentions the right column names.
		user, _staff = self._make_user_and_staff(
			"_Test Scope Leader Pool Query", roles=["Lead Sales"], team=self._team, function="Lead Sales"
		)
		frappe.set_user(user)
		try:
			contact = frappe.get_doc(
				{
					"doctype": "CRM Contact",
					"full_name": "_Test Unassigned Pool Contact",
					"phone": "0933000111",
				}
			)
			contact.insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

		try:
			self.assertEqual(contact.owning_team, self._team)
			condition = shared_conditions("CRM Contact", user=user)
			matched = frappe.db.sql(
				f"select name from `tabCRM Contact` where name = %s and ({condition})",
				(contact.name,),
			)
			self.assertTrue(matched, "unassigned contact must be visible via the leader's pool condition")
		finally:
			frappe.delete_doc("CRM Contact", contact.name, force=True)

	def test_team_leader_with_no_team_denied(self):
		user, _staff = self._make_user_and_staff("_Test Scope Leader No Team", roles=["Lead Sales"])
		self.assertEqual(shared_conditions("CRM Contact", user=user), "1=0")

	def test_lead_sales_inherits_team_leader_scope(self):
		user, staff = self._make_user_and_staff(
			"_Test Scope Lead Sales", roles=["Lead Sales"], team=self._team, function="Lead Sales"
		)
		condition = shared_conditions("CRM Contact", user=user)
		self.assertIsNotNone(condition)
		self.assertIn(staff, condition)
		self.assertIn(self._team, condition)

	def test_team_leader_pool_excludes_sibling_team_on_same_campus(self):
		# self._team is the leader's own team, on self._campus. A second, unrelated
		# team on the same campus must never appear in the leader's unassigned pool
		# (constraint 3) — the pool is now an exact owning_team match, so campus is
		# irrelevant to this guarantee.
		sibling_team = self._make_team("_Test Scope Sibling Team", self._campus)
		user, staff = self._make_user_and_staff(
			"_Test Scope Leader Shared Campus",
			roles=["Lead Sales"],
			team=self._team,
			function="Lead Sales",
		)
		condition = shared_conditions("CRM Contact", user=user)
		self.assertIsNotNone(condition)
		self.assertNotIn(frappe.db.escape(sibling_team), condition)
		self.assertIn(staff, condition)
		frappe.delete_doc("CRM Team", sibling_team, force=True)

	def test_team_leader_pool_includes_all_own_teams(self):
		# A leader who belongs to two teams should get both teams' unassigned pools.
		second_campus = self._make_campus("_Test Scope Second Campus")
		second_team = self._make_team("_Test Scope Second Team", second_campus)
		user, staff = self._make_user_and_staff(
			"_Test Scope Leader Two Teams",
			roles=["Lead Sales"],
			team=self._team,
			function="Lead Sales",
		)
		staff_doc = frappe.get_doc("CRM Staff", staff)
		staff_doc.append(
			"team_memberships",
			{"team": second_team, "function": "Lead Sales", "term": "", "is_primary": 0},
		)
		staff_doc.save(ignore_permissions=True)

		condition = shared_conditions("CRM Contact", user=user)
		self.assertIsNotNone(condition)
		self.assertIn("owning_team in", condition)
		self.assertIn(frappe.db.escape(self._team), condition)
		self.assertIn(frappe.db.escape(second_team), condition)

		staff_doc.team_memberships = [
			membership for membership in staff_doc.team_memberships if membership.team != second_team
		]
		staff_doc.save(ignore_permissions=True)
		frappe.delete_doc("CRM Team", second_team, force=True)
		self._cleanup_campus(second_campus)

	def test_sale_is_scoped_to_own_assigned_records(self):
		user, staff = self._make_user_and_staff("_Test Scope Sale", roles=["Sale"])
		condition = shared_conditions("CRM Student", user=user)
		self.assertIsNotNone(condition)
		self.assertEqual(condition, f"`tabCRM Student`.owner_staff = {frappe.db.escape(staff)}")

	def test_marketing_has_no_contact_or_student_scope(self):
		user, _staff = self._make_user_and_staff("_Test Scope Marketing", roles=["Marketing"])
		condition = shared_conditions("CRM Contact", user=user)
		self.assertEqual(condition, "1=0")

	def test_marketing_remains_denied_when_legacy_campus_flag_is_enabled(self):
		user, _staff = self._make_user_and_staff("_Test Scope Marketing Legacy Flag", roles=["Marketing"])
		previous = frappe.conf.get("crm_legacy_campus_scoping")
		frappe.conf["crm_legacy_campus_scoping"] = 1
		try:
			self.assertEqual(shared_conditions("CRM Contact", user=user), "1=0")
			self.assertEqual(shared_conditions("CRM Student", user=user), "1=0")
		finally:
			if previous is None:
				frappe.conf.pop("crm_legacy_campus_scoping", None)
			else:
				frappe.conf["crm_legacy_campus_scoping"] = previous

	def test_sale_scoped_to_own_assigned_only(self):
		user, staff = self._make_user_and_staff("_Test Scope Sale", roles=["Sale"])
		condition = shared_conditions("CRM Contact", user=user)
		self.assertEqual(condition, f"`tabCRM Contact`.owner_staff = {frappe.db.escape(staff)}")

	def test_ctv_sale_scoped_to_own_assigned_only(self):
		user, staff = self._make_user_and_staff("_Test Scope CTV Sale", roles=["Sale"])
		condition = shared_conditions("CRM Student", user=user)
		self.assertEqual(condition, f"`tabCRM Student`.owner_staff = {frappe.db.escape(staff)}")

	def test_lead_sales_scope_wins_over_sale_if_assignment_is_mixed(self):
		# A staff member holding both Lead Sales and Sale roles must get the broader
		# Lead Sales scope, not the narrower Sale (own-assigned-only) scope.
		user, staff = self._make_user_and_staff(
			"_Test Scope Precedence",
			roles=["Lead Sales", "Sale"],
			team=self._team,
			function="Lead Sales",
		)
		condition = shared_conditions("CRM Contact", user=user)
		self.assertNotEqual(condition, f"`tabCRM Contact`.owner_staff = {frappe.db.escape(staff)}")

	def test_unrecognized_role_denied(self):
		user, _staff = self._make_user_and_staff("_Test Scope Unknown Role", roles=["Website Manager"])
		self.assertEqual(shared_conditions("CRM Contact", user=user), "1=0")

	# ----------------------------------------------------- doctype delegation wiring

	def test_crm_contact_delegates_to_shared_module(self):
		user, _staff = self._make_user_and_staff("_Test Scope Delegate Contact", roles=["Sale"])
		self.assertEqual(contact_conditions(user=user), shared_conditions("CRM Contact", user=user))

	def test_crm_student_delegates_to_shared_module(self):
		user, _staff = self._make_user_and_staff("_Test Scope Delegate Student", roles=["Sale"])
		self.assertEqual(student_conditions(user=user), shared_conditions("CRM Student", user=user))

	def test_student_direct_record_scope_uses_derived_owner_fields(self):
		user, staff = self._make_user_and_staff("_Test Scope Student Direct", roles=["Sale"])
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": "_Test Direct Scoped Student",
				"phone": "0933998877",
				"assigned_to": staff,
			}
		)
		student.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("CRM Student", student.name, force=True)
			if frappe.db.exists("CRM Student", student.name)
			else None
		)
		self.assertEqual(student.owner_staff, staff)
		self.assertTrue(shared_has_permission(student, user=user))

		foreign_user, _foreign_staff = self._make_user_and_staff(
			"_Test Scope Student Foreign", roles=["Sale"]
		)
		self.assertFalse(shared_has_permission(student, user=foreign_user))
	def test_student_dto_endpoints_enforce_self_foreign_list_and_write_scope(self):
		"""Exercise the whitelisted Student DTO path against the real test site.

		The endpoint must use the same server-owned scope hooks as raw delegated
		reads: the owner can list/read/write its Student; another Sales user sees
		neither the record in a list nor its direct-by-name DTO and cannot write it.
		"""
		owner_user, owner_staff = self._make_user_and_staff(
			"_Test DTO Owner", roles=["Sale"], team=self._team
		)
		team_user, _team_staff = self._make_user_and_staff(
			"_Test DTO Team", roles=["Lead Sales"], team=self._team, function="Lead Sales"
		)
		foreign_user, _foreign_staff = self._make_user_and_staff("_Test DTO Foreign", roles=["Sale"])
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": "_Test DTO Scoped Student",
				"phone": "0933998878",
				"assigned_to": owner_staff,
				"branch": self._campus,
			}
		)
		student.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("CRM Student", student.name, force=True)
			if frappe.db.exists("CRM Student", student.name)
			else None
		)

		try:
			with patch("crm.api.capability._student_ai_exposure_enabled", return_value=True):
				# Frappe caches User permission maps; these identities were created in
				# this test, so evict any pre-creation negative cache before exercising
				# the real list/report permission path.
				frappe.clear_cache(user=owner_user)
				frappe.clear_cache(user=team_user)
				frappe.clear_cache(user=foreign_user)
				frappe.set_user(owner_user)
				self.assertEqual(get_ai_student(student.name)["name"], student.name)
				self.assertIn(
					student.name,
					[row["name"] for row in list_ai_students(limit=50)["records"]],
				)
				self.assertTrue(frappe.has_permission("CRM Student", ptype="write", doc=student, user=owner_user))

				frappe.set_user(team_user)
				self.assertEqual(get_ai_student(student.name)["name"], student.name)
				self.assertIn(
					student.name,
					[row["name"] for row in list_ai_students(limit=50)["records"]],
				)
				self.assertTrue(frappe.has_permission("CRM Student", ptype="write", doc=student, user=team_user))

				frappe.set_user(foreign_user)
				with self.assertRaises(frappe.PermissionError):
					get_ai_student(student.name)
				self.assertNotIn(
					student.name,
					[row["name"] for row in list_ai_students(limit=50)["records"]],
				)
				self.assertFalse(frappe.has_permission("CRM Student", ptype="write", doc=student, user=foreign_user))
		finally:
			frappe.set_user("Administrator")

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
				"user_type": "System User",
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
