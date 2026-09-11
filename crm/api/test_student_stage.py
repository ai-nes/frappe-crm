"""Focused HTTP adapter tests for Student stage transitions."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import student_stage


class TestStudentStageAPI(FrappeTestCase):
	def test_transition_endpoint_forwards_canonical_student_name(self):
		expected = {"status": "applied", "student": "CRMC-2026-00001"}
		with (
			patch.object(student_stage.frappe.db, "exists", return_value=True),
			patch.object(student_stage, "set_student_stage", return_value=expected) as command,
		):
			self.assertEqual(
				student_stage.request_transition("CRMC-2026-00001", "Attempting"),
				expected,
			)
		command.assert_called_once_with("CRMC-2026-00001", "Attempting")

	def test_transition_endpoint_resolves_lead_name_to_linked_student(self):
		expected = {"status": "applied", "student": "CRMC-2026-00001"}
		with (
			patch.object(student_stage, "canonical_student", return_value="CRMC-2026-00001") as resolve,
			patch.object(student_stage, "set_student_stage", return_value=expected) as command,
		):
			self.assertEqual(
				student_stage.request_transition("ENR-2026-00001", "Attempting"),
				expected,
			)

		resolve.assert_called_once_with("ENR-2026-00001")
		command.assert_called_once_with("CRMC-2026-00001", "Attempting")
