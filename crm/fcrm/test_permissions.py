# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Tests for the shared row-level scoping logic in crm/fcrm/permissions.py, exercised
through both CRM Student.get_permission_query_conditions and
CRM Lead.get_permission_query_conditions (see business-rules-data-scope.md for the
locked precedence matrix: Lead Sale > Sale > Marketing/deny).
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.crm_lead.crm_lead import (
	get_permission_query_conditions as student_conditions,
)
from crm.fcrm.doctype.crm_student.crm_student import (
	get_permission_query_conditions as contact_conditions,
)
from crm.fcrm.permissions import (
	can_read_full_lead_board,
	get_student_list_read_condition,
)
from crm.fcrm.permissions import (
	get_permission_query_conditions as shared_conditions,
)
from crm.fcrm.permissions import (
	has_permission as shared_has_permission,
)
from crm.fcrm.role_policy import PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY


class TestSharedScopingPermissions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# This module verifies the canonical owner/team scope matrix. Keep the
		# optional converted-Contact compatibility projection disabled so the
		# assertions do not depend on demo-site rollout configuration.
		self._conversion_read_flag = "crm_student_conversion_read_enabled"
		self._previous_conversion_read = frappe.conf.get(self._conversion_read_flag)
		frappe.conf[self._conversion_read_flag] = False
		self._campus = self._make_campus("_Test Scope Campus")
		self._other_campus = self._make_campus("_Test Scope Other Campus")
		self._department = self._get_or_create_department("_Test Scope Dept", self._campus)
		self._team = self._make_team("_Test Scope Team", self._campus)

	def tearDown(self):
		if self._previous_conversion_read is None:
			frappe.conf.pop(self._conversion_read_flag, None)
		else:
			frappe.conf[self._conversion_read_flag] = self._previous_conversion_read
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
		self.assertIsNone(shared_conditions("CRM Student", user=user))
		self.assertIsNone(shared_conditions("CRM Lead", user=user))

	def test_admissions_director_has_full_visibility(self):
		user, _staff = self._make_user_and_staff("_Test Scope Director", roles=["Admissions Director"])
		self.assertIsNone(shared_conditions("CRM Student", user=user))

	def test_canonical_sales_and_lead_sales_use_policy_scopes(self):
		sales_user, sales_staff = self._make_user_and_staff("_Test Scope Sale", roles=["Sale"])
		lead_user, lead_staff = self._make_user_and_staff(
			"_Test Scope Lead Sale", roles=["Lead Sale"], team=self._team, function="Lead Sale"
		)
		self.assertEqual(
			shared_conditions("CRM Student", user=sales_user),
			f"`tabCRM Student`.owner_staff = {frappe.db.escape(sales_staff)}",
		)
		self.assertIn(lead_staff, shared_conditions("CRM Student", user=lead_user))

	def test_conversion_read_does_not_hide_standalone_students(self):
		frappe.conf[self._conversion_read_flag] = True
		user, staff = self._make_user_and_staff("_Test Scope Standalone Student", roles=["Sale"])
		self.assertEqual(
			shared_conditions("CRM Student", user=user),
			f"`tabCRM Student`.owner_staff = {frappe.db.escape(staff)}",
		)

	def test_sale_student_list_scope_includes_team_pool_without_widening_crud_scope(self):
		user, staff = self._make_user_and_staff(
			"_Test Scope Sale List", roles=["Sale"], team=self._team, function="Sale"
		)

		list_condition = get_student_list_read_condition(user=user)

		self.assertIn("owning_team", list_condition)
		self.assertIn(staff, list_condition)
		self.assertEqual(
			shared_conditions("CRM Lead", user=user),
			f"`tabCRM Lead`.owner_staff = {frappe.db.escape(staff)}",
		)
		lead_list_condition = get_student_list_read_condition(user=user, doctype="CRM Lead")
		self.assertIn("`tabCRM Lead`.owner_staff", lead_list_condition)
		self.assertNotIn("`tabCRM Student`", lead_list_condition)

	def test_lead_sale_group_leader_reads_managed_group_students(self):
		user, staff = self._make_user_and_staff(
			"_Test Scope Group Leader", roles=["Lead Sale"], function="Lead Sale"
		)
		province = frappe.get_doc(
			{
				"doctype": "CRM Province",
				"province_name": "_Test Scope Group Province",
				"province_code": "_TEST_SCOPE_GROUP",
				"city_type": "Province",
			}
		)
		province.insert(ignore_permissions=True)
		group = frappe.get_doc(
			{
				"doctype": "CRM Team Group",
				"group_name": "_Test Scope Group Leader Group",
				"province": province.name,
				"group_lead_staff": staff,
				"is_active": 1,
			}
		)
		group.insert(ignore_permissions=True)
		team = frappe.get_doc("CRM Team", self._team)
		team.group = group.name
		team.save(ignore_permissions=True)

		try:
			condition = get_student_list_read_condition(user=user)
			self.assertIn(frappe.db.escape(team.name), condition)
			self.assertIn("owner_staff is not null", condition)
			self.assertIn("assigned_to is not null", condition)
			self.assertIn("owner_staff is null", condition)
			self.assertIn("assigned_to is null", condition)

			lead_condition = get_student_list_read_condition(user=user, doctype="CRM Lead")
			self.assertIn(frappe.db.escape(province.name), lead_condition)
			self.assertIn("owner_staff is null", lead_condition)
			self.assertIn("assigned_to is null", lead_condition)
			# The canonical CRUD scope remains unchanged because this user has no
			# child Team Membership row.
			self.assertEqual(shared_conditions("CRM Student", user=user), "1=0")
		finally:
			team.group = None
			team.save(ignore_permissions=True)
			frappe.delete_doc("CRM Team Group", group.name, force=True)
			frappe.delete_doc("CRM Province", province.name, force=True)

	def test_lead_board_full_access_is_separate_from_group_team_list_scope(self):
		"""Full-board compatibility is retained for detail/write checks only."""
		lead_user, lead_staff = self._make_user_and_staff(
			"_Test Scope Lead Board", roles=["Lead Sale"], team=self._team, function="Lead Sale"
		)
		sale_user, sale_staff = self._make_user_and_staff("_Test Scope Board Sale", roles=["Sale"])

		self.assertTrue(can_read_full_lead_board(user=lead_user))
		self.assertFalse(can_read_full_lead_board(user=sale_user))
		self.assertFalse(can_read_full_lead_board(user="Administrator"))
		self.assertIn(lead_staff, shared_conditions("CRM Lead", user=lead_user))
		self.assertEqual(
			shared_conditions("CRM Lead", user=sale_user),
			f"`tabCRM Lead`.owner_staff = {frappe.db.escape(sale_staff)}",
		)

	def test_lead_sale_can_update_any_lead_on_the_full_intake_board(self):
		user, staff = self._make_user_and_staff(
			"_Test Scope Lead Board Editor", roles=["Lead Sale"], team=self._team, function="Lead Sale"
		)
		lead = frappe._dict(doctype="CRM Lead", name="_Test Lead Outside Own Team", owner_staff="OTHER-STAFF")

		self.assertTrue(shared_has_permission(lead, user=user, ptype="write"))
		self.assertTrue(can_read_full_lead_board(user=user))
		self.assertIn(staff, shared_conditions("CRM Lead", user=user))

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
			self.assertEqual(shared_conditions("CRM Student", user=user.name), "1=0")
		finally:
			frappe.delete_doc("User", user.name, force=True)

	def test_explicit_administrator_role_is_the_ceo_profile(self):
		user, _staff = self._make_user_and_staff("_Test Scope Admin Role", roles=["Administrator"])
		self.assertIsNone(shared_conditions("CRM Student", user=user))

	def test_system_manager_direct_access_does_not_require_a_staff_record(self):
		user = self._make_user_without_staff("_test_system_manager_no_staff@example.com", ["System Manager"])
		self.assertTrue(
			shared_has_permission(frappe._dict(doctype="CRM Student", name="not-queried"), user=user)
		)

	def test_new_document_create_uses_ptype_without_running_name_scope_sql(self):
		# Frappe invokes hooks with ``ptype``. An unsaved document has no name,
		# therefore the row predicate must not be queried with ``name = None``.
		with patch("crm.fcrm.permissions.frappe.db.sql") as sql:
			allowed = shared_has_permission(
				frappe._dict(doctype="CRM Lead", name=None), user="sale@example.com", ptype="create"
			)
		self.assertTrue(allowed)
		sql.assert_not_called()

	# ------------------------------------------------------------------- role precedence

	def test_team_leader_condition_scopes_to_team_and_unassigned_pool(self):
		user, staff = self._make_user_and_staff(
			"_Test Scope Leader", roles=["Lead Sale"], team=self._team, function="Lead Sale"
		)
		condition = shared_conditions("CRM Student", user=user)
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
			"_Test Scope Leader Pool Query", roles=["Lead Sale"], team=self._team, function="Lead Sale"
		)
		frappe.set_user(user)
		try:
			contact = frappe.get_doc(
				{
					"doctype": "CRM Student",
					"full_name": "_Test Unassigned Pool Contact",
					"phone": "0933000111",
				}
			)
			contact.insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

		try:
			self.assertEqual(contact.owning_team, self._team)
			condition = shared_conditions("CRM Student", user=user)
			matched = frappe.db.sql(
				f"select name from `tabCRM Student` where name = %s and ({condition})",
				(contact.name,),
			)
			self.assertTrue(matched, "unassigned contact must be visible via the leader's pool condition")
		finally:
			frappe.delete_doc("CRM Student", contact.name, force=True)

	def test_team_leader_with_no_team_denied(self):
		user, _staff = self._make_user_and_staff("_Test Scope Leader No Team", roles=["Lead Sale"])
		self.assertEqual(shared_conditions("CRM Student", user=user), "1=0")

	def test_team_leader_pool_excludes_sibling_team_on_same_campus(self):
		# self._team is the leader's own team, on self._campus. A second, unrelated
		# team on the same campus must never appear in the leader's unassigned pool
		# (constraint 3) — the pool is now an exact owning_team match, so campus is
		# irrelevant to this guarantee.
		sibling_team = self._make_team("_Test Scope Sibling Team", self._campus)
		user, staff = self._make_user_and_staff(
			"_Test Scope Leader Shared Campus",
			roles=["Lead Sale"],
			team=self._team,
			function="Lead Sale",
		)
		condition = shared_conditions("CRM Student", user=user)
		self.assertIsNotNone(condition)
		self.assertNotIn(frappe.db.escape(sibling_team), condition)
		self.assertIn(staff, condition)
		frappe.delete_doc("CRM Team", sibling_team, force=True)

	def test_team_leader_pool_excludes_own_team_membership_from_another_campus(self):
		# A lead may have stale or transitional membership in another Campus, but
		# Phase 2 scope is Team within the Staff member's current Campus.
		second_campus = self._make_campus("_Test Scope Second Campus")
		second_team = self._make_team("_Test Scope Second Team", second_campus)
		user, staff = self._make_user_and_staff(
			"_Test Scope Leader Two Teams",
			roles=["Lead Sale"],
			team=self._team,
			function="Lead Sale",
		)
		staff_doc = frappe.get_doc("CRM Staff", staff)
		staff_doc.append(
			"team_memberships",
			{"team": second_team, "function": "Lead Sale", "term": "", "is_primary": 0},
		)
		staff_doc.save(ignore_permissions=True)

		condition = shared_conditions("CRM Student", user=user)
		self.assertIsNotNone(condition)
		self.assertIn("owning_team in", condition)
		self.assertIn(frappe.db.escape(self._team), condition)
		self.assertNotIn(frappe.db.escape(second_team), condition)

		staff_doc.reload()
		staff_doc.team_memberships = [row for row in staff_doc.team_memberships if row.team != second_team]
		staff_doc.save(ignore_permissions=True)
		frappe.delete_doc("CRM Team", second_team, force=True)
		self._cleanup_campus(second_campus)

	def test_lead_sales_scoped_to_team(self):
		user, staff = self._make_user_and_staff(
			"_Test Scope Lead Sale Student", roles=["Lead Sale"], team=self._team, function="Lead Sale"
		)
		condition = shared_conditions("CRM Lead", user=user)
		self.assertIsNotNone(condition)
		self.assertIn("owning_team", condition)
		self.assertIn(staff, condition)

	def test_sale_scoped_to_own_contact(self):
		user, staff = self._make_user_and_staff("_Test Scope Sale Contact", roles=["Sale"])
		condition = shared_conditions("CRM Student", user=user)
		self.assertIn(staff, condition)

	def test_sale_scoped_to_own_assigned_only(self):
		user, staff = self._make_user_and_staff("_Test Scope Sale", roles=["Sale"])
		condition = shared_conditions("CRM Student", user=user)
		self.assertEqual(condition, f"`tabCRM Student`.owner_staff = {frappe.db.escape(staff)}")

	def test_sale_scoped_to_own_assigned_student(self):
		user, staff = self._make_user_and_staff("_Test Scope Sale Student", roles=["Sale"])
		condition = shared_conditions("CRM Lead", user=user)
		self.assertEqual(condition, f"`tabCRM Lead`.owner_staff = {frappe.db.escape(staff)}")

	def test_lead_sales_uses_team_scope(self):
		user, _staff = self._make_user_and_staff(
			"_Test Scope Precedence",
			roles=["Lead Sale"],
			team=self._team,
			function="Lead Sale",
		)
		condition = shared_conditions("CRM Student", user=user)
		self.assertNotEqual(condition, "1=0")
		self.assertIn("owning_team", condition)

	def test_cross_domain_role_overlap_still_fails_closed(self):
		user, _staff = self._make_user_and_staff(
			"_Test Scope Cross Domain",
			roles=["Lead Sale", "Marketing"],
			team=self._team,
			function="Lead Sale",
		)
		self.assertEqual(shared_conditions("CRM Student", user=user), "1=0")

	def test_marketing_scoped_to_own_campus(self):
		# PRD-phan-quyen-lead.md P0-1/P0-2 (2026-09-04): Marketing gets
		# read-only, campus-scoped visibility instead of the old full deny.
		user, staff = self._make_user_and_staff("_Test Scope Marketing Student", roles=["Marketing"])
		condition = shared_conditions("CRM Lead", user=user)
		self.assertNotEqual(condition, "1=0")
		self.assertIn(staff, condition)

	def test_unrecognized_role_denied(self):
		with patch("crm.fcrm.permissions.frappe.get_roles", return_value=["Unknown Legacy Role"]):
			self.assertEqual(shared_conditions("CRM Student", user="unknown-role@example.com"), "1=0")

	# ----------------------------------------------------- doctype delegation wiring

	def test_crm_contact_delegates_to_shared_module(self):
		user, _staff = self._make_user_and_staff("_Test Scope Delegate Contact", roles=["Sale"])
		self.assertEqual(contact_conditions(user=user), shared_conditions("CRM Student", user=user))

	def test_crm_student_delegates_to_shared_module(self):
		user, _staff = self._make_user_and_staff("_Test Scope Delegate Student", roles=["Sale"])
		self.assertEqual(student_conditions(user=user), shared_conditions("CRM Lead", user=user))

	# ---------------------------------------------------------- ownership-gated delete

	def test_delete_allowed_when_creator_owns_even_if_assigned_to_a_teammate(self):
		# Owner (creator) OR assigned_to -- covers the "differ" case explicitly
		# called out by Phase 5 step 1: the acting user authored the record but
		# it is currently assigned to a teammate, not to themselves.
		leader_user, _leader_staff = self._make_user_and_staff(
			"_Test Ownership Leader Creator", roles=["Lead Sale"], team=self._team, function="Lead Sale"
		)
		_teammate_user, teammate_staff = self._make_user_and_staff(
			"_Test Ownership Teammate", roles=["Sale"], team=self._team, function="Sale"
		)
		frappe.set_user(leader_user)
		try:
			contact = frappe.get_doc(
				{
					"doctype": "CRM Student",
					"full_name": "_Test Ownership Creator Contact",
					"phone": "0933000222",
					"assigned_to": teammate_staff,
				}
			)
			contact.insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")
		try:
			self.assertEqual(contact.owner, leader_user)
			self.assertEqual(contact.assigned_to, teammate_staff)
			self.assertTrue(shared_has_permission(contact, user=leader_user, ptype="delete"))
		finally:
			frappe.delete_doc("CRM Student", contact.name, force=True)

	def test_delete_denied_when_in_scope_but_neither_owner_nor_assigned(self):
		# AND-not-OR: being inside the acting user's row-scope must not be
		# enough on its own -- a teammate's record the actor did not create and
		# is not assigned to must stay undeletable even though it is visible.
		_teammate_user, teammate_staff = self._make_user_and_staff(
			"_Test Ownership Other Teammate", roles=["Sale"], team=self._team, function="Sale"
		)
		bystander_user, bystander_staff = self._make_user_and_staff(
			"_Test Ownership Bystander", roles=["Lead Sale"], team=self._team, function="Lead Sale"
		)
		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "_Test Ownership Bystander Contact",
				"phone": "0933000333",
				"assigned_to": teammate_staff,
			}
		)
		contact.insert(ignore_permissions=True)
		try:
			self.assertNotEqual(contact.owner, bystander_user)
			self.assertNotEqual(contact.assigned_to, bystander_staff)
			# Visible via team scope ...
			condition = shared_conditions("CRM Student", user=bystander_user)
			self.assertTrue(
				frappe.db.sql(
					f"select name from `tabCRM Student` where name = %s and ({condition})",
					(contact.name,),
				)
			)
			# ... but not deletable: bystander is neither creator nor assignee.
			self.assertFalse(shared_has_permission(contact, user=bystander_user, ptype="delete"))
		finally:
			frappe.delete_doc("CRM Student", contact.name, force=True)

	def test_kill_switch_restores_delete_without_ownership_gate(self):
		_teammate_user, teammate_staff = self._make_user_and_staff(
			"_Test Ownership KillSwitch Teammate", roles=["Sale"], team=self._team, function="Sale"
		)
		bystander_user, _bystander_staff = self._make_user_and_staff(
			"_Test Ownership KillSwitch Bystander", roles=["Lead Sale"], team=self._team, function="Lead Sale"
		)
		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "_Test Ownership KillSwitch Contact",
				"phone": "0933000444",
				"assigned_to": teammate_staff,
			}
		)
		contact.insert(ignore_permissions=True)
		frappe.conf[PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY] = 1
		try:
			# Without the switch this exact setup is denied (see the previous
			# test) -- the switch restores pre-Phase-5 behavior where row-scope
			# alone governs delete, with no additional ownership gate.
			self.assertTrue(shared_has_permission(contact, user=bystander_user, ptype="delete"))
		finally:
			frappe.conf.pop(PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY, None)
			frappe.delete_doc("CRM Student", contact.name, force=True)

	def test_delete_still_denied_outside_row_scope_even_if_owner(self):
		# Ownership must never act as an alternate grant path around row-scope:
		# a Sale user who owns/created a record that has since been assigned
		# away to someone else, outside their own-assigned-only scope, must
		# still be denied.
		sale_user, sale_staff = self._make_user_and_staff("_Test Ownership Sale Creator", roles=["Sale"])
		_other_user, other_staff = self._make_user_and_staff("_Test Ownership Sale Other", roles=["Sale"])
		frappe.set_user(sale_user)
		try:
			contact = frappe.get_doc(
				{
					"doctype": "CRM Student",
					"full_name": "_Test Ownership Sale Reassigned Contact",
					"phone": "0933000555",
					"assigned_to": sale_staff,
				}
			)
			contact.insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")
		contact.assigned_to = other_staff
		contact.save(ignore_permissions=True)
		try:
			self.assertEqual(contact.owner, sale_user)
			self.assertEqual(
				shared_conditions("CRM Student", user=sale_user),
				f"`tabCRM Student`.owner_staff = {frappe.db.escape(sale_staff)}",
			)
			self.assertFalse(shared_has_permission(contact, user=sale_user, ptype="delete"))
		finally:
			frappe.delete_doc("CRM Student", contact.name, force=True)

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
			function = "Lead Sale" if function == "Team Leader" else function
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

	def _make_user_without_staff(self, email, roles):
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		self.addCleanup(lambda: frappe.delete_doc("User", email, force=True))
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "_Test",
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
		return email
