import frappe
from frappe.tests.utils import FrappeTestCase

from crm.services.sales_action_policy import ACTION_POLICIES, V2_ACTION_TYPES, validate_action_command
from crm.services.student_context import is_committed_task_state, material_student_changed, snapshot_hash


class TestStudentTaskV2Contracts(FrappeTestCase):
	def test_policy_registry_covers_exact_v2_action_vocabulary(self):
		self.assertEqual(tuple(ACTION_POLICIES), V2_ACTION_TYPES)
		self.assertEqual(len(ACTION_POLICIES), 11)
		self.assertIn("package", ACTION_POLICIES["CALL"].required_inputs)
		self.assertIn("authority", ACTION_POLICIES["PARENT_CONTACT"].required_inputs)

	def test_parent_contact_fails_closed_without_authority(self):
		with self.assertRaises(frappe.PermissionError):
			validate_action_command(
				"PARENT_CONTACT",
				student="_missing_student_for_v2_test",
				inputs={"objective": "contact", "authority": True, "channel": "phone", "timing": True},
				actor_roles={"Sale"},
			)

	def test_material_change_projection_and_state_helpers(self):
		before = {"student_name": "A", "major": "M"}
		after = {"student_name": "A", "major": "N"}
		self.assertTrue(material_student_changed(after, before))
		self.assertFalse(material_student_changed(after, {"student_name": "A", "major": "N"}))
		self.assertTrue(is_committed_task_state("ACCEPTED"))
		self.assertFalse(is_committed_task_state("PENDING"))
		self.assertEqual(snapshot_hash({"b": 2, "a": 1}), snapshot_hash({"a": 1, "b": 2}))
