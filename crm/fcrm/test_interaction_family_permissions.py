# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Row-level scoping tests for CRM Interaction / CRM Intent / CRM Score
History. Previously these three doctypes had DocType-level role grants only
(e.g. Sale, Marketing readable) with no permission_query_conditions/
has_permission hook, so a role with a channel-based read grant could see
every student's evidence regardless of assignment. See
crm/fcrm/permissions.py's get_interaction_permission_query_conditions,
get_intent_permission_query_conditions, and
OPERATIONAL_RECORD_STUDENT_FIELDS.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.permissions import (
	get_interaction_permission_query_conditions,
	has_interaction_permission,
	has_operational_record_permission,
)
from crm.fcrm.test_permissions import TestSharedScopingPermissions


class TestInteractionFamilyPermissions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = TestSharedScopingPermissions._make_campus(self, "_Test IFP Campus")
		self._department = TestSharedScopingPermissions._get_or_create_department(
			self, "_Test IFP Dept", self._campus
		)
		if not frappe.db.exists("CRM Term", "_Test IFP Call"):
			frappe.get_doc(
				{"doctype": "CRM Term", "term_name": "_Test IFP Call", "category": "interaction_type"}
			).insert(ignore_permissions=True)

	def tearDown(self):
		for name in frappe.db.get_all("CRM Interaction", filters={"summary": ["like", "_Test IFP%"]}, pluck="name"):
			frappe.delete_doc("CRM Interaction", name, force=True)
		for name in frappe.db.get_all("CRM Student", filters={"student_name": ["like", "_Test IFP%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for name in frappe.db.get_all("CRM Contact", filters={"full_name": ["like", "_Test IFP%"]}, pluck="name"):
			frappe.delete_doc("CRM Contact", name, force=True)
		for name in frappe.db.get_all("CRM Staff", filters={"full_name": ["like", "%_Test IFP%"]}, pluck="name"):
			frappe.delete_doc("CRM Staff", name, force=True)
		for name in frappe.db.get_all("User", filters={"first_name": ["like", "_Test IFP%"]}, pluck="name"):
			frappe.delete_doc("User", name, force=True)
		self._cleanup_campus(self._campus)

	# ---------------------------------------------------------------------- helpers

	def _cleanup_campus(self, campus):
		if campus and frappe.db.exists("CRM Campus", campus):
			frappe.delete_doc("CRM Campus", campus, force=True)

	def _make_user_and_staff(self, prefix, roles):
		return TestSharedScopingPermissions._make_user_and_staff(self, prefix, roles=roles)

	def _make_student(self, name, owner_staff=None):
		student = frappe.get_doc({"doctype": "CRM Student", "student_name": name, "phone": "0900000000"})
		previous_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_flag
		if owner_staff:
			student.db_set("owner_staff", owner_staff)
		return student

	def _make_interaction(self, student_name, summary):
		interaction = frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"student": student_name,
				"interaction_type": "_Test IFP Call",
				"summary": summary,
			}
		)
		interaction.insert(ignore_permissions=True)
		return interaction

	# -------------------------------------------------------------- query conditions

	def test_system_manager_has_unrestricted_interaction_access(self):
		user, _staff = self._make_user_and_staff("_Test IFP Admin", ["System Manager"])
		self.assertIsNone(get_interaction_permission_query_conditions(user=user, doctype="CRM Interaction"))

	def test_marketing_role_has_no_row_scope_despite_channel(self):
		# Marketing has DocType-level read on CRM Interaction (crm_interaction.json),
		# but must never see a row solely because the channel is Email/Chat -- it
		# has no Student/Contact case scope in the canonical policy.
		user, _staff = self._make_user_and_staff("_Test IFP Marketing", ["Marketing"])
		self.assertEqual(get_interaction_permission_query_conditions(user=user, doctype="CRM Interaction"), "1=0")

	def test_sale_only_sees_own_assigned_students_interaction(self):
		user, staff = self._make_user_and_staff("_Test IFP Sale", ["Sale"])
		student = self._make_student("_Test IFP Sale Student", owner_staff=staff)
		other_student = self._make_student("_Test IFP Other Student")
		mine = self._make_interaction(student.name, "_Test IFP mine")
		theirs = self._make_interaction(other_student.name, "_Test IFP theirs")

		condition = get_interaction_permission_query_conditions(user=user, doctype="CRM Interaction")
		visible = frappe.db.sql(
			f"select name from `tabCRM Interaction` where name in %(names)s and ({condition})",
			{"names": [mine.name, theirs.name]},
			as_dict=True,
		)
		visible_names = {row.name for row in visible}
		self.assertIn(mine.name, visible_names)
		self.assertNotIn(theirs.name, visible_names)

	def test_has_interaction_permission_matches_query_condition(self):
		user, staff = self._make_user_and_staff("_Test IFP HasPerm", ["Sale"])
		student = self._make_student("_Test IFP HasPerm Student", owner_staff=staff)
		other_student = self._make_student("_Test IFP HasPerm Other")
		mine = self._make_interaction(student.name, "_Test IFP haspm mine")
		theirs = self._make_interaction(other_student.name, "_Test IFP haspm theirs")

		self.assertTrue(has_interaction_permission(mine, user=user))
		self.assertFalse(has_interaction_permission(theirs, user=user))

	def test_interaction_create_permission_checks_linked_student_not_own_row(self):
		# Same class of guard as the Intent create-time check: a DocType-level
		# Sale create grant must not let a user attach an interaction to a
		# student outside their scope, and an interaction with neither
		# student nor crm_contact set has nothing to scope against and must
		# be denied rather than silently allowed.
		user, staff = self._make_user_and_staff("_Test IFP Interaction Create", ["Sale"])
		student = self._make_student("_Test IFP Interaction Create Student", owner_staff=staff)
		other_student = self._make_student("_Test IFP Interaction Create Other")

		mine_new = frappe.new_doc("CRM Interaction")
		mine_new.student = student.name
		self.assertTrue(has_interaction_permission(mine_new, user=user, ptype="create"))

		theirs_new = frappe.new_doc("CRM Interaction")
		theirs_new.student = other_student.name
		self.assertFalse(has_interaction_permission(theirs_new, user=user, ptype="create"))

		empty_new = frappe.new_doc("CRM Interaction")
		self.assertFalse(has_interaction_permission(empty_new, user=user, ptype="create"))

	def test_contact_only_interaction_scoped_via_contact_condition(self):
		user, staff = self._make_user_and_staff("_Test IFP Contact Sale", ["Sale"])
		contact = frappe.get_doc(
			{"doctype": "CRM Contact", "full_name": "_Test IFP Contact", "phone": "0900000099"}
		)
		contact.insert(ignore_permissions=True)
		contact.db_set("owner_staff", staff)
		interaction = frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"crm_contact": contact.name,
				"interaction_type": "_Test IFP Call",
				"summary": "_Test IFP contact-only",
			}
		)
		interaction.insert(ignore_permissions=True)

		other_user, _other_staff = self._make_user_and_staff("_Test IFP Contact Sale Other", ["Sale"])
		self.assertTrue(has_interaction_permission(interaction, user=user))
		self.assertFalse(has_interaction_permission(interaction, user=other_user))

	# --------------------------------------------------- CRM Intent / Score History

	def test_intent_scoped_to_own_assigned_student(self):
		from crm.fcrm.permissions import get_intent_permission_query_conditions, has_intent_permission

		if not frappe.db.exists("CRM Term", "_Test IFP Intent Type"):
			frappe.get_doc(
				{
					"doctype": "CRM Term",
					"term_name": "_Test IFP Intent Type", "category": "intent_type",
					"metadata": {"importance": "Medium"},
				}
			).insert(ignore_permissions=True)

		user, staff = self._make_user_and_staff("_Test IFP Intent Sale", ["Sale"])
		student = self._make_student("_Test IFP Intent Student", owner_staff=staff)
		other_student = self._make_student("_Test IFP Intent Other")
		mine_interaction = self._make_interaction(student.name, "_Test IFP intent mine")
		theirs_interaction = self._make_interaction(other_student.name, "_Test IFP intent theirs")

		mine_intent = frappe.get_doc(
			{"doctype": "CRM Intent", "interaction": mine_interaction.name, "intent_type": "_Test IFP Intent Type"}
		).insert(ignore_permissions=True)
		theirs_intent = frappe.get_doc(
			{"doctype": "CRM Intent", "interaction": theirs_interaction.name, "intent_type": "_Test IFP Intent Type"}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Intent", mine_intent.name, force=True)
		self.addCleanup(frappe.delete_doc, "CRM Intent", theirs_intent.name, force=True)

		condition = get_intent_permission_query_conditions(user=user, doctype="CRM Intent")
		visible = frappe.db.sql(
			f"select name from `tabCRM Intent` where name in %(names)s and ({condition})",
			{"names": [mine_intent.name, theirs_intent.name]},
			as_dict=True,
		)
		visible_names = {row.name for row in visible}
		self.assertIn(mine_intent.name, visible_names)
		self.assertNotIn(theirs_intent.name, visible_names)

		self.assertTrue(has_intent_permission(mine_intent, user=user))
		self.assertFalse(has_intent_permission(theirs_intent, user=user))

	def test_intent_on_contact_only_interaction_falls_back_to_contact_scope(self):
		# CRM Intent.student is null when its parent Interaction is Contact-only
		# (pre-conversion). Scoping must fall back through the parent Interaction's
		# own Contact condition instead of denying every such Intent outright.
		from crm.fcrm.permissions import get_intent_permission_query_conditions, has_intent_permission

		if not frappe.db.exists("CRM Term", "_Test IFP Contact Intent Type"):
			frappe.get_doc(
				{
					"doctype": "CRM Term",
					"term_name": "_Test IFP Contact Intent Type", "category": "intent_type",
					"metadata": {"importance": "Medium"},
				}
			).insert(ignore_permissions=True)

		user, staff = self._make_user_and_staff("_Test IFP Intent Contact Sale", ["Sale"])
		contact = frappe.get_doc(
			{"doctype": "CRM Contact", "full_name": "_Test IFP Intent Contact", "phone": "0900000098"}
		)
		contact.insert(ignore_permissions=True)
		contact.db_set("owner_staff", staff)
		interaction = frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"crm_contact": contact.name,
				"interaction_type": "_Test IFP Call",
				"summary": "_Test IFP contact-only intent source",
			}
		)
		interaction.insert(ignore_permissions=True)
		self.assertIsNone(interaction.student)

		intent = frappe.get_doc(
			{"doctype": "CRM Intent", "interaction": interaction.name, "intent_type": "_Test IFP Contact Intent Type"}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Intent", intent.name, force=True)
		self.assertIsNone(intent.student)

		other_user, _other_staff = self._make_user_and_staff("_Test IFP Intent Contact Other", ["Sale"])
		self.assertTrue(has_intent_permission(intent, user=user))
		self.assertFalse(has_intent_permission(intent, user=other_user))

	def test_intent_create_permission_checks_linked_interaction_not_own_row(self):
		# has_permission fires on Document.insert()'s "create" check before
		# autoname assigns doc.name, so the name-keyed row-scope query cannot
		# run against the (unassigned) Intent row itself -- but the linked
		# `interaction` already exists and its scope must still be checked.
		# frappe/permissions.py's has_controller_permissions() actually calls the
		# hook via frappe.call(method, doc=doc, ptype=ptype, ...) -- the real
		# kwarg is `ptype`, not `permission_type` -- so this must be exercised
		# with `ptype=` to prove the guard fires on the real call shape, not
		# just on a name this test happens to choose.
		from crm.fcrm.permissions import has_intent_permission

		if not frappe.db.exists("CRM Term", "_Test IFP Create Guard Type"):
			frappe.get_doc(
				{
					"doctype": "CRM Term",
					"term_name": "_Test IFP Create Guard Type", "category": "intent_type",
					"metadata": {"importance": "Medium"},
				}
			).insert(ignore_permissions=True)

		user, staff = self._make_user_and_staff("_Test IFP Intent Create", ["Sale"])
		student = self._make_student("_Test IFP Intent Create Student", owner_staff=staff)
		other_student = self._make_student("_Test IFP Intent Create Other")
		mine_interaction = self._make_interaction(student.name, "_Test IFP intent create mine")
		theirs_interaction = self._make_interaction(other_student.name, "_Test IFP intent create theirs")

		# No interaction at all -- nothing to scope against, must deny rather
		# than silently allow (this is the exact bypass the guard closes).
		empty_intent = frappe.new_doc("CRM Intent")
		self.assertIsNone(empty_intent.name)
		self.assertFalse(has_intent_permission(empty_intent, user=user, ptype="create"))

		mine_new = frappe.new_doc("CRM Intent")
		mine_new.interaction = mine_interaction.name
		self.assertTrue(has_intent_permission(mine_new, user=user, ptype="create"))

		theirs_new = frappe.new_doc("CRM Intent")
		theirs_new.interaction = theirs_interaction.name
		self.assertFalse(has_intent_permission(theirs_new, user=user, ptype="create"))

	def test_intent_create_permission_via_real_document_insert_path(self):
		# End-to-end proof (not just a direct function call): a Sale-role user
		# with no interaction/student row yet can actually insert a CRM Intent,
		# going through the real frappe.has_permission -> hooks.py wiring ->
		# has_intent_permission dispatch.
		if not frappe.db.exists("CRM Term", "_Test IFP Create Path Type"):
			frappe.get_doc(
				{
					"doctype": "CRM Term",
					"term_name": "_Test IFP Create Path Type", "category": "intent_type",
					"metadata": {"importance": "Medium"},
				}
			).insert(ignore_permissions=True)

		user, staff = self._make_user_and_staff("_Test IFP Intent Insert Path", ["Sale"])
		student = self._make_student("_Test IFP Intent Insert Student", owner_staff=staff)
		interaction = self._make_interaction(student.name, "_Test IFP intent insert path")

		frappe.set_user(user)
		try:
			intent = frappe.get_doc(
				{
					"doctype": "CRM Intent",
					"interaction": interaction.name,
					"intent_type": "_Test IFP Create Path Type",
				}
			)
			intent.insert()
		finally:
			frappe.set_user("Administrator")
		self.addCleanup(frappe.delete_doc, "CRM Intent", intent.name, force=True)
		self.assertTrue(frappe.db.exists("CRM Intent", intent.name))

	def test_score_history_denied_for_unrelated_student(self):
		user, staff = self._make_user_and_staff("_Test IFP Score Sale", ["Sale"])
		_mine = self._make_student("_Test IFP Score Student", owner_staff=staff)
		other_student = self._make_student("_Test IFP Score Other")

		denied = has_operational_record_permission(
			frappe._dict(doctype="CRM Score History", student=other_student.name), user=user
		)
		self.assertFalse(denied)
