import unittest

from crm.patches.v1_0.phase3_prepare_student_intake_data import (
	classify_student,
	encode_lookup_key,
	normalize_admission_year,
	normalize_identifier,
)


class TestPhase3PrepareStudentIntakeData(unittest.TestCase):
	def test_lookup_key_is_length_delimited(self):
		self.assertNotEqual(encode_lookup_key("crm.test", "ab", "c"), encode_lookup_key("crm.test", "a", "bc"))

	def test_normalization_and_cycle_validation(self):
		self.assertEqual(normalize_identifier(" 12-345.678 "), "12345678")
		self.assertEqual(normalize_admission_year(" 2026 "), "2026")
		self.assertEqual(normalize_admission_year("26"), "")

	def test_weak_observations_never_resolve_an_identity(self):
		student = {"admission_year": "2026", "phone": "+84 900 000 000", "email": "student@example.com"}
		self.assertEqual(classify_student(student), "weak_only_shared_identifier")

	def test_valid_strong_identifier_resolves(self):
		student = {"admission_year": "2026", "id_number": "012345678"}
		self.assertEqual(classify_student(student), "resolvable")

	def test_malformed_or_missing_cycle_is_quarantined(self):
		self.assertEqual(classify_student({"id_number": "012345678"}), "missing_admission_cycle")
		self.assertEqual(
			classify_student({"admission_year": "2026", "id_number": "123"}),
			"malformed_national_id",
		)
