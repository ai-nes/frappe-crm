from unittest import TestCase
from unittest.mock import patch

from crm.demo.seed_lead_api_lookups import PUBLIC_LEAD_MAJORS, SCHOOLS_PER_PROVINCE, execute


class TestSeedLeadAPILookups(TestCase):
	def test_execute_seeds_small_geography_slice_and_majors(self):
		with (
			patch(
				"crm.demo.seed_lead_api_lookups.seed_school_seed",
				return_value={"mutations": {"school_created": 35}, "errors": []},
			) as seed_school,
			patch(
				"crm.demo.seed_lead_api_lookups._ensure_major", return_value=("Major", True)
			) as ensure_major,
			patch("crm.demo.seed_lead_api_lookups.frappe.db.commit"),
		):
			result = execute()

		seed_school.assert_called_once_with(
			dry_run=False,
			commit_policy="all",
			max_schools_per_province=SCHOOLS_PER_PROVINCE,
		)
		self.assertEqual(ensure_major.call_count, len(PUBLIC_LEAD_MAJORS))
		self.assertEqual(result["schools_per_province"], 5)
		self.assertEqual(len(result["provinces"]), 7)
		self.assertEqual(result["majors_created"], len(PUBLIC_LEAD_MAJORS))
		self.assertEqual(result["geography"]["school_created"], 35)

	def test_execute_fails_when_geography_seed_has_errors(self):
		with patch(
			"crm.demo.seed_lead_api_lookups.seed_school_seed",
			return_value={"mutations": {}, "errors": [{"source_row": 1}]},
		):
			with self.assertRaisesRegex(RuntimeError, "1 errors"):
				execute()
