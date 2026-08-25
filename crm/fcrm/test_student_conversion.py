"""Backend contract tests for the Phase 8 conversion command.

These tests run inside a Frappe bench.  The repository's lightweight Python
environment intentionally has no Frappe runtime, so collection is skipped
there rather than replacing the command contract with an unfaithful mock.
"""

import unittest

try:
	import frappe
except ImportError:  # pragma: no cover - exercised by the no-bench CI lane
	frappe = None


@unittest.skipIf(frappe is None, "Phase 8 command tests require a Frappe bench")
class TestStudentConversionCommand(unittest.TestCase):
	def test_expected_revision_and_idempotency_are_required(self):
		from crm.fcrm.student_conversion import StudentConversionError, convert_student

		with self.assertRaises(StudentConversionError) as ctx:
			convert_student(student="STU-MISSING", expected_lifecycle_revision=None, idempotency_key="")
		self.assertIn(ctx.exception.code, {"INVALID_INPUT", "DISABLED"})

	def test_conversion_is_disabled_by_default(self):
		from crm.fcrm.student_conversion import StudentConversionError, convert_student

		with self.assertRaises(StudentConversionError) as ctx:
			convert_student(student="STU-1", expected_lifecycle_revision=1, idempotency_key="cmd-1")
		self.assertEqual(ctx.exception.code, "DISABLED")

	def test_legacy_endpoint_cannot_synthesize_request_identity(self):
		from crm.fcrm.doctype.crm_student.crm_student import CRMStudent

		student = CRMStudent({"doctype": "CRM Student", "name": "STU-1"})
		with self.assertRaises(Exception):
			student.convert_to_contact()
