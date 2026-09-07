from unittest import TestCase

from crm.patches.v1_0.consolidate_admissions_technical_records import build_manifest


class TestConsolidateAdmissionsTechnicalRecords(TestCase):
	def test_manifest_contains_counts_and_no_raw_record_name(self):
		manifest = build_manifest(
			{"CRM Student Routing Request": [{"name": "ROUTE-0001", "creation": "2026-08-25"}]}
		)
		self.assertEqual(manifest["counts"], {})
		self.assertNotIn("ROUTE-0001", str(manifest))
		self.assertEqual(manifest["items"], [])
