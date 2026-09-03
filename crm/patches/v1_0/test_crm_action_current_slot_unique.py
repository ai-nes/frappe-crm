"""The current-slot normalization is correct and re-runnable.

The unique key is created by ``_ensure_unique_index`` (shared with the student
next-task patch and covered there); this exercises the pre-key normalization
that the current-slot patch runs first.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.test_permissions import TestSharedScopingPermissions
from crm.patches.v1_0 import crm_action_current_slot_unique as patch

_INDEX = "crm_action_student_current_slot_uniq"


class TestCRMActionCurrentSlotUnique(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = TestSharedScopingPermissions._make_campus(self, "_Slot Patch Campus")
		self._department = TestSharedScopingPermissions._get_or_create_department(
			self, "_Slot Patch Dept", self._campus
		)
		self._student = self._make_student("_Slot Patch Student")
		# Drop the migrated key so a pre-migration violation can be fabricated;
		# restore it afterwards regardless of how the test exits.
		frappe.db.sql_ddl(f"DROP INDEX IF EXISTS `{_INDEX}` ON `tabCRM Action`")
		self.addCleanup(
			frappe.db.sql_ddl,
			f"ALTER TABLE `tabCRM Action` ADD UNIQUE KEY `{_INDEX}` (student, current_slot)",
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.db.get_all("CRM Action", filters={"student": self._student.name}, pluck="name"):
			frappe.delete_doc("CRM Action", name, force=True)
		frappe.delete_doc("CRM Student", self._student.name, force=True)
		frappe.delete_doc("CRM Department", self._department, force=True)
		frappe.delete_doc("CRM Campus", self._campus, force=True)

	def _make_student(self, name):
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc({"doctype": "CRM Student", "student_name": name, "phone": phone})
		previous = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous
		return student

	def _raw_current_slot(self, name):
		return frappe.db.get_value("CRM Action", name, "current_slot")

	def _force_current_slot(self, name, value):
		frappe.db.set_value("CRM Action", name, "current_slot", value, update_modified=False)

	def _make_action(self, state="pending"):
		return frappe.get_doc(
			{
				"doctype": "CRM Action",
				"student": self._student.name,
				"origin": "ai",
				"source_context_revision": 1,
				"disposition": "ACT",
				"action_type": "CALL",
				"objective": "x",
				"policy_context_version": "t",
				"generation_idempotency_key": frappe.generate_hash(length=20),
				"producer_identity": "test",
				"payload_digest": frappe.generate_hash(length=32),
				"state": state,
			}
		).insert(ignore_permissions=True)

	def test_normalizes_conflicts_and_is_rerunnable(self):
		a = self._make_action()
		b = self._make_action()
		c = self._make_action(state="completed")
		d = self._make_action()
		self._force_current_slot(a.name, "CURRENT")
		self._force_current_slot(b.name, "CURRENT")
		self._force_current_slot(c.name, "CURRENT")
		self._force_current_slot(d.name, "")

		touched = patch._normalize_current_slots()
		self.assertGreaterEqual(touched, 3)

		current = [
			name for name in (a.name, b.name, c.name, d.name) if self._raw_current_slot(name) == "CURRENT"
		]
		self.assertEqual(len(current), 1, "exactly one non-terminal Action keeps the slot")
		self.assertNotIn(c.name, current, "a completed Action never keeps the slot")
		self.assertIsNone(self._raw_current_slot(d.name), "an empty-string slot is normalized to NULL")

		# A second pass has nothing left to normalize.
		self.assertEqual(patch._normalize_current_slots(), 0)
