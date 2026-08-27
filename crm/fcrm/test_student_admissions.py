"""Contract tests for the Student Detail admissions action boundary."""

import unittest

from crm.fcrm.student_admissions import ACTION_CAPABILITIES, StudentAdmissionsError, _fingerprint, _payload, _required


class TestStudentAdmissionsContract(unittest.TestCase):
	def test_action_catalog_covers_the_admissions_operating_loop(self):
		self.assertTrue({"digital_signal", "call_attempt", "call_success", "brochure_sent", "major_update", "lifecycle_transition", "event_invite", "event_checkin", "scholarship_interest", "create_task", "create_insight_note", "assign_counselor"}.issubset(ACTION_CAPABILITIES))

	def test_payload_parser_rejects_non_objects(self):
		self.assertEqual(_payload('{"signal":"Zalo chat"}'), {"signal": "Zalo chat"})
		with self.assertRaises(StudentAdmissionsError) as context:
			_payload("[]")
		self.assertEqual(context.exception.code, "INVALID_INPUT")

	def test_required_values_are_trimmed_and_bounded(self):
		self.assertEqual(_required("  value  ", "field"), "value")
		with self.assertRaises(StudentAdmissionsError) as context:
			_required("", "field")
		self.assertEqual(context.exception.code, "INVALID_INPUT")

	def test_fingerprint_is_order_independent(self):
		self.assertEqual(_fingerprint({"a": 1, "b": 2}), _fingerprint({"b": 2, "a": 1}))
