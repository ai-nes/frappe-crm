import unittest

try:
	import frappe
except ImportError:  # pragma: no cover - exercised by the no-bench CI lane
	frappe = None


@unittest.skipIf(frappe is None, "Conversion readiness tests require a Frappe bench")
class TestConversionReadiness(unittest.TestCase):
	def test_requires_phone_province_high_school_and_major(self):
		from crm.fcrm.conversion_readiness import conversion_blockers, is_conversion_ready

		lead = {
			"phone": "",
			"province": "",
			"high_school": "THPT-1",
			"major": None,
		}

		self.assertEqual(
			conversion_blockers(lead),
			["missing_phone", "missing_province", "missing_major"],
		)
		self.assertFalse(is_conversion_ready(lead))

	def test_ready_when_all_four_inputs_are_present_without_cccd(self):
		from crm.fcrm.conversion_readiness import conversion_readiness, is_conversion_ready

		lead = {
			"phone": "0900000000",
			"province": "Ho Chi Minh City",
			"high_school": "THPT-1",
			"major": "CS",
		}

		self.assertTrue(is_conversion_ready(lead))
		self.assertEqual(
			conversion_readiness(lead),
			{"ready": True, "status": "Ready", "blockers": []},
		)

	def test_supports_document_like_records(self):
		from crm.fcrm.conversion_readiness import conversion_blockers

		class Lead:
			phone = "0900000000"
			province = "Ho Chi Minh City"
			high_school = "THPT-1"
			major = "CS"

		self.assertEqual(conversion_blockers(Lead()), [])
