"""HTTP-contract tests for the Student conversion command."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api import student_conversion


class TestStudentConversionAPI(FrappeTestCase):
	def test_adapter_forwards_enrolled_revision_and_replay_key(self):
		with patch("crm.api.student_conversion._convert_student", return_value={"status": "created"}) as command:
			result = student_conversion.convert_student("STU-1", 7, "convert-1", "corr-1")
		self.assertEqual(result, {"status": "created"})
		command.assert_called_once_with(
			student="STU-1", expected_lifecycle_revision=7, idempotency_key="convert-1", correlation_id="corr-1"
		)

	def test_adapter_forwards_explicit_imported_student_target(self):
		with patch("crm.api.student_conversion._convert_student", return_value={"status": "created"}) as command:
			student_conversion.convert_student("LEAD-1", 3, "convert-2", "corr-2", "STUDENT-1")
		command.assert_called_once_with(
			student="LEAD-1",
			expected_lifecycle_revision=3,
			idempotency_key="convert-2",
			correlation_id="corr-2",
			target_student="STUDENT-1",
		)
