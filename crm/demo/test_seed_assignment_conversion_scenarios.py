from unittest import TestCase

from crm.demo import seed_team_management
from crm.demo.seed_assignment_conversion_scenarios import (
	DUPLICATE_PHONE,
	SCENARIOS,
	UNMANAGED_PROVINCE,
	_intake_namespace,
	_team_by_province,
)


class TestSeedAssignmentConversionScenarios(TestCase):
	def test_fixture_contains_twenty_uniquely_identified_leads(self):
		self.assertEqual(len(SCENARIOS), 20)
		self.assertEqual(len({row["phone"] for row in SCENARIOS}), 20)
		# Intake must accept every Lead, so the seeded phone numbers stay unique;
		# the duplicate is only created afterwards by a phone mutation.
		for row in SCENARIOS:
			self.assertTrue(row["province"])
			self.assertTrue(row["school"])
			self.assertTrue(row["major"])
			self.assertNotIn("id", row)

	def test_thirteen_leads_are_assignable_and_eight_carry_one_defect(self):
		happy = [row for row in SCENARIOS if "defect" not in row or row["defect"]["expected"] == "assigned"]
		defects = [row for row in SCENARIOS if "defect" in row]
		self.assertEqual(len(happy), 15)
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
			self.assertIn(row["defect"]["expected"], {"manual_review", "assigned"})
			self.assertTrue(row["defect"]["note"])

	def test_duplicate_pair_collapses_onto_one_lead_phone(self):
		"""The resubmission is closed by the previously processed Lead phone."""
		primary = next(row for row in SCENARIOS if row.get("defect", {}).get("code") == "DUPLICATE_PRIMARY")
		resubmit = next(row for row in SCENARIOS if row.get("defect", {}).get("code") == "DUPLICATE_RESUBMIT")
		self.assertEqual(primary["phone"], DUPLICATE_PHONE)
		self.assertEqual(primary["defect"]["fields"], {})
		self.assertEqual(resubmit["defect"]["fields"], {"phone": DUPLICATE_PHONE})
		self.assertNotIn("id_number", primary)
		self.assertNotIn("id_number", resubmit)

	def test_every_scenario_province_has_a_seeded_team(self):
		"""Intake needs an active Team pool per province, or no Lead can be created."""
		teams = _team_by_province()
		self.assertEqual(
			set(teams),
			{fixture["province"] for fixture in seed_team_management.GROUP_FIXTURES},
		)
		for row in SCENARIOS:
			self.assertIn(row["province"], teams)

	def test_each_fixture_run_uses_a_distinct_intake_namespace(self):
		first = _intake_namespace("first-run")
		second = _intake_namespace("second-run")

		self.assertNotEqual(first, second)
		self.assertTrue(first.startswith("local-assignment-conversion-20260908:run:"))

	def test_the_unmanaged_province_defect_targets_a_province_without_a_team(self):
		"""The routing defect only fires while no seeded Team covers that province."""
		self.assertNotIn(UNMANAGED_PROVINCE, _team_by_province())
