from inspect import signature
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.demo import seed_director_analytics as seed


class TestSeedDirectorAnalyticsDefinition(FrappeTestCase):
	def test_fixture_is_local_only_and_uses_non_production_example_data(self):
		self.assertEqual(seed.LOCAL_SITE, "crm.localhost")
		self.assertEqual(seed.NAMESPACE, "director-analytics-local-2026")
		self.assertEqual(len(seed.RECORDED_SPEND_ROWS), 3)

	def test_recorded_spend_is_explicitly_not_an_approved_cost_source(self):
		self.assertTrue(all(row["amount"] > 0 for row in seed.RECORDED_SPEND_ROWS))
		self.assertTrue(all(row["spend_date"].year == 2026 for row in seed.RECORDED_SPEND_ROWS))

	def test_academic_fixture_contains_quota_and_tuition(self):
		self.assertEqual({line["line_kind"] for line in seed.ACADEMIC_LINES}, {"quota", "tuition"})
		self.assertEqual(next(line["quota"] for line in seed.ACADEMIC_LINES if line["line_kind"] == "quota"), 180)
		self.assertTrue(all(seed.NAMESPACE not in line["note"] for line in seed.ACADEMIC_LINES))

	def test_academic_line_marker_is_namespaced_for_idempotent_append(self):
		line = seed._namespaced_academic_line(
			seed.ACADEMIC_LINES[0], {"major": "SE"}, {"campus": "HCMC"}
		)
		self.assertEqual(line["note"], f"{seed.NAMESPACE}: Học phí ghi nhận cho dashboard local")
		self.assertEqual((line["major"], line["campus"]), ("SE", "HCMC"))

	def test_execute_reuses_the_callers_existing_admissions_context_and_staff(self):
		self.assertEqual(list(signature(seed.execute).parameters), ["admissions", "context", "staff_context"])

	def test_metabase_fixture_never_invents_a_remote_configuration(self):
		with patch("crm.demo.seed_director_analytics.frappe.db.table_exists", return_value=False):
			self.assertEqual(seed._metabase_catalog_fixture(), {"status": "unavailable", "reason": "canonical_config_missing"})
