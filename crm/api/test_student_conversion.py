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
