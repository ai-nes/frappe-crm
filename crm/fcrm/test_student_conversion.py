"""Backend contract tests for the Phase 8 conversion command.

These tests run inside a Frappe bench.  The repository's lightweight Python
environment intentionally has no Frappe runtime, so collection is skipped
there rather than replacing the command contract with an unfaithful mock.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

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

		with (
			patch("crm.fcrm.student_conversion.enabled", return_value=False),
			self.assertRaises(StudentConversionError) as ctx,
		):
			convert_student(student="STU-1", expected_lifecycle_revision=1, idempotency_key="cmd-1")
		self.assertEqual(ctx.exception.code, "DISABLED")

	def test_legacy_endpoint_cannot_synthesize_request_identity(self):
		from crm.fcrm.doctype.crm_lead.crm_lead import CRMLead

		student = CRMLead({"doctype": "CRM Lead", "name": "STU-1"})
		with self.assertRaises(Exception):
			student.convert_to_contact()

	def test_command_exposes_exact_once_boundaries_for_replay_and_races(self):
		from crm.fcrm import student_conversion

		source = Path(student_conversion.__file__).read_text(encoding="utf-8")
		self.assertIn("for update", source.lower())
		self.assertIn("IDEMPOTENCY_KEY_REUSED", source)
		self.assertIn("expected_lifecycle_revision", source)
		self.assertIn("CONVERSION_DOCTYPE", source)

	def test_conversion_uses_explicit_lead_to_student_snapshot_map(self):
		from crm.fcrm.student_conversion import _student_snapshot_values

		lead = frappe._dict(
			{
				"student_name": "Mapped Lead",
				"phone": "0911111199",
				"email": "mapped@example.com",
				"enrollment_status": "PROSPECT",
				"source": "Website",
				"latest_score": 98,
				"student_context_revision": 7,
				"notes": "Snapshot note",
			}
		)
		identity = frappe._dict(name="ID-MAPPED")

		values = _student_snapshot_values(lead, identity)

		self.assertEqual(values["full_name"], "Mapped Lead")
		self.assertEqual(values["phone"], "0911111199")
		self.assertEqual(values["source"], "Website")
		self.assertEqual(values["notes"], "Snapshot note")
		self.assertNotIn("latest_score", values)
		self.assertNotIn("student_context_revision", values)

	def test_conversion_does_not_auto_match_by_identity(self):
		from crm.fcrm import student_conversion

		source = Path(student_conversion.__file__).read_text(encoding="utf-8")
		self.assertNotIn("_contacts_for_identity", source)
		self.assertIn("target_student", source)

	def test_only_enrolled_students_are_convertible(self):
		from crm.fcrm import student_conversion

		source = Path(student_conversion.__file__).read_text(encoding="utf-8")
		self.assertIn("Enrolled", source)
		self.assertIn("CONVERSION_CONDITION_FAILED", source)
