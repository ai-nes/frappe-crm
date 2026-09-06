"""Schema contracts for the assignment control plane."""

import json
from pathlib import Path
from unittest import TestCase


class TestCRMAssignmentControlSchema(TestCase):
	def setUp(self):
		path = Path(__file__).with_name("crm_assignment_control.json")
		self.schema = json.loads(path.read_text(encoding="utf-8"))
		self.fields = {field["fieldname"]: field for field in self.schema["fields"]}

	def test_control_is_a_system_manager_owned_singleton(self):
		self.assertTrue(self.schema["issingle"])
		self.assertTrue(any(row.get("role") == "System Manager" and row.get("write") for row in self.schema["permissions"]))

	def test_routing_switch_requires_capacity_by_default(self):
		self.assertEqual(self.fields["routing_enabled"]["default"], "0")
		self.assertEqual(self.fields["capacity_required"]["default"], "1")
