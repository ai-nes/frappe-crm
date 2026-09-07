import unittest

try:
	import frappe
except ImportError:  # pragma: no cover - exercised by the no-bench CI lane
	frappe = None


@unittest.skipIf(frappe is None, "Conversion readiness tests require a Frappe bench")
class TestConversionReadiness(unittest.TestCase):
	def test_requires_cccd_high_school_and_major(self):
		from crm.fcrm.conversion_readiness import conversion_blockers, is_conversion_ready

		lead = {"id_number": "", "high_school": "THPT-1", "major": None}

		self.assertEqual(conversion_blockers(lead), ["missing_id_number", "missing_major"])
		self.assertFalse(is_conversion_ready(lead))

	def test_ready_when_all_three_inputs_are_present(self):
		from crm.fcrm.conversion_readiness import conversion_readiness, is_conversion_ready

		lead = {"id_number": "012345678901", "high_school": "THPT-1", "major": "CS"}

		self.assertTrue(is_conversion_ready(lead))
		self.assertEqual(
			conversion_readiness(lead),
			{"ready": True, "status": "Ready", "blockers": []},
		)

	def test_supports_document_like_records(self):
		from crm.fcrm.conversion_readiness import conversion_blockers

		class Lead:
			id_number = "012345678901"
			high_school = "THPT-1"
			major = "CS"

		self.assertEqual(conversion_blockers(Lead()), [])
