"""Regression coverage for long admission selection idempotency keys."""

import unittest

from crm.fcrm.admission_application import _application_source_reference


class TestAdmissionApplicationSourceReference(unittest.TestCase):
	def test_short_reference_is_preserved(self):
		self.assertEqual(_application_source_reference("student-1", "key-1"), "student-1:key-1")

	def test_reference_at_data_limit_is_preserved(self):
		key = "x" * 138
		self.assertEqual(_application_source_reference("s", key), f"s:{key}")

	def test_reference_over_data_limit_is_compact_and_deterministic(self):
		key = "x" * 139
		reference = _application_source_reference("s", key)
		self.assertLessEqual(len(reference), 140)
		self.assertEqual(reference, _application_source_reference("s", key))

	def test_long_keys_with_same_prefix_remain_distinct(self):
		prefix = "x" * 200
		self.assertNotEqual(
			_application_source_reference("student-1", f"{prefix}:SCHOLARSHIP"),
			_application_source_reference("student-1", f"{prefix}:STUDY_NOW_PAY_LATER"),
		)

	def test_same_long_key_for_different_students_remains_distinct(self):
		key = "x" * 200
		self.assertNotEqual(
			_application_source_reference("student-1", key),
			_application_source_reference("student-2", key),
		)
