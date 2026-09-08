from unittest import TestCase

from crm.demo import seed_team_management
from crm.demo.seed_assignment_conversion_scenarios import (
	DUPLICATE_ID,
	SCENARIOS,
	UNMANAGED_PROVINCE,
	_team_by_province,
)


class TestSeedAssignmentConversionScenarios(TestCase):
	def test_fixture_contains_twenty_uniquely_identified_leads(self):
		self.assertEqual(len(SCENARIOS), 20)
		self.assertEqual(len({row["phone"] for row in SCENARIOS}), 20)
		# Intake must accept every Lead, so the seeded identifiers stay unique;
		# the duplicate is only created afterwards by a defect mutation.
		self.assertEqual(len({row["id"] for row in SCENARIOS}), 20)
		for row in SCENARIOS:
			self.assertTrue(row["province"])
			self.assertTrue(row["school"])
			self.assertTrue(row["major"])
			self.assertTrue(row["id"])

	def test_twelve_leads_are_conversion_ready_and_eight_carry_one_defect(self):
		happy = [row for row in SCENARIOS if "defect" not in row]
		defects = [row for row in SCENARIOS if "defect" in row]
		self.assertEqual(len(happy), 12)
		self.assertEqual(len(defects), 8)
		self.assertEqual(
			{row["defect"]["code"] for row in defects},
			{
				"INVALID_MISSING_MAJOR",
				"INVALID_MISSING_HIGH_SCHOOL",
				"INVALID_MISSING_PHONE",
				"MISSING_PROVINCE",
				"MISSING_CAMPUS",
				"TEAM_NOT_FOUND_FOR_PROVINCE",
				"DUPLICATE_PRIMARY",
				"DUPLICATE_RESUBMIT",
			},
		)
		for row in defects:
			self.assertEqual(row["defect"]["expected"], "manual_review")
			self.assertTrue(row["defect"]["note"])

	def test_duplicate_pair_collapses_onto_one_national_id(self):
		"""Both halves must end on one CCCD, or neither closes as DUPLICATE."""
		primary = next(row for row in SCENARIOS if row.get("defect", {}).get("code") == "DUPLICATE_PRIMARY")
		resubmit = next(row for row in SCENARIOS if row.get("defect", {}).get("code") == "DUPLICATE_RESUBMIT")
		self.assertEqual(primary["id"], DUPLICATE_ID)
		self.assertEqual(primary["defect"]["fields"], {})
		self.assertEqual(resubmit["defect"]["fields"], {"id_number": DUPLICATE_ID})
		self.assertNotEqual(resubmit["id"], DUPLICATE_ID)

	def test_every_scenario_province_has_a_seeded_team(self):
		"""Intake needs an active Team pool per province, or no Lead can be created."""
		teams = _team_by_province()
		self.assertEqual(
			set(teams),
			{fixture["province"] for fixture in seed_team_management.GROUP_FIXTURES},
		)
		for row in SCENARIOS:
			self.assertIn(row["province"], teams)

	def test_the_unmanaged_province_defect_targets_a_province_without_a_team(self):
		"""The routing defect only fires while no seeded Team covers that province."""
		self.assertNotIn(UNMANAGED_PROVINCE, _team_by_province())
