"""Offline contracts for the large CRM demo student allocation."""

from __future__ import annotations

import unittest

from crm.demo.seed_bulk_realistic import (
	allocate_school_placements,
	background_student_count,
	build_student_values,
	enrich_bulk_scenarios,
	province_weight,
)


class TestBulkAllocation(unittest.TestCase):
	def test_exact_background_count(self):
		self.assertEqual(background_student_count(3184, 17, 5), 3162)

	def test_province_weights_normalize_dong_nai(self):
		self.assertEqual(province_weight("TP. Đồng Nai"), 1.5)
		self.assertEqual(province_weight("Hồ Chí Minh"), 2.0)
		self.assertEqual(province_weight("Lâm Đồng"), 1.0)

	def test_every_school_is_covered_and_cap_is_respected(self):
		schools = [
			{"name": "school-1", "school_name": "A", "province": "Hồ Chí Minh", "ward": "ward-1"},
			{"name": "school-2", "school_name": "B", "province": "TP. Đồng Nai", "ward": "ward-2"},
			{"name": "school-3", "school_name": "C", "province": "Lâm Đồng", "ward": "ward-3"},
		]
		rows = allocate_school_placements(schools, 12, seed=7, per_school_cap=5)
		counts = {school["name"]: 0 for school in schools}
		for row in rows:
			counts[row["name"]] += 1
		self.assertEqual(len(rows), 12)
		self.assertEqual(set(counts), {"school-1", "school-2", "school-3"})
		self.assertTrue(all(1 <= count <= 5 for count in counts.values()))

	def test_allocation_is_deterministic(self):
		schools = [
			{"name": "school-1", "school_name": "A", "province": "Hồ Chí Minh", "ward": "ward-1"},
			{"name": "school-2", "school_name": "B", "province": "Lâm Đồng", "ward": "ward-2"},
		]
		first = allocate_school_placements(schools, 10, seed=19)
		second = allocate_school_placements(list(reversed(schools)), 10, seed=19)
		self.assertEqual([row["name"] for row in first], [row["name"] for row in second])

	def test_invalid_capacity_fails_closed(self):
		with self.assertRaises(ValueError):
			allocate_school_placements(
				[{"name": "school", "province": "Hồ Chí Minh", "ward": "ward"}],
				11,
				per_school_cap=10,
			)

	def test_object_rows_are_normalized_to_school_links(self):
		class School:
			name = "school-1"
			province = "Hồ Chí Minh"
			ward = "ward-1"

		rows = enrich_bulk_scenarios(
			[{"key": "bulk-student-001", "student_name": "A", "email": "a@example.test"}],
			[School()],
			[("Công nghệ thông tin", 1.0)],
			["Showcase Website"],
		)
		self.assertEqual(rows[0]["high_school"], "school-1")
		self.assertEqual(rows[0]["province"], "Hồ Chí Minh")
		self.assertEqual(rows[0]["ward"], "ward-1")

	def test_student_payload_contains_complete_school_and_cohort_fields(self):
		values = build_student_values(
			{
				"key": "bulk-student-001",
				"student_name": "A",
				"email": "a@example.test",
				"phone": "0908000001",
				"gender": "Female",
				"admission_method": "Combined",
				"target_stage": "Applicant",
				"high_school": "school-1",
				"province": "Hồ Chí Minh",
				"ward": "ward-1",
			},
			{"admission_year": "2026", "campus": "FPTU Ho Chi Minh Campus"},
			index=0,
		)
		self.assertEqual(values["import_source_id"], "crm-demo-showcase:bulk:bulk-student-001")
		self.assertEqual(values["cohort_start_year"], 2026)
		self.assertEqual(values["cohort_end_year"], 2029)
		self.assertEqual(values["high_school"], "school-1")
		self.assertEqual(values["province"], "Hồ Chí Minh")
		self.assertEqual(values["ward"], "ward-1")

