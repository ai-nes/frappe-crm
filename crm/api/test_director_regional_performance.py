from datetime import datetime
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api import director_regional_performance


class TestDirectorRegionalPerformance(FrappeTestCase):
	def test_province_builder_keeps_canonical_funnel_order_and_null_denominators(self):
		as_of = datetime(2026, 8, 31, 10, tzinfo=director_regional_performance.LOCAL_TIMEZONE)
		province = director_regional_performance._build_province(
			"P-1", "Đắk Lắk", [{"processing_status": "NEW", "resolution": "PENDING", "creation": "2026-08-01"}], [], None, None, as_of
		)

		self.assertEqual(
			[stage["id"] for stage in province["funnel"]],
			[stage[0] for stage in director_regional_performance.FUNNEL_STAGES],
		)
		self.assertEqual([stage["value"] for stage in province["funnel"]], [1, 0, 0, 0])
		self.assertEqual(province["targetAchievement"], 0.0)
		self.assertEqual(province["conversion"], 0.0)
		self.assertIsNone(province["applicationChange"])
		self.assertIsNone(director_regional_performance._ratio(0, 0))
		self.assertEqual(len(province["trend"]), 6)

	def test_endpoint_returns_documented_snapshot_shape(self):
		as_of = datetime(2026, 8, 31, 10, tzinfo=director_regional_performance.LOCAL_TIMEZONE)
		with (
			patch.object(
				director_regional_performance,
				"require_director_access",
				return_value={"user": "director@example.com", "roleState": "canonical_profile"},
			),
			patch.object(director_regional_performance, "resolve_admission_year", return_value="2026"),
			patch.object(
				director_regional_performance,
				"_resolve_scope",
				return_value={"id": "all", "label": "Toàn bộ địa bàn", "territory": None},
			),
			patch.object(director_regional_performance, "_now", return_value=as_of),
			patch.object(director_regional_performance, "_load_students", return_value=[]),
			patch.object(director_regional_performance, "_build_provinces", return_value=[]),
		):
			response = director_regional_performance.get_director_regional_performance("2026", "all")

		self.assertEqual(set(response), {"meta", "capabilityColumns", "provinces", "priorityActions"})
		self.assertEqual(response["meta"]["status"], "available")
		self.assertEqual(response["meta"]["trendMonths"], 6)
		self.assertEqual(response["meta"]["warnings"], [])
		self.assertEqual(len(response["capabilityColumns"]), 6)
