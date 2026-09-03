import unittest

from crm.services.action_outcome import derive_progress, validate_outcome


class TestActionOutcome(unittest.TestCase):
	def test_progress_is_bounded_and_type_aware(self):
		self.assertEqual(derive_progress("CALL", "success"), "POSITIVE_PROGRESS")
		self.assertEqual(derive_progress("EMAIL", "failed"), "NEGATIVE_PROGRESS")
		self.assertEqual(derive_progress("HANDOFF", "success"), "UNKNOWN")

	def test_unknown_outcome_is_rejected(self):
		with self.assertRaises(ValueError):
			validate_outcome("converted")
